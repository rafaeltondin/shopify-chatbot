# -*- coding: utf-8 -*-
"""
Webhook handlers para Evolution API v2
Compatível com payloads v1 e v2 da Evolution API
"""
import logging
import json
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import ValidationError

from src.core import prospect as prospect_manager
from src.api.routes.webhook_models import (
    WebhookPayload,
    WebhookMessageData,
    ConnectionUpdatePayload,
    normalize_event_name,
    EVENT_MAP_V2_TO_V1
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_instance_from_payload(payload_dict: dict) -> Optional[str]:
    """
    Extrai o nome da instância do payload, compatível com v1 e v2.
    v1 usa 'instance', v2 usa 'instanceName'
    """
    return payload_dict.get("instanceName") or payload_dict.get("instance")


def _is_valid_webhook_structure(payload_dict: dict) -> bool:
    """
    Verifica se o payload tem estrutura válida para webhook.
    Compatível com v1 (instance) e v2 (instanceName)
    """
    if not isinstance(payload_dict, dict):
        return False
    if "event" not in payload_dict:
        return False
    # Aceita tanto 'instance' (v1) quanto 'instanceName' (v2)
    if "instance" not in payload_dict and "instanceName" not in payload_dict:
        return False
    return True


@router.post("/webhook/messages-upsert", include_in_schema=False, tags=["Webhook"])
async def webhook_messages_upsert(request: Request, background_tasks: BackgroundTasks):
    """Rota específica para eventos messages.upsert (v1) / MESSAGES_UPSERT (v2)"""
    logger.info("[WEBHOOK_HANDLER] Rota específica /webhook/messages-upsert atingida.")
    return await _handle_webhook_request(request, background_tasks, event_path="messages.upsert")


@router.post("/webhook/MESSAGES_UPSERT", include_in_schema=False, tags=["Webhook"])
async def webhook_messages_upsert_v2(request: Request, background_tasks: BackgroundTasks):
    """Rota específica para eventos MESSAGES_UPSERT (formato v2)"""
    logger.info("[WEBHOOK_HANDLER] Rota específica /webhook/MESSAGES_UPSERT (v2) atingida.")
    return await _handle_webhook_request(request, background_tasks, event_path="messages.upsert")


@router.post("/webhook", include_in_schema=False, tags=["Webhook"])
async def webhook_root(request: Request, background_tasks: BackgroundTasks):
    """Rota raiz do webhook - detecta evento do payload"""
    logger.info("[WEBHOOK_HANDLER] Rota raiz /webhook atingida.")
    payload_dict_for_event_detection = {}
    event_from_payload = "unknown_event_parsing_failed"
    try:
        raw_body_for_event = await request.body()
        async def receive_body_again(): return {'type': 'http.request', 'body': raw_body_for_event, 'more_body': False}
        request_clone = Request(request.scope, receive_body_again)

        if raw_body_for_event:
            payload_dict_for_event_detection = json.loads(raw_body_for_event)
            event_from_payload = payload_dict_for_event_detection.get("event", "unknown_event_key_missing")
            logger.info(f"[WEBHOOK_HANDLER] Evento detectado do payload na rota raiz: '{event_from_payload}'")
        else:
            logger.warning("[WEBHOOK_HANDLER] Corpo da requisição vazio na rota raiz /webhook.")

        return await _handle_webhook_request(request_clone, background_tasks, event_path=event_from_payload)
    except json.JSONDecodeError as json_err:
        logger.error(f"[WEBHOOK_HANDLER] Erro ao decodificar JSON na rota raiz /webhook para determinar evento: {json_err}. Corpo (início): {raw_body_for_event[:200].decode(errors='ignore')}")
        return await _handle_webhook_request(request, background_tasks, event_path="unknown_json_decode_error")
    except Exception as e:
        logger.error(f"[WEBHOOK_HANDLER] Erro inesperado ao tentar detectar evento na rota raiz /webhook: {e}", exc_info=True)
        return await _handle_webhook_request(request, background_tasks, event_path="unknown_event_detection_exception")


@router.post("/webhook/{event_path:path}", include_in_schema=False, tags=["Webhook"])
async def webhook_generic(request: Request, background_tasks: BackgroundTasks, event_path: str = ""):
    """Rota genérica para qualquer evento via path"""
    logger.info(f"[WEBHOOK_HANDLER] Rota genérica /webhook/{{event_path}} atingida com event_path='{event_path}'")
    return await _handle_webhook_request(request, background_tasks, event_path=event_path)


async def _handle_webhook_request(request: Request, background_tasks: BackgroundTasks, event_path: str):
    """
    Handler principal de webhook - compatível com Evolution API v1 e v2.

    Diferenças tratadas:
    - v1 usa 'instance', v2 usa 'instanceName'
    - v1 usa eventos lowercase.dot.case, v2 usa UPPERCASE_SNAKE_CASE
    - v1 usa 'owner' em mensagens, v2 usa 'instanceId'
    """
    logger.info(f"[WEBHOOK_CORE] Processando webhook. Caminho do evento identificado: '{event_path}'. URL completa: {request.url.path}")
    logger.debug(f"[WEBHOOK_CORE] Cabeçalhos da requisição: {dict(request.headers)}")

    payload_dict = {}
    raw_body_bytes = b""
    try:
        raw_body_bytes = await request.body()
        if not raw_body_bytes:
            logger.warning(f"[WEBHOOK_CORE] Corpo da requisição está vazio para o evento '{event_path}'.")
            return {"status": "ignored_empty_payload"}

        logger.debug(f"[WEBHOOK_CORE] Corpo bruto recebido (primeiros 500 bytes) para evento '{event_path}': {raw_body_bytes[:500].decode(errors='ignore')}...")

        payload_dict = json.loads(raw_body_bytes)
        try:
            payload_log_str = json.dumps(payload_dict, indent=2, ensure_ascii=False)
            logger.debug(f"[WEBHOOK_CORE] Payload JSON parseado para evento '{event_path}':\n{payload_log_str}")
        except Exception as json_dump_err:
            logger.error(f"[WEBHOOK_CORE] Erro ao serializar payload parseado para log: {json_dump_err}")
            logger.debug(f"[WEBHOOK_CORE] Payload parseado (fallback dict): {payload_dict}")

        # Validação compatível com v1 e v2
        if not _is_valid_webhook_structure(payload_dict):
            logger.warning(f"[WEBHOOK_CORE] Payload inválido para evento '{event_path}'. Estrutura básica ausente (event, instance/instanceName). Chaves presentes: {list(payload_dict.keys())}")
            return {"status": "ignored_invalid_payload_structure"}

        webhook_data = WebhookPayload(**payload_dict)

        # Normalizar evento para formato interno (lowercase.dot.case)
        raw_event = webhook_data.event
        normalized_event = normalize_event_name(raw_event)

        # Usar método helper para obter nome da instância (compatível v1/v2)
        instance_name = webhook_data.get_instance_name()
        data_field = webhook_data.data

        logger.info(f"[WEBHOOK_CORE] Evento validado: '{raw_event}' -> normalizado: '{normalized_event}', Instância: '{instance_name}' (event_path original era '{event_path}')")

        # Processar evento messages.upsert (v1) / MESSAGES_UPSERT (v2)
        if normalized_event == "messages.upsert":
            logger.info(f"[WEBHOOK_CORE] Evento 'messages.upsert' detectado para instância '{instance_name}'.")
            if data_field is None:
                logger.warning(f"[WEBHOOK_CORE] Evento 'messages.upsert' recebido, mas o campo 'data' está ausente ou nulo. Payload: {payload_dict}")
                return {"status": "messages_upsert_data_missing"}

            messages_to_process = data_field if isinstance(data_field, list) else ([data_field] if isinstance(data_field, dict) else [])

            if not messages_to_process:
                logger.info(f"[WEBHOOK_CORE] Evento 'messages.upsert' não continha mensagens processáveis no campo 'data'. Data: {data_field}")
                return {"status": "messages_upsert_no_messages_in_data"}

            logger.debug(f"[WEBHOOK_CORE] Processando {len(messages_to_process)} mensagem(ns) do evento 'messages.upsert'.")
            # DEBUG: Log do sender no payload principal (pode conter número real na v2)
            logger.info(f"[WEBHOOK_CORE] [DEBUG_V2] Payload sender: {webhook_data.sender}")
            processed_count = 0
            for msg_idx, msg_dict_raw in enumerate(messages_to_process):
                 if not isinstance(msg_dict_raw, dict):
                     logger.warning(f"[WEBHOOK_CORE] Item {msg_idx} em 'data' não é um dicionário. Ignorando. Conteúdo: {str(msg_dict_raw)[:100]}")
                     continue
                 try:
                     # DEBUG: Log do payload raw completo para investigar estrutura v2
                     logger.info(f"[WEBHOOK_CORE] [DEBUG_V2] Payload raw keys: {list(msg_dict_raw.keys())}")
                     logger.info(f"[WEBHOOK_CORE] [DEBUG_V2] Payload raw (500 chars): {str(msg_dict_raw)[:500]}")
                     logger.debug(f"[WEBHOOK_CORE] Validando mensagem individual {msg_idx+1} do 'messages.upsert': {str(msg_dict_raw)[:200]}")
                     message_data_obj = WebhookMessageData(**msg_dict_raw)

                     # Verificar se a mensagem é de um grupo
                     if message_data_obj.key and message_data_obj.key.remoteJid and message_data_obj.key.remoteJid.endswith('@g.us'):
                         logger.info(f"[WEBHOOK_CORE] Mensagem {msg_idx+1} (ID: {message_data_obj.key.id}) é de um grupo ({message_data_obj.key.remoteJid}). Ignorando.")
                         continue # Pula para a próxima mensagem

                     logger.info(f"[WEBHOOK_CORE] Mensagem {msg_idx+1} (ID: {message_data_obj.key.id}, De: {message_data_obj.key.remoteJid}) validada. Adicionando à task de background para a instância '{instance_name}'.")
                     # Passar o instance_name para a task de background
                     background_tasks.add_task(prospect_manager.handle_incoming_message, message_data_obj, instance_name)
                     processed_count += 1
                 except ValidationError as msg_val_err:
                     logger.error(f"[WEBHOOK_CORE] Erro de validação Pydantic para mensagem individual {msg_idx+1}: {msg_val_err}. Dados da mensagem: {json.dumps(msg_dict_raw, ensure_ascii=False)}")
                 except Exception as proc_err:
                     logger.error(f"[WEBHOOK_CORE] Erro ao despachar mensagem individual {msg_idx+1} para task: {proc_err}. Dados: {json.dumps(msg_dict_raw, ensure_ascii=False)}", exc_info=True)

            logger.info(f"[WEBHOOK_CORE] Evento 'messages.upsert': {processed_count} de {len(messages_to_process)} mensagens despachadas para processamento em background.")
            return {"status": f"messages_upsert_dispatched_{processed_count}_of_{len(messages_to_process)}"}

        # Processar evento connection.update (v1) / CONNECTION_UPDATE (v2)
        elif normalized_event == "connection.update":
            logger.info(f"[WEBHOOK_CORE] Evento 'connection.update' detectado para instância '{instance_name}'.")
            try:
                conn_payload = ConnectionUpdatePayload(**payload_dict)
                state = conn_payload.data.state
                logger.info(f"[WEBHOOK_CORE] Atualização de conexão: Instância '{instance_name}' estado é agora '{state}'.")
                return {"status": f"connection_update_processed_state_{state}"}
            except ValidationError as conn_val_err:
                 logger.error(f"[WEBHOOK_CORE] Erro de validação Pydantic para payload 'connection.update': {conn_val_err}. Payload: {json.dumps(payload_dict, ensure_ascii=False)}")
                 return {"status": "error_connection_update_payload_validation"}

        # Processar evento qrcode.updated (v1) / QRCODE_UPDATED (v2)
        elif normalized_event == "qrcode.updated":
            logger.info(f"[WEBHOOK_CORE] Evento 'qrcode.updated' detectado para instância '{instance_name}'.")
            return {"status": "qrcode_updated_received", "instance": instance_name}

        # Processar evento application.startup (v1) / APPLICATION_STARTUP (v2)
        elif normalized_event == "application.startup":
            logger.info(f"[WEBHOOK_CORE] Evento 'application.startup' detectado para instância '{instance_name}'.")
            return {"status": "application_startup_received", "instance": instance_name}

        else:
            logger.info(f"[WEBHOOK_CORE] Evento '{raw_event}' (normalizado: '{normalized_event}') recebido para instância '{instance_name}', mas não há manipulador específico implementado.")
            return {"status": "event_received_unhandled", "event": raw_event, "normalized_event": normalized_event}

    except json.JSONDecodeError as json_err:
        logger.error(f"[WEBHOOK_CORE] Erro de decodificação JSON para evento '{event_path}': {json_err}. Corpo bruto (início): {raw_body_bytes.decode(errors='ignore')[:500]}...")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except ValidationError as pydantic_err:
        logger.error(f"[WEBHOOK_CORE] Erro de validação Pydantic para evento '{event_path}': {pydantic_err}. Payload que causou o erro: {json.dumps(payload_dict, indent=2, ensure_ascii=False)}")
        raise HTTPException(status_code=400, detail=f"Invalid webhook payload structure: {pydantic_err.errors()}")
    except Exception as e:
        logger.error(f"[WEBHOOK_CORE] Erro inesperado ao processar webhook para evento '{event_path}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error processing webhook")
