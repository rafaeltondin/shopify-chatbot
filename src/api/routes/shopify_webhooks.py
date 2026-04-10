# -*- coding: utf-8 -*-
"""
Webhook handlers para eventos da Shopify.
Recebe notificações de novos pedidos, fulfillments, carrinhos abandonados, etc.
"""
import logging
import json
import hmac
import hashlib
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from src.core.config import settings
from src.core.shopify import get_shopify_client
from src.core.prospect_management.state import get_prospect, add_message_to_history_state
from src.core.db_operations import prospect_crud

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shopify-webhook", tags=["Shopify Webhooks"])


# ─────────────────────────────────────────────
# Validação de HMAC (segurança Shopify)
# ─────────────────────────────────────────────
def _verify_shopify_hmac(body: bytes, hmac_header: str) -> bool:
    """Verifica a assinatura HMAC do webhook da Shopify."""
    secret = settings.SHOPIFY_WEBHOOK_SECRET
    if not secret:
        logger.warning("SHOPIFY_WEBHOOK_SECRET não configurado. Pulando validação HMAC.")
        return True  # Permite em dev sem secret

    computed_hmac = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()

    import base64
    computed_hmac_b64 = base64.b64encode(computed_hmac).decode("utf-8")
    return hmac.compare_digest(computed_hmac_b64, hmac_header)


# ─────────────────────────────────────────────
# Helper: Enviar mensagem WhatsApp ao cliente
# ─────────────────────────────────────────────
async def _notify_customer_whatsapp(phone: str, message: str):
    """Envia notificação ao cliente via WhatsApp (Evolution API)."""
    if not phone:
        logger.warning("Tentativa de notificar cliente sem número de telefone")
        return

    try:
        from src.core import evolution
        from src.utils.formatting import clean_phone_number

        clean_number = clean_phone_number(phone)
        if clean_number:
            await evolution.send_text_message(clean_number, message)
            logger.info(f"Notificação WhatsApp enviada para {clean_number}")
        else:
            logger.warning(f"Número de telefone inválido para notificação: {phone}")
    except Exception as e:
        logger.error(f"Erro ao enviar notificação WhatsApp para {phone}: {e}", exc_info=True)


# ─────────────────────────────────────────────
# Webhook: Novo Pedido (orders/create)
# ─────────────────────────────────────────────
@router.post("/orders/create")
async def webhook_order_created(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe webhook quando um novo pedido é criado na Shopify.
    Envia confirmação ao cliente via WhatsApp e atualiza dados no BD.
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _verify_shopify_hmac(body, hmac_header):
        raise HTTPException(status_code=401, detail="HMAC inválido")

    try:
        order_data = json.loads(body)
        order_name = order_data.get("name", "N/A")
        customer = order_data.get("customer", {})
        phone = customer.get("phone", "")
        email = customer.get("email", "")
        total = order_data.get("total_price", "0")
        currency = order_data.get("currency", "BRL")

        logger.info(f"[SHOPIFY_WEBHOOK] Novo pedido: {order_name}, Total: {currency} {total}, Tel: {phone}")

        # Atualizar dados do prospect/cliente no BD
        if phone:
            background_tasks.add_task(
                _process_new_order,
                phone=phone,
                email=email,
                order_name=order_name,
                total=total,
                order_data=order_data,
            )

        return {"status": "ok", "order": order_name}
    except Exception as e:
        logger.error(f"[SHOPIFY_WEBHOOK] Erro ao processar orders/create: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno")


async def _process_new_order(phone: str, email: str, order_name: str, total: str, order_data: dict):
    """Processa novo pedido em background."""
    try:
        # Buscar itens do pedido
        items = order_data.get("line_items", [])
        item_names = [f"• {i.get('quantity', 1)}x {i.get('title', 'Item')}" for i in items[:5]]
        items_text = "\n".join(item_names)

        # Mensagem de confirmação
        message = (
            f"✅ *Pedido {order_name} confirmado!*\n\n"
            f"*Itens:*\n{items_text}\n\n"
            f"💰 *Total: R$ {float(total):.2f}*\n\n"
            f"Acompanhe seu pedido a qualquer momento me enviando o número *{order_name}*.\n"
            f"Obrigado pela compra! 🎉"
        )

        # Verificar se notificações estão habilitadas
        from src.core.db_operations.config_crud import get_config_value
        notifications_enabled = await get_config_value("shopify_order_notification_enabled")
        if notifications_enabled != "false":
            await _notify_customer_whatsapp(phone, message)

        # Atualizar dados do prospect
        from src.utils.formatting import clean_phone_number
        clean_number = clean_phone_number(phone)
        if clean_number:
            prospect = await get_prospect(clean_number)
            if prospect:
                await add_message_to_history_state(
                    clean_number,
                    "system",
                    f"[SHOPIFY] Novo pedido criado: {order_name} — Total: R$ {float(total):.2f}",
                    conversation_initiator_override=prospect.conversation_initiator
                )

        # Verificar se o cliente tinha follow-up pendente (cupom) → marcar como convertido
        try:
            from src.core.followup_scheduler import mark_followup_converted
            from src.utils.formatting import clean_phone_number
            clean_number = clean_phone_number(phone)
            if clean_number:
                await mark_followup_converted(clean_number, order_name)
        except Exception as e_conv:
            logger.debug(f"[SHOPIFY_WEBHOOK] Erro ao verificar conversão de follow-up: {e_conv}")

        logger.info(f"[SHOPIFY_WEBHOOK] Pedido {order_name} processado com sucesso")
    except Exception as e:
        logger.error(f"[SHOPIFY_WEBHOOK] Erro ao processar pedido {order_name}: {e}", exc_info=True)


# ─────────────────────────────────────────────
# Webhook: Pedido Enviado (orders/fulfilled)
# ─────────────────────────────────────────────
@router.post("/orders/fulfilled")
async def webhook_order_fulfilled(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe webhook quando um pedido é despachado/enviado.
    Notifica o cliente com informações de rastreamento.
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _verify_shopify_hmac(body, hmac_header):
        raise HTTPException(status_code=401, detail="HMAC inválido")

    try:
        order_data = json.loads(body)
        order_name = order_data.get("name", "N/A")
        customer = order_data.get("customer", {})
        phone = customer.get("phone", "")

        # Buscar tracking info
        fulfillments = order_data.get("fulfillments", [])
        tracking_number = ""
        tracking_url = ""
        for f in fulfillments:
            tracking_number = f.get("tracking_number", "")
            tracking_url = f.get("tracking_url", "")
            if tracking_number:
                break

        logger.info(f"[SHOPIFY_WEBHOOK] Pedido enviado: {order_name}, Rastreio: {tracking_number}")

        if phone:
            tracking_text = ""
            if tracking_number:
                tracking_text = f"\n📋 *Código de rastreio:* {tracking_number}"
                if tracking_url:
                    tracking_text += f"\n🔗 Rastrear: {tracking_url}"

            message = (
                f"📦 *Pedido {order_name} foi enviado!*\n"
                f"{tracking_text}\n\n"
                f"Se precisar de qualquer ajuda, é só me enviar uma mensagem! 😊"
            )

            background_tasks.add_task(_notify_customer_whatsapp, phone, message)

        return {"status": "ok", "order": order_name}
    except Exception as e:
        logger.error(f"[SHOPIFY_WEBHOOK] Erro ao processar orders/fulfilled: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno")


# ─────────────────────────────────────────────
# Webhook: Carrinho Abandonado (checkouts/create)
# ─────────────────────────────────────────────
@router.post("/checkouts/create")
async def webhook_checkout_created(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe webhook quando um checkout é criado (potencial carrinho abandonado).
    Armazena para posterior follow-up se não for convertido em pedido.
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _verify_shopify_hmac(body, hmac_header):
        raise HTTPException(status_code=401, detail="HMAC inválido")

    try:
        checkout_data = json.loads(body)
        checkout_token = checkout_data.get("token", "N/A")
        email = checkout_data.get("email", "")
        phone = checkout_data.get("phone", "")
        abandoned_url = checkout_data.get("abandoned_checkout_url", "")
        total = checkout_data.get("total_price", "0")

        logger.info(f"[SHOPIFY_WEBHOOK] Checkout criado: {checkout_token}, Email: {email}, Tel: {phone}")

        # Nota: A lógica de carrinho abandonado (follow-up após X horas) deve ser
        # implementada no scheduler. Aqui apenas registramos o evento.
        if phone:
            from src.utils.formatting import clean_phone_number
            clean_number = clean_phone_number(phone)
            if clean_number:
                prospect = await get_prospect(clean_number)
                if prospect:
                    await add_message_to_history_state(
                        clean_number,
                        "system",
                        f"[SHOPIFY] Checkout iniciado (possível carrinho abandonado). Token: {checkout_token}, Total: R$ {float(total):.2f}, URL: {abandoned_url}",
                        conversation_initiator_override=prospect.conversation_initiator
                    )

        return {"status": "ok", "checkout_token": checkout_token}
    except Exception as e:
        logger.error(f"[SHOPIFY_WEBHOOK] Erro ao processar checkouts/create: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno")


# ─────────────────────────────────────────────
# Webhook: Pedido Cancelado (orders/cancelled)
# ─────────────────────────────────────────────
@router.post("/orders/cancelled")
async def webhook_order_cancelled(request: Request, background_tasks: BackgroundTasks):
    """Recebe webhook quando um pedido é cancelado."""
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")

    if not _verify_shopify_hmac(body, hmac_header):
        raise HTTPException(status_code=401, detail="HMAC inválido")

    try:
        order_data = json.loads(body)
        order_name = order_data.get("name", "N/A")
        customer = order_data.get("customer", {})
        phone = customer.get("phone", "")
        cancel_reason = order_data.get("cancel_reason", "não informado")

        logger.info(f"[SHOPIFY_WEBHOOK] Pedido cancelado: {order_name}, Motivo: {cancel_reason}")

        if phone:
            message = (
                f"❌ *Pedido {order_name} foi cancelado*\n\n"
                f"Se você não solicitou esse cancelamento ou tem alguma dúvida, "
                f"por favor me envie uma mensagem para que possamos resolver!"
            )
            background_tasks.add_task(_notify_customer_whatsapp, phone, message)

        return {"status": "ok", "order": order_name}
    except Exception as e:
        logger.error(f"[SHOPIFY_WEBHOOK] Erro ao processar orders/cancelled: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno")


logger.info("shopify_webhooks.py: Módulo carregado.")
