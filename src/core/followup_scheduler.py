# -*- coding: utf-8 -*-
"""
Follow-up Scheduler — Envio automático de cupons para clientes que
conversaram no WhatsApp mas não compraram na Shopify.

Fluxo:
1. Busca prospects que conversaram nos últimos N dias
2. Verifica na Shopify se cada um fez pedido recente
3. Se NÃO comprou → cria cupom personalizado na Shopify
4. Envia mensagem no WhatsApp com o cupom
5. Registra no BD (evita envio duplicado)
"""
import logging
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

import pytz

from src.core.config import settings

logger = logging.getLogger(__name__)

# Estado do scheduler
_scheduler_task: Optional[asyncio.Task] = None
_is_running: bool = False


# ─────────────────────────────────────────────
# Controle do scheduler
# ─────────────────────────────────────────────
def start_followup_scheduler():
    """Inicia o scheduler de follow-up em background."""
    global _scheduler_task, _is_running
    if _is_running:
        logger.warning("[FOLLOWUP] Scheduler já está rodando")
        return

    _is_running = True
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    logger.info("[FOLLOWUP] Scheduler iniciado")


async def stop_followup_scheduler():
    """Para o scheduler de follow-up."""
    global _scheduler_task, _is_running
    _is_running = False
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
    logger.info("[FOLLOWUP] Scheduler parado")


async def _scheduler_loop():
    """Loop principal do scheduler."""
    # Esperar 60s no startup para dar tempo de tudo inicializar
    await asyncio.sleep(60)

    while _is_running:
        try:
            config = await _get_followup_config()

            if not config.get("enabled"):
                logger.debug("[FOLLOWUP] Follow-up desabilitado. Dormindo...")
                await asyncio.sleep(3600)  # Verificar a cada 1h se foi habilitado
                continue

            # Verificar se está no horário permitido
            if not _is_within_schedule(config):
                logger.debug("[FOLLOWUP] Fora do horário permitido. Dormindo 30min...")
                await asyncio.sleep(1800)
                continue

            logger.info("[FOLLOWUP] Iniciando ciclo de verificação...")
            await _process_followup_cycle(config)

            # Dormir pelo intervalo configurado
            interval_hours = config.get("check_interval_hours", 6)
            sleep_seconds = interval_hours * 3600
            logger.info(f"[FOLLOWUP] Ciclo concluído. Próxima verificação em {interval_hours}h")
            await asyncio.sleep(sleep_seconds)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[FOLLOWUP] Erro no loop do scheduler: {e}", exc_info=True)
            await asyncio.sleep(300)  # Em caso de erro, esperar 5min e tentar de novo


# ─────────────────────────────────────────────
# Configuração
# ─────────────────────────────────────────────
async def _get_followup_config() -> Dict[str, Any]:
    """Busca configuração de follow-up do banco de dados."""
    try:
        from src.core.db_operations.config_crud import get_config_value

        enabled = await get_config_value("followup_enabled")
        check_interval = await get_config_value("followup_check_interval_hours")
        min_hours = await get_config_value("followup_min_hours_after_contact")
        max_hours = await get_config_value("followup_max_hours_after_contact")
        no_purchase_days = await get_config_value("followup_no_purchase_days")
        discount_pct = await get_config_value("followup_discount_percentage")
        discount_expiry = await get_config_value("followup_discount_expiry_days")
        discount_minimum = await get_config_value("followup_discount_minimum_subtotal")
        message_template = await get_config_value("followup_message_template")
        start_time = await get_config_value("followup_schedule_start_time")
        end_time = await get_config_value("followup_schedule_end_time")
        allowed_weekdays = await get_config_value("followup_allowed_weekdays")

        return {
            "enabled": enabled != "false",
            "check_interval_hours": int(check_interval or 6),
            "min_hours_after_contact": int(min_hours or 24),
            "max_hours_after_contact": int(max_hours or 168),
            "no_purchase_days": int(no_purchase_days or 7),
            "discount_percentage": float(discount_pct or 10),
            "discount_expiry_days": int(discount_expiry or 3),
            "discount_minimum_subtotal": float(discount_minimum) if discount_minimum else None,
            "message_template": json.loads(message_template) if message_template else _default_message_template(),
            "start_time": start_time or "09:00",
            "end_time": end_time or "20:00",
            "allowed_weekdays": json.loads(allowed_weekdays) if allowed_weekdays else [0, 1, 2, 3, 4, 5],
        }
    except Exception as e:
        logger.error(f"[FOLLOWUP] Erro ao buscar config: {e}", exc_info=True)
        return {"enabled": False}


def _default_message_template() -> str:
    return (
        "Oi, {nome}! 😊\n\n"
        "Vi que você conversou com a gente mas ainda não finalizou sua compra.\n\n"
        "Preparei um cupom especial pra você:\n\n"
        "🎁 *{desconto}% de desconto* com o código:\n"
        "👉 *{cupom}*\n\n"
        "⏰ Válido por {validade} dias!\n\n"
        "É só usar na hora de finalizar o pedido no site. Se precisar de ajuda, estou aqui! 🛍️"
    )


def _is_within_schedule(config: Dict) -> bool:
    """Verifica se está dentro do horário e dia da semana permitidos."""
    try:
        tz = pytz.timezone("America/Sao_Paulo")
        now = datetime.now(tz)

        # Verificar dia da semana (0=Monday, 6=Sunday)
        if now.weekday() not in config.get("allowed_weekdays", [0, 1, 2, 3, 4, 5]):
            return False

        # Verificar horário
        start = datetime.strptime(config.get("start_time", "09:00"), "%H:%M").time()
        end = datetime.strptime(config.get("end_time", "20:00"), "%H:%M").time()
        current_time = now.time()

        return start <= current_time <= end
    except Exception:
        return True  # Em caso de erro, permitir execução


# ─────────────────────────────────────────────
# Ciclo de processamento
# ─────────────────────────────────────────────
async def _process_followup_cycle(config: Dict):
    """
    Ciclo principal:
    1. Busca prospects elegíveis
    2. Filtra quem já recebeu follow-up
    3. Verifica compras na Shopify
    4. Envia cupons para quem não comprou
    """
    from src.core.shopify import get_shopify_client

    client = get_shopify_client()
    if not client:
        logger.warning("[FOLLOWUP] Shopify client não disponível. Pulando ciclo.")
        return

    # Buscar prospects elegíveis
    prospects = await _get_eligible_prospects(config)
    if not prospects:
        logger.info("[FOLLOWUP] Nenhum prospect elegível para follow-up neste ciclo")
        return

    logger.info(f"[FOLLOWUP] {len(prospects)} prospects elegíveis para verificação")

    sent_count = 0
    skipped_purchased = 0
    skipped_already_sent = 0
    errors = 0

    for prospect in prospects:
        if not _is_running:
            break

        jid = prospect["jid"]
        name = prospect.get("name", "")

        try:
            # Verificar se já recebeu follow-up recentemente
            already_sent = await _has_recent_followup(jid, days=config["no_purchase_days"])
            if already_sent:
                skipped_already_sent += 1
                continue

            # Verificar se fez compra na Shopify
            has_order = await client.has_recent_order(jid, days=config["no_purchase_days"])
            if has_order:
                skipped_purchased += 1
                logger.debug(f"[FOLLOWUP] {jid} já comprou recentemente. Pulando.")
                continue

            # Cliente elegível → criar cupom e enviar
            success = await _create_and_send_coupon(jid, name, config, client)
            if success:
                sent_count += 1
            else:
                errors += 1

            # Delay entre envios para não sobrecarregar
            await asyncio.sleep(5)

        except Exception as e:
            errors += 1
            logger.error(f"[FOLLOWUP] Erro ao processar {jid}: {e}", exc_info=True)

    logger.info(
        f"[FOLLOWUP] Ciclo concluído: "
        f"{sent_count} cupons enviados, "
        f"{skipped_purchased} já compraram, "
        f"{skipped_already_sent} já receberam follow-up, "
        f"{errors} erros"
    )


async def _get_eligible_prospects(config: Dict) -> List[Dict]:
    """
    Busca prospects que:
    - Têm conversa ativa (enviaram pelo menos 1 mensagem)
    - O último contato foi entre min_hours e max_hours atrás
    - Status ativo
    """
    if not settings.db_pool:
        return []

    min_hours = config.get("min_hours_after_contact", 24)
    max_hours = config.get("max_hours_after_contact", 168)
    instance_id = settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                    SELECT DISTINCT p.jid, p.name, p.email, p.last_interaction_at, p.created_at
                    FROM prospects p
                    INNER JOIN conversation_history ch
                        ON ch.instance_id = p.instance_id
                        AND ch.prospect_jid = p.jid
                        AND ch.role = 'user'
                    WHERE p.instance_id = %s
                        AND p.status = 'active'
                        AND p.last_interaction_at IS NOT NULL
                        AND p.last_interaction_at < NOW() - INTERVAL %s HOUR
                        AND p.last_interaction_at > NOW() - INTERVAL %s HOUR
                    ORDER BY p.last_interaction_at ASC
                    LIMIT 50
                """
                await cursor.execute(sql, (instance_id, min_hours, max_hours))
                rows = await cursor.fetchall()

                logger.info(f"[FOLLOWUP] Query retornou {len(rows)} prospects elegíveis")
                return list(rows) if rows else []

    except Exception as e:
        logger.error(f"[FOLLOWUP] Erro ao buscar prospects elegíveis: {e}", exc_info=True)
        return []


async def _has_recent_followup(jid: str, days: int = 7) -> bool:
    """Verifica se já enviamos follow-up para esse JID nos últimos N dias."""
    if not settings.db_pool:
        return False

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                    SELECT 1 FROM followup_history
                    WHERE instance_id = %s
                        AND jid = %s
                        AND sent_at > NOW() - INTERVAL %s DAY
                    LIMIT 1
                """
                await cursor.execute(sql, (settings.INSTANCE_ID, jid, days))
                result = await cursor.fetchone()
                return result is not None

    except Exception as e:
        logger.error(f"[FOLLOWUP] Erro ao verificar followup anterior para {jid}: {e}")
        return True  # Em caso de erro, não enviar (segurança anti-spam)


async def _create_and_send_coupon(
    jid: str,
    name: str,
    config: Dict,
    shopify_client,
) -> bool:
    """
    Cria cupom personalizado na Shopify e envia via WhatsApp.

    O código do cupom é único por cliente: LOJA-{4 chars aleatórios}-{últimos 4 do tel}
    """
    try:
        discount_pct = config["discount_percentage"]
        expiry_days = config["discount_expiry_days"]
        minimum_subtotal = config.get("discount_minimum_subtotal")
        message_template = config["message_template"]

        # Gerar código único
        phone_suffix = jid.replace("@s.whatsapp.net", "")[-4:]
        random_part = uuid.uuid4().hex[:4].upper()
        coupon_code = f"VIP-{random_part}-{phone_suffix}"

        # Datas
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=expiry_days)).isoformat()

        # Criar cupom na Shopify
        logger.info(f"[FOLLOWUP] Criando cupom {coupon_code} ({discount_pct}% off) para {jid}")

        discount_result = await shopify_client.create_discount_code(
            code=coupon_code,
            title=f"Follow-up WhatsApp - {jid} - {now.strftime('%d/%m')}",
            percentage=discount_pct,
            starts_at=now.isoformat(),
            ends_at=expires_at,
            usage_limit=1,
            applies_once_per_customer=True,
            minimum_subtotal=minimum_subtotal,
        )

        if not discount_result:
            logger.error(f"[FOLLOWUP] Falha ao criar cupom na Shopify para {jid}")
            return False

        shopify_discount_id = discount_result.get("id", "")

        # Montar mensagem personalizada
        display_name = name or "cliente"
        message = message_template.format(
            nome=display_name,
            desconto=int(discount_pct),
            cupom=coupon_code,
            validade=expiry_days,
        )

        # Enviar via WhatsApp
        from src.core import evolution
        from src.utils.formatting import format_number_for_evolution

        formatted_jid = format_number_for_evolution(jid)
        if not formatted_jid:
            logger.error(f"[FOLLOWUP] JID inválido para envio: {jid}")
            return False

        send_result = await evolution.send_text_message(jid=formatted_jid, text=message)

        if not send_result:
            logger.error(f"[FOLLOWUP] Falha ao enviar mensagem para {jid}")
            await _save_followup_record(jid, coupon_code, discount_pct, message, "failed", shopify_discount_id)
            return False

        # Registrar no BD
        await _save_followup_record(jid, coupon_code, discount_pct, message, "sent", shopify_discount_id)

        # Registrar no histórico de conversa
        from src.core.prospect_management.state import add_message_to_history_state
        await add_message_to_history_state(
            jid, "assistant", message,
            conversation_initiator_override="user",
        )
        await add_message_to_history_state(
            jid, "system",
            f"[FOLLOWUP] Cupom {coupon_code} ({discount_pct}% off, {expiry_days} dias) enviado automaticamente",
            conversation_initiator_override="user",
        )

        logger.info(f"[FOLLOWUP] Cupom {coupon_code} enviado com sucesso para {jid}")
        return True

    except Exception as e:
        logger.error(f"[FOLLOWUP] Erro ao criar/enviar cupom para {jid}: {e}", exc_info=True)
        return False


async def _save_followup_record(
    jid: str,
    discount_code: str,
    discount_percentage: float,
    message: str,
    status: str,
    shopify_discount_id: str = "",
):
    """Salva registro de follow-up no banco de dados."""
    if not settings.db_pool:
        return

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                    INSERT INTO followup_history
                        (instance_id, jid, followup_type, discount_code, discount_percentage,
                         message_sent, status, shopify_discount_id)
                    VALUES (%s, %s, 'no_purchase', %s, %s, %s, %s, %s)
                """
                await cursor.execute(sql, (
                    settings.INSTANCE_ID, jid,
                    discount_code, discount_percentage,
                    message, status, shopify_discount_id,
                ))
                logger.debug(f"[FOLLOWUP] Registro salvo para {jid}: status={status}")

    except Exception as e:
        logger.error(f"[FOLLOWUP] Erro ao salvar registro para {jid}: {e}", exc_info=True)


# ─────────────────────────────────────────────
# Funções de consulta (para endpoints da API)
# ─────────────────────────────────────────────
async def get_followup_stats(days: int = 30) -> Dict[str, Any]:
    """Retorna estatísticas de follow-up dos últimos N dias."""
    if not settings.db_pool:
        return {}

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                        SUM(CASE WHEN status = 'converted' THEN 1 ELSE 0 END) as converted,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                    FROM followup_history
                    WHERE instance_id = %s
                        AND sent_at > NOW() - INTERVAL %s DAY
                """
                await cursor.execute(sql, (settings.INSTANCE_ID, days))
                row = await cursor.fetchone()

                return {
                    "period_days": days,
                    "total": row.get("total", 0) if row else 0,
                    "sent": row.get("sent", 0) if row else 0,
                    "converted": row.get("converted", 0) if row else 0,
                    "failed": row.get("failed", 0) if row else 0,
                    "conversion_rate": (
                        round(row["converted"] / row["sent"] * 100, 1)
                        if row and row.get("sent", 0) > 0
                        else 0
                    ),
                }

    except Exception as e:
        logger.error(f"[FOLLOWUP] Erro ao buscar stats: {e}", exc_info=True)
        return {}


async def get_followup_history(limit: int = 50) -> List[Dict]:
    """Retorna histórico recente de follow-ups."""
    if not settings.db_pool:
        return []

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                    SELECT id, jid, followup_type, discount_code, discount_percentage,
                           status, sent_at, converted_at
                    FROM followup_history
                    WHERE instance_id = %s
                    ORDER BY sent_at DESC
                    LIMIT %s
                """
                await cursor.execute(sql, (settings.INSTANCE_ID, limit))
                rows = await cursor.fetchall()
                return list(rows) if rows else []

    except Exception as e:
        logger.error(f"[FOLLOWUP] Erro ao buscar histórico: {e}", exc_info=True)
        return []


async def mark_followup_converted(jid: str, order_name: str = ""):
    """
    Marca um follow-up como convertido (cliente comprou).
    Chamado pelo webhook de orders/create quando detecta uma compra.
    """
    if not settings.db_pool:
        return

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                    UPDATE followup_history
                    SET status = 'converted', converted_at = NOW()
                    WHERE instance_id = %s
                        AND jid = %s
                        AND status = 'sent'
                    ORDER BY sent_at DESC
                    LIMIT 1
                """
                await cursor.execute(sql, (settings.INSTANCE_ID, jid))
                if cursor.rowcount > 0:
                    logger.info(f"[FOLLOWUP] Follow-up para {jid} marcado como convertido (pedido: {order_name})")

    except Exception as e:
        logger.error(f"[FOLLOWUP] Erro ao marcar conversão para {jid}: {e}", exc_info=True)


logger.info("followup_scheduler.py: Módulo carregado.")
