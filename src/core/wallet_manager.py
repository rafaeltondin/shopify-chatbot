# -*- coding: utf-8 -*-
import logging
import time
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any

try:
    import mercadopago
except ImportError:
    mercadopago = None  # Mercado Pago não é necessário para o chatbot Shopify
from pydantic import BaseModel, Field
try:
    from pydantic import EmailStr, HttpUrl
except ImportError:
    EmailStr = str
    HttpUrl = str

from src.core.config import settings, logger

logger = logging.getLogger(__name__)

# Constantes para cálculo de custo de LLM
TOKENS_PER_UNIT_COST = Decimal('1000000') # 1 milhão de tokens
COST_PER_UNIT_BRL = Decimal('10.00')    # R$ 10,00
MINIMUM_CHARGE_BRL = Decimal('0.01')    # Cobrança mínima de R$ 0,01 se houver custo

async def get_or_create_wallet(instance_id: str, db_conn_or_pool: Any = None) -> Optional[Dict[str, Any]]:
    """
    Busca uma carteira existente para o instance_id ou cria uma nova se não existir.
    Retorna um dicionário representando a carteira ou None em caso de erro.
    """
    logger.info(f"[WALLET_MANAGER] Buscando ou criando carteira para instance_id: {instance_id}")
    
    conn_to_use = None
    release_conn = False

    if db_conn_or_pool and hasattr(db_conn_or_pool, 'cursor'):
        conn_to_use = db_conn_or_pool
    elif settings.db_pool:
        conn_to_use = await settings.db_pool.acquire()
        release_conn = True
    else:
        logger.error(f"[WALLET_MANAGER] Pool de DB não disponível e nenhuma conexão fornecida para get_or_create_wallet (instance: {instance_id}).")
        return None

    if not conn_to_use:
        logger.error(f"[WALLET_MANAGER] Falha ao obter conexão com o DB para get_or_create_wallet (instance: {instance_id}).")
        return None

    try:
        async with conn_to_use.cursor() as cursor:
            select_sql = "SELECT id, instance_id, balance_brl, created_at, updated_at FROM wallets WHERE instance_id = %s"
            await cursor.execute(select_sql, (instance_id,))
            wallet_data = await cursor.fetchone()

            if wallet_data:
                logger.info(f"[WALLET_MANAGER] Carteira encontrada para instance_id {instance_id}: ID {wallet_data['id']}")
                return wallet_data
            else:
                logger.info(f"[WALLET_MANAGER] Carteira não encontrada para instance_id {instance_id}. Criando nova...")
                insert_sql = "INSERT INTO wallets (instance_id, balance_brl) VALUES (%s, %s)"
                await cursor.execute(insert_sql, (instance_id, Decimal('0.00')))
                wallet_id = cursor.lastrowid
                if not wallet_id:
                    raise Exception("Falha ao obter lastrowid após inserir nova carteira.")
                
                if release_conn:
                    await conn_to_use.commit()

                logger.info(f"[WALLET_MANAGER] Nova carteira criada com ID {wallet_id} para instance_id {instance_id}.")
                await cursor.execute(select_sql, (instance_id,))
                new_wallet_data = await cursor.fetchone()
                return new_wallet_data
    except Exception as e:
        logger.error(f"[WALLET_MANAGER] Erro em get_or_create_wallet para instance_id {instance_id}: {e}", exc_info=True)
        if release_conn and conn_to_use.get_transaction_status():
            try: 
                await conn_to_use.rollback()
            except Exception as rb_err: 
                logger.error(f"Erro durante rollback: {rb_err}")
        return None
    finally:
        if release_conn and conn_to_use:
            settings.db_pool.release(conn_to_use)

async def get_wallet_balance(instance_id: str) -> Optional[Decimal]:
    """Retorna o saldo da carteira para o instance_id ou None se não encontrada/erro."""
    logger.debug(f"[WALLET_MANAGER] Buscando saldo da carteira para instance_id: {instance_id}")
    wallet = await get_or_create_wallet(instance_id)
    if wallet and 'balance_brl' in wallet:
        balance = wallet['balance_brl']
        logger.info(f"[WALLET_MANAGER] Saldo para instance_id {instance_id}: {balance}")
        return Decimal(balance)
    logger.warning(f"[WALLET_MANAGER] Não foi possível obter saldo para instance_id {instance_id}.")
    return Decimal('0.00')

async def update_wallet_balance(wallet_id: int, amount_change_brl: Decimal, cursor: Any) -> bool:
    """
    Atualiza o saldo de uma carteira. Deve ser chamada dentro de uma transação existente.
    `cursor` é o cursor da transação ativa.
    """
    logger.info(f"[WALLET_MANAGER] Atualizando saldo da carteira ID {wallet_id} em {amount_change_brl}.")
    try:
        sql = "UPDATE wallets SET balance_brl = balance_brl + %s WHERE id = %s"
        await cursor.execute(sql, (amount_change_brl, wallet_id))
        if cursor.rowcount == 0:
            logger.error(f"[WALLET_MANAGER] Nenhuma carteira encontrada com ID {wallet_id} para atualizar saldo.")
            return False
        logger.info(f"[WALLET_MANAGER] Saldo da carteira ID {wallet_id} atualizado com sucesso.")
        return True
    except Exception as e:
        logger.error(f"[WALLET_MANAGER] Erro ao atualizar saldo da carteira ID {wallet_id}: {e}", exc_info=True)
        return False

async def record_transaction(
    wallet_id: int,
    type: str,
    amount_brl: Decimal,
    status: str,
    cursor: Any,
    payment_method: Optional[str] = None,
    payment_provider: Optional[str] = None,
    transaction_id_provider: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[int]:
    """Registra uma transação na carteira. Deve ser chamada dentro de uma transação existente."""
    logger.info(f"[WALLET_MANAGER] Registrando transação para wallet_id {wallet_id}: Tipo={type}, Valor={amount_brl}, Status={status}")
    try:
        sql = """
            INSERT INTO wallet_transactions 
            (wallet_id, type, amount_brl, payment_method, payment_provider, transaction_id_provider, status, description, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        metadata_json = json.dumps(metadata) if metadata else None
        await cursor.execute(sql, (
            wallet_id, type, amount_brl, payment_method, payment_provider, 
            transaction_id_provider, status, description, metadata_json
        ))
        transaction_id = cursor.lastrowid
        if not transaction_id:
            raise Exception("Falha ao obter lastrowid após inserir transação.")
        logger.info(f"[WALLET_MANAGER] Transação ID {transaction_id} registrada com sucesso para wallet_id {wallet_id}.")
        return transaction_id
    except Exception as e:
        logger.error(f"[WALLET_MANAGER] Erro ao registrar transação para wallet_id {wallet_id}: {e}", exc_info=True)
        return None

class MercadoPagoItem(BaseModel):
    title: str = Field(..., min_length=1)
    quantity: int = Field(1, ge=1)
    unit_price: float = Field(..., gt=0)
    currency_id: str = "BRL"

class MercadoPagoPayer(BaseModel):
    email: Optional[EmailStr] = None

class MercadoPagoPreferenceRequest(BaseModel):
    items: list[MercadoPagoItem]
    external_reference: Optional[str] = None
    notification_url: Optional[HttpUrl] = None
    back_urls: Optional[Dict[str, HttpUrl]] = None
    auto_return: Optional[str] = "approved"
    payer: Optional[MercadoPagoPayer] = None

async def initiate_mercado_pago_payment(
    instance_id: str,
    amount_brl: Decimal, 
    description: str, 
    payer_email: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    logger.info(f"[MP_PAYMENT] Iniciando pagamento Mercado Pago para instance_id {instance_id}, valor {amount_brl}")

    if not settings.MERCADOPAGO_ACCESS_TOKEN:
        logger.error("[MP_PAYMENT] MERCADOPAGO_ACCESS_TOKEN não configurado.")
        return None

    wallet = await get_or_create_wallet(instance_id)
    if not wallet or 'id' not in wallet:
        logger.error(f"[MP_PAYMENT] Não foi possível obter/criar carteira para instance_id {instance_id}.")
        return None
    wallet_id = wallet['id']

    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
    
    external_reference = f"wallet_{wallet_id}_tx_{int(time.time())}_{settings.INSTANCE_ID}"

    preference_data = {
        "items": [
            {
                "title": description,
                "quantity": 1,
                "unit_price": float(amount_brl),
                "currency_id": "BRL"
            }
        ],
        "back_urls": {
            "success": f"{settings.SITE_URL}/static/index.html#/wallet?mp_status=approved&ext_ref={external_reference}",
            "failure": f"{settings.SITE_URL}/static/index.html#/wallet?mp_status=failure&ext_ref={external_reference}",
            "pending": f"{settings.SITE_URL}/static/index.html#/wallet?mp_status=pending&ext_ref={external_reference}"
        },
        "auto_return": "approved",
        "notification_url": f"{settings.SITE_URL}/api/wallet/mercado-pago/webhook",
        "external_reference": external_reference
    }
    if payer_email:
        preference_data["payer"] = {"email": payer_email}

    logger.debug(f"[MP_PAYMENT] Dados da preferência Mercado Pago: {preference_data}")

    conn = None
    transaction_id = None
    try:
        if not settings.db_pool: 
            raise Exception("DB Pool não disponível")
        conn = await settings.db_pool.acquire()
        await conn.begin()
        try:
            async with conn.cursor() as cursor:
                transaction_id = await record_transaction(
                    wallet_id=wallet_id, type='credit', amount_brl=amount_brl, status='pending',
                    payment_method='mercado_pago', payment_provider='mercado_pago',
                    transaction_id_provider=None,
                    description=f"Recarga: {description}",
                    metadata={"external_reference": external_reference, "payer_email": payer_email},
                    cursor=cursor
                )
                if not transaction_id:
                    raise Exception("Falha ao registrar transação pendente no DB.")
            await conn.commit()
            logger.info(f"[MP_PAYMENT] Transação pendente ID {transaction_id} (ext_ref: {external_reference}) registrada para wallet {wallet_id}.")
        except Exception as e_tx_block:
            logger.error(f"[MP_PAYMENT] Erro dentro do bloco de transação para ext_ref {external_reference}: {e_tx_block}", exc_info=True)
            if conn.get_transaction_status():
                await conn.rollback()
            transaction_id = None
            raise
    except Exception as e_db_tx:
        logger.error(f"[MP_PAYMENT] Erro geral ao registrar transação pendente no DB para ext_ref {external_reference}: {e_db_tx}", exc_info=True)
        return None
    finally:
        if conn: 
            settings.db_pool.release(conn)

    preference_response = sdk.preference().create(preference_data)
    logger.debug(f"[MP_PAYMENT] Resposta da criação de preferência MP: {preference_response}")

    if preference_response and preference_response["status"] == 201:
        response_content = preference_response["response"]
        logger.info(f"[MP_PAYMENT] Preferência Mercado Pago criada com ID: {response_content['id']}, Init Point: {response_content['init_point']}")
        return {
            "preference_id": response_content["id"],
            "init_point": response_content["init_point"],
            "external_reference": external_reference,
            "db_transaction_id": transaction_id
        }
    else:
        error_msg = preference_response.get("response", {}).get("message", "Erro desconhecido do Mercado Pago") if preference_response else "Resposta inválida do Mercado Pago"
        logger.error(f"[MP_PAYMENT] Falha ao criar preferência Mercado Pago: {error_msg}")
        
        conn_fail = None
        try:
            if not settings.db_pool: 
                raise Exception("DB Pool não disponível para falha")
            conn_fail = await settings.db_pool.acquire()
            await conn_fail.begin()
            try:
                async with conn_fail.cursor() as cursor_fail:
                    await cursor_fail.execute("UPDATE wallet_transactions SET status = 'failed', description = %s WHERE id = %s", (f"Falha MP: {error_msg}", transaction_id))
                await conn_fail.commit()
            except Exception as e_update_block:
                logger.error(f"[MP_PAYMENT] Erro dentro do bloco de transação ao atualizar para 'failed' (ID: {transaction_id}): {e_update_block}", exc_info=True)
                if conn_fail.get_transaction_status(): 
                    await conn_fail.rollback()
        except Exception as e_conn_acquire_fail:
             logger.error(f"[MP_PAYMENT] Erro ao adquirir conexão para atualizar transação {transaction_id} para 'failed': {e_conn_acquire_fail}")
        finally:
            if conn_fail: 
                settings.db_pool.release(conn_fail)
        return None

async def debit_llm_token_usage(
    instance_id: str, 
    total_tokens_used: int, 
    llm_model_name: str,
    prospect_jid: Optional[str] = None
) -> bool:
    """
    Debita o custo do uso de tokens LLM da carteira do usuário.
    Retorna True se o débito for bem-sucedido, False caso contrário.
    """
    logger.info(f"[WALLET_DEBIT_LLM] Iniciando débito por uso de LLM para instance_id: {instance_id}. Tokens: {total_tokens_used}, Modelo: {llm_model_name}, Prospect: {prospect_jid or 'N/A'}")

    if total_tokens_used <= 0:
        logger.info(f"[WALLET_DEBIT_LLM] Nenhum token usado ({total_tokens_used}). Nenhum débito necessário.")
        return True

    # Calcular o custo
    cost_factor = Decimal(total_tokens_used) / TOKENS_PER_UNIT_COST
    calculated_cost_raw = cost_factor * COST_PER_UNIT_BRL
    
    # Arredondar para 2 casas decimais (padrão bancário)
    calculated_cost = calculated_cost_raw.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if calculated_cost <= Decimal('0'): # Se o custo arredondado for zero ou negativo (improvável, mas seguro)
        logger.info(f"[WALLET_DEBIT_LLM] Custo calculado ({calculated_cost_raw:.6f} BRL) é zero ou insignificante após arredondamento. Nenhum débito será feito.")
        return True
    
    # Aplicar cobrança mínima se o custo for muito pequeno, mas maior que zero
    if calculated_cost < MINIMUM_CHARGE_BRL:
        final_cost_to_debit = MINIMUM_CHARGE_BRL
        logger.info(f"[WALLET_DEBIT_LLM] Custo calculado ({calculated_cost:.2f} BRL) abaixo do mínimo. Aplicando débito mínimo de {MINIMUM_CHARGE_BRL:.2f} BRL.")
    else:
        final_cost_to_debit = calculated_cost
    
    logger.info(f"[WALLET_DEBIT_LLM] Custo final a ser debitado: {final_cost_to_debit:.2f} BRL (Tokens: {total_tokens_used}, Modelo: {llm_model_name})")

    wallet = await get_or_create_wallet(instance_id)
    if not wallet or 'id' not in wallet:
        logger.error(f"[WALLET_DEBIT_LLM] Falha ao obter/criar carteira para instance_id {instance_id}. Débito LLM não realizado.")
        return False
    wallet_id = wallet['id']
    current_balance = Decimal(wallet['balance_brl'])

    if current_balance < final_cost_to_debit:
        logger.warning(f"[WALLET_DEBIT_LLM] Saldo insuficiente para instance_id {instance_id}. Saldo: {current_balance:.2f} BRL, Custo: {final_cost_to_debit:.2f} BRL. Débito LLM não realizado.")
        # Opcional: Registrar uma transação de falha por saldo insuficiente
        # conn_fail_balance = None
        # try:
        #     if not settings.db_pool: raise Exception("DB Pool não disponível")
        #     conn_fail_balance = await settings.db_pool.acquire()
        #     await conn_fail_balance.begin()
        #     async with conn_fail_balance.cursor() as cursor_fail:
        #         await record_transaction(
        #             wallet_id=wallet_id, type='debit', amount_brl=final_cost_to_debit, status='failed_insufficient_funds',
        #             payment_method='system_debit', payment_provider='system',
        #             description=f"Falha débito LLM: Saldo insuficiente. Tokens: {total_tokens_used}, Modelo: {llm_model_name}",
        #             metadata={"tokens_used": total_tokens_used, "model": llm_model_name, "prospect_jid": prospect_jid, "cost_calculated_brl": float(final_cost_to_debit), "balance_at_attempt_brl": float(current_balance)},
        #             cursor=cursor_fail
        #         )
        #     await conn_fail_balance.commit()
        # except Exception as e_tx_fail:
        #     logger.error(f"[WALLET_DEBIT_LLM] Erro ao registrar transação de falha por saldo insuficiente: {e_tx_fail}", exc_info=True)
        #     if conn_fail_balance and conn_fail_balance.get_transaction_status(): await conn_fail_balance.rollback()
        # finally:
        #     if conn_fail_balance: settings.db_pool.release(conn_fail_balance)
        return False

    conn = None
    try:
        if not settings.db_pool: 
            raise Exception("DB Pool não disponível para débito LLM")
        conn = await settings.db_pool.acquire()
        await conn.begin()
        
        async with conn.cursor() as cursor:
            # Debitar da carteira
            debit_amount = -final_cost_to_debit # Passar valor negativo para update_wallet_balance
            balance_updated = await update_wallet_balance(wallet_id, debit_amount, cursor)
            if not balance_updated:
                raise Exception("Falha ao atualizar saldo da carteira durante débito LLM.")

            # Registrar a transação de débito
            transaction_description = f"Uso LLM: {total_tokens_used} tokens ({llm_model_name})"
            if prospect_jid:
                transaction_description += f" - Prospect: {prospect_jid}"
            
            transaction_id = await record_transaction(
                wallet_id=wallet_id,
                type='debit',
                amount_brl=final_cost_to_debit, # Valor positivo para o registro da transação
                status='completed',
                payment_method='system_debit',
                payment_provider='system',
                description=transaction_description,
                metadata={"tokens_used": total_tokens_used, "model": llm_model_name, "prospect_jid": prospect_jid, "cost_calculated_brl": float(final_cost_to_debit)},
                cursor=cursor
            )
            if not transaction_id:
                raise Exception("Falha ao registrar transação de débito LLM.")

        await conn.commit()
        new_balance = current_balance - final_cost_to_debit
        logger.info(f"[WALLET_DEBIT_LLM] Débito de {final_cost_to_debit:.2f} BRL realizado com sucesso para instance_id {instance_id}. Saldo anterior: {current_balance:.2f}, Saldo atual: {new_balance:.2f}. Transação ID: {transaction_id}")
        return True
    except Exception as e_debit:
        logger.error(f"[WALLET_DEBIT_LLM] Erro durante o processo de débito LLM para instance_id {instance_id}: {e_debit}", exc_info=True)
        if conn and conn.get_transaction_status():
            try: 
                await conn.rollback()
                logger.info(f"[WALLET_DEBIT_LLM] Rollback da transação de débito LLM realizado para instance_id {instance_id}.")
            except Exception as rb_err: 
                logger.error(f"[WALLET_DEBIT_LLM] Erro durante rollback da transação de débito LLM: {rb_err}")
        return False
    finally:
        if conn:
            settings.db_pool.release(conn)

async def process_mercado_pago_webhook(data: Dict[str, Any]):
    logger.info(f"[MP_WEBHOOK] Recebido webhook do Mercado Pago. Tipo: {data.get('type')}, Action: {data.get('action')}")
    logger.debug(f"[MP_WEBHOOK] Dados completos do webhook: {data}")

    if not settings.MERCADOPAGO_ACCESS_TOKEN:
        logger.error("[MP_WEBHOOK] MERCADOPAGO_ACCESS_TOKEN não configurado. Não é possível processar webhook.")
        return

    # TODO: Validar a origem da notificação (ex: usando X-Signature header se configurado)

    if data.get("type") == "payment" and data.get("data", {}).get("id"):
        payment_id = str(data["data"]["id"])
        logger.info(f"[MP_WEBHOOK] Processando notificação de pagamento ID: {payment_id}")
        
        sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
        payment_info_response = sdk.payment().get(payment_id)
        logger.debug(f"[MP_WEBHOOK] Resposta da API de pagamento MP para ID {payment_id}: {json.dumps(payment_info_response, indent=2)}") # Log completo da resposta da API MP

        if payment_info_response and payment_info_response["status"] == 200:
            payment_details = payment_info_response["response"]
            external_reference = payment_details.get("external_reference")
            mp_status = payment_details.get("status")
            
            if not external_reference:
                logger.error(f"[MP_WEBHOOK] Pagamento MP ID {payment_id} sem external_reference. Impossível rastrear transação interna.")
                return

            logger.info(f"[MP_WEBHOOK] Detalhes do pagamento MP ID {payment_id}: Status='{mp_status}', ExternalRef='{external_reference}'")

            conn = None
            try:
                if not settings.db_pool: 
                    raise Exception("DB Pool não disponível")
                conn = await settings.db_pool.acquire()
                await conn.begin()
                try:
                    async with conn.cursor() as cursor:
                        sql_find_tx = """
                            SELECT id, wallet_id, status, amount_brl 
                            FROM wallet_transactions 
                            WHERE JSON_EXTRACT(metadata, '$.external_reference') = %s 
                            ORDER BY created_at DESC LIMIT 1 
                        """
                        await cursor.execute(sql_find_tx, (external_reference,))
                        internal_tx = await cursor.fetchone()

                        if not internal_tx:
                            logger.error(f"[MP_WEBHOOK] Nenhuma transação interna PENDENTE encontrada para external_reference: {external_reference}")
                            await cursor.rollback()
                            return
                        
                        internal_tx_id = internal_tx['id']
                        wallet_id = internal_tx['wallet_id']
                        current_internal_status = internal_tx['status']
                        transaction_amount_brl = internal_tx['amount_brl']

                        logger.info(f"[MP_WEBHOOK] Transação interna ID {internal_tx_id} (Wallet: {wallet_id}) encontrada para ext_ref {external_reference}. Status atual: {current_internal_status}")

                        if current_internal_status == 'completed':
                            logger.warning(f"[MP_WEBHOOK] Transação interna ID {internal_tx_id} já está 'completed'. Webhook possivelmente duplicado. Ignorando.")
                            await cursor.rollback()
                            return

                        new_internal_status = None
                        update_balance = False

                        if mp_status == "approved":
                            new_internal_status = "completed"
                            update_balance = True
                        elif mp_status in ["pending", "in_process"]:
                            new_internal_status = "pending"
                        elif mp_status in ["rejected", "cancelled", "refunded", "charged_back"]:
                            new_internal_status = "failed" if mp_status == "rejected" else mp_status
                        else:
                            logger.warning(f"[MP_WEBHOOK] Status MP '{mp_status}' não mapeado diretamente. Transação {internal_tx_id} não será alterada por este webhook.")
                            await cursor.rollback()
                            return

                        if new_internal_status and new_internal_status != current_internal_status:
                            sql_update_tx = "UPDATE wallet_transactions SET status = %s, transaction_id_provider = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
                            await cursor.execute(sql_update_tx, (new_internal_status, payment_id, internal_tx_id))
                            logger.info(f"[MP_WEBHOOK] Transação interna ID {internal_tx_id} atualizada para status '{new_internal_status}' com ID MP '{payment_id}'.")

                            if update_balance:
                                if await update_wallet_balance(wallet_id, transaction_amount_brl, cursor):
                                    logger.info(f"[MP_WEBHOOK] Saldo da carteira ID {wallet_id} atualizado com +{transaction_amount_brl} devido à transação {internal_tx_id} aprovada.")
                                else:
                                    logger.error(f"[MP_WEBHOOK] FALHA ao atualizar saldo da carteira ID {wallet_id} para transação {internal_tx_id}. Revertendo.")
                                    raise Exception("Falha na atualização de saldo da carteira.")
                        
                        await conn.commit()
                        logger.info(f"[MP_WEBHOOK] Processamento do webhook para external_reference {external_reference} concluído.")
                except Exception as e_webhook_block:
                    logger.error(f"[MP_WEBHOOK] Erro dentro do bloco de transação do webhook para ext_ref {external_reference}: {e_webhook_block}", exc_info=True)
                    if conn.get_transaction_status(): 
                        await conn.rollback()
            except Exception as e_db_webhook:
                logger.error(f"[MP_WEBHOOK] Erro geral de DB ao processar webhook para external_reference {external_reference}: {e_db_webhook}", exc_info=True)
            finally:
                if conn: 
                    settings.db_pool.release(conn)
        else:
            logger.error(f"[MP_WEBHOOK] Falha ao obter detalhes do pagamento MP ID {payment_id}. Status: {payment_info_response.get('status') if payment_info_response else 'N/A'}")
    else:
        logger.info(f"[MP_WEBHOOK] Webhook do Mercado Pago ignorado (tipo: {data.get('type')}, action: {data.get('action')}).")

logger.info("wallet_manager.py: Módulo carregado.")
