# -*- coding: utf-8 -*-
import logging
import json # Adicionado import json
from decimal import Decimal
from typing import Optional, List, Dict, Any, Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status, Query # Adicionado Query
from pydantic import BaseModel, Field

from src.core.security import User, get_current_user
from src.core import wallet_manager
from src.core.config import settings
from src.api.routes.wallet_models import (
    GenericResponse,
    WalletBalanceResponse,
    AddCreditRequest,
    InitiatePaymentResponse,
    WalletHistoryResponse,
    WalletTransactionItem,
    InitiatePaymentResponseData
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wallet", tags=["Wallet"])

# --- Endpoints da Wallet ---

@router.get("/balance", response_model=WalletBalanceResponse)
async def get_current_wallet_balance(current_user: User = Depends(get_current_user)):
    logger.info(f"[API_WALLET_BALANCE] Usuário {current_user.username} (instância {settings.INSTANCE_ID}) solicitando saldo da carteira.")
    balance = await wallet_manager.get_wallet_balance(settings.INSTANCE_ID)
    if balance is None: # get_wallet_balance agora retorna 0.00 se não existir, então None indicaria erro.
        logger.error(f"[API_WALLET_BALANCE] Erro ao buscar saldo para instância {settings.INSTANCE_ID}.")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao buscar saldo da carteira.")
    return WalletBalanceResponse(balance=balance)

@router.post("/add-credit/initiate", response_model=InitiatePaymentResponse)
async def initiate_add_credit_payment(
    request_data: AddCreditRequest, 
    current_user: User = Depends(get_current_user)
):
    instance_id = settings.INSTANCE_ID
    logger.info(f"[API_WALLET_ADD_CREDIT] Usuário {current_user.username} (instância {instance_id}) iniciando adição de crédito: {request_data.amount} BRL.")
    
    # Aqui, o frontend não especifica o método de pagamento (PIX/Cartão) ainda.
    # A API do Mercado Pago pode oferecer ambos no checkout.
    # Se precisarmos de fluxos diferentes para PIX vs Cartão desde o início, o frontend precisaria enviar.
    # Por ora, vamos assumir que o checkout do MP lida com isso.
    
    # O e-mail do pagador pode ser o e-mail do usuário logado, se disponível e desejado.
    # payer_email = current_user.email # Se o modelo User tiver email
    payer_email = None # Por enquanto, não vamos passar e-mail do pagador

    description = f"Recarga de créditos na carteira Innova Fluxo ({instance_id})"
    
    payment_init_data = await wallet_manager.initiate_mercado_pago_payment(
        instance_id=instance_id,
        amount_brl=request_data.amount,
        description=description,
        payer_email=payer_email 
    )

    if not payment_init_data:
        logger.error(f"[API_WALLET_ADD_CREDIT] Falha ao iniciar pagamento com Mercado Pago para instância {instance_id}.")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao iniciar processo de pagamento com Mercado Pago.")
    
    logger.info(f"[API_WALLET_ADD_CREDIT] Processo de pagamento iniciado com sucesso para instância {instance_id}. Preference ID: {payment_init_data['preference_id']}")
    return InitiatePaymentResponse(
        success=True,
        message="Processo de pagamento iniciado. Redirecione o usuário para o checkout.",
        data=InitiatePaymentResponseData(**payment_init_data)
    )

@router.post("/mercado-pago/webhook", status_code=http_status.HTTP_200_OK)
async def mercado_pago_webhook_receiver(request: Request):
    """Endpoint público para receber webhooks do Mercado Pago."""
    webhook_data = await request.json()
    logger.info(f"[API_MP_WEBHOOK] Webhook do Mercado Pago recebido. Action: {webhook_data.get('action')}, Type: {webhook_data.get('type')}")
    logger.debug(f"[API_MP_WEBHOOK] Dados completos do webhook: {webhook_data}")

    # Processar em background para responder rapidamente ao MP
    # background_tasks.add_task(wallet_manager.process_mercado_pago_webhook, webhook_data)
    # Por enquanto, processamento síncrono para simplificar. Em produção, usar background task.
    await wallet_manager.process_mercado_pago_webhook(webhook_data)
    
    return {"status": "webhook_received"}

@router.get("/history", response_model=WalletHistoryResponse)
async def get_wallet_transaction_history(
    current_user: User = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    instance_id = settings.INSTANCE_ID
    logger.info(f"[API_WALLET_HISTORY] Usuário {current_user.username} (instância {instance_id}) solicitando histórico da carteira. Limit: {limit}, Offset: {offset}")

    if not settings.db_pool:
        logger.error(f"[API_WALLET_HISTORY] DB Pool não disponível para instância {instance_id}.")
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro interno do servidor.")

    conn = None
    try:
        conn = await settings.db_pool.acquire()
        async with conn.cursor() as cursor:
            # Primeiro, obter o wallet_id para o instance_id
            wallet = await wallet_manager.get_or_create_wallet(instance_id, db_conn_or_pool=conn) # Passa a conexão
            if not wallet or 'id' not in wallet:
                logger.warning(f"[API_WALLET_HISTORY] Carteira não encontrada para instância {instance_id}. Retornando histórico vazio.")
                return WalletHistoryResponse(transactions=[], total_count=0)
            wallet_id = wallet['id']

            # Contar total de transações
            count_sql = "SELECT COUNT(*) as total FROM wallet_transactions WHERE wallet_id = %s"
            await cursor.execute(count_sql, (wallet_id,))
            total_row = await cursor.fetchone()
            total_count = total_row['total'] if total_row else 0

            # Buscar transações com paginação
            history_sql = """
                SELECT id, type, amount_brl, payment_method, payment_provider, transaction_id_provider, status, description, metadata, created_at 
                FROM wallet_transactions 
                WHERE wallet_id = %s 
                ORDER BY created_at DESC 
                LIMIT %s OFFSET %s
            """
            await cursor.execute(history_sql, (wallet_id, limit, offset))
            transactions_raw = await cursor.fetchall()
            
            transactions_list = []
            for row in transactions_raw:
                transactions_list.append(WalletTransactionItem(
                    id=row['id'],
                    type=row['type'],
                    amount_brl=row['amount_brl'],
                    payment_method=row.get('payment_method'),
                    payment_provider=row.get('payment_provider'),
                    transaction_id_provider=row.get('transaction_id_provider'),
                    status=row['status'],
                    description=row.get('description'),
                    metadata=json.loads(row['metadata']) if row['metadata'] else None,
                    created_at=row['created_at'].isoformat() if row['created_at'] else None
                ))
            
            logger.info(f"[API_WALLET_HISTORY] {len(transactions_list)} transações retornadas para wallet_id {wallet_id} (Total: {total_count}).")
            return WalletHistoryResponse(transactions=transactions_list, total_count=total_count)

    except Exception as e:
        logger.error(f"[API_WALLET_HISTORY] Erro ao buscar histórico da carteira para instância {instance_id}: {e}", exc_info=True)
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao buscar histórico da carteira.")
    finally:
        if conn:
            settings.db_pool.release(conn)

logger.info("API routes for Wallet loaded.")
