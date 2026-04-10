# -*- coding: utf-8 -*-
import logging
import asyncio
import random
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import redis.asyncio as redis
import pytz

# Timezone padrão: America/Sao_Paulo (GMT-3)
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

from src.core.config import settings, logger
from src.core.prospect_management.state import (
    get_prospect, add_prospect_state, update_prospect_stage_state, 
    add_message_to_history_state, save_prospect
)
from src.core.prospect_management.queue import (
    add_jids_to_prospect_queue, is_queue_paused, pause_queue,
    resume_queue, get_queue_size, clear_queue, prospect_queue, new_prospect_event,
    get_all_jids_in_memory_queue, is_jid_in_prospected_set, _get_instance_prefix_queue
)
from src.core.prospect_management.message_handling import (
    handle_incoming_message_logic, start_message_processor, stop_message_processor
)
from src.core.prospect_management.flow_logic import process_queued_prospect_flow
from src.core.prospect_management.scheduler import (
    start_follow_up_scheduler_sch, stop_follow_up_scheduler_sch,
    start_wallet_checker_sch, stop_wallet_checker_sch
)
from src.core.prospect_management.statistics import (
    get_total_prospected_count_stats, get_funnel_counts_stats, 
    get_messages_sent_count_stats, get_active_prospect_count_stats,
    clear_all_redis_history_stats
)
from src.core.db_operations import config_crud, prospect_crud

logger = logging.getLogger(__name__)

# --- Global variables for prospect_management main logic ---
queue_processor_task_main: Optional[asyncio.Task] = None
is_processing_queue_main: bool = False

# --- Redis Initialization (called from main application startup) ---
async def initialize_redis_main():
    if not settings.redis_client:
        try:
            logger.info(f"[PROSPECT_MAIN_REDIS] Connecting to Redis at {settings.REDIS_URL}...")
            settings.redis_client = await redis.from_url(settings.REDIS_URL, decode_responses=True)
            await settings.redis_client.ping()
            logger.info("[PROSPECT_MAIN_REDIS] Redis connection successful.")
            # Initialize queue paused key if not exists
            from src.core.prospect_management.queue import _get_queue_paused_key_queue
            await settings.redis_client.setnx(_get_queue_paused_key_queue(), "false")
        except Exception as e:
            logger.critical(f"[PROSPECT_MAIN_REDIS] CRITICAL: Failed to connect/initialize Redis: {e}", exc_info=True)
            settings.redis_client = None
    else:
        logger.info("[PROSPECT_MAIN_REDIS] Redis client already initialized.")

async def close_redis_main():
    if settings.redis_client:
        try:
            await settings.redis_client.close()
            logger.info("[PROSPECT_MAIN_REDIS] Redis connection closed.")
        except Exception as e:
            logger.error(f"[PROSPECT_MAIN_REDIS] Error closing Redis connection: {e}", exc_info=True)
        finally:
            settings.redis_client = None
            logger.info("[PROSPECT_MAIN_REDIS] Redis client set to None.")

# --- Queue Processor Control (Main Logic) ---
def start_queue_processor_main():
    global queue_processor_task_main, is_processing_queue_main
    logger.debug("[PROSPECT_MAIN_QUEUE_CTRL] Checking need to start main queue processor.")
    if not is_processing_queue_main:
        if queue_processor_task_main is None or queue_processor_task_main.done():
            is_processing_queue_main = True
            new_prospect_event.set() 
            try:
                loop = asyncio.get_running_loop()
                queue_processor_task_main = loop.create_task(_queue_processor_loop_main())
                logger.info("[PROSPECT_MAIN_QUEUE_CTRL] Main queue processor task (re)started.")
            except RuntimeError:
                logger.error("[PROSPECT_MAIN_QUEUE_CTRL] No asyncio loop running. Task not created.")
                is_processing_queue_main = False
        else: logger.debug("[PROSPECT_MAIN_QUEUE_CTRL] Main task already active and not done.")
    else: logger.debug("[PROSPECT_MAIN_QUEUE_CTRL] Main processor already marked as running.")

async def stop_queue_processor_main():
    global queue_processor_task_main, is_processing_queue_main
    logger.info("[PROSPECT_MAIN_QUEUE_CTRL] Attempting to stop main queue processor.")
    is_processing_queue_main = False
    new_prospect_event.set()

    if queue_processor_task_main and not queue_processor_task_main.done():
        logger.info("[PROSPECT_MAIN_QUEUE_CTRL] Cancelling active main task...")
        queue_processor_task_main.cancel()
        try:
            await asyncio.wait_for(queue_processor_task_main, timeout=5.0)
            logger.info("[PROSPECT_MAIN_QUEUE_CTRL] Main task cancelled and awaited.")
        except asyncio.CancelledError: logger.info("[PROSPECT_MAIN_QUEUE_CTRL] Main task cancelled as expected.")
        except asyncio.TimeoutError: logger.warning("[PROSPECT_MAIN_QUEUE_CTRL] Timeout awaiting main task termination.")
        except Exception as e: logger.error(f"[PROSPECT_MAIN_QUEUE_CTRL] Error during main stop: {e}", exc_info=True)
        finally: queue_processor_task_main = None
    else: logger.info("[PROSPECT_MAIN_QUEUE_CTRL] No active main task to stop or already finished.")
    logger.info("[PROSPECT_MAIN_QUEUE_CTRL] Main stop process completed.")

async def _queue_processor_loop_main():
    global is_processing_queue_main
    logger.info("[PROSPECT_MAIN_QUEUE_LOOP] Main prospect queue processor loop started.")

    # Contador para executar monitoramento periodicamente
    monitoring_counter = 0
    monitoring_interval = 10  # A cada 10 iterações do loop

    try:
        while is_processing_queue_main:
            try:
                if await is_queue_paused():
                    logger.info("[PROSPECT_MAIN_QUEUE_LOOP] Queue is paused. Waiting for event...")
                    new_prospect_event.clear()
                    await new_prospect_event.wait()
                    logger.info("[PROSPECT_MAIN_QUEUE_LOOP] Woke up from paused state.")
                    continue

                logger.debug(f"[PROSPECT_MAIN_QUEUE_LOOP] Tentando obter lead da fila")
                try:
                    # Agora lead_data será o dicionário {"number": "...", "name": "..."}
                    lead_data = await asyncio.wait_for(prospect_queue.get(), timeout=1.0)
                    jid = lead_data["number"] # Extrai o JID real
                    name = lead_data.get("name") # Extrai o nome

                    logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Lead obtido da fila - JID: {jid}, Nome: {name}")
                    logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Iniciando processamento do prospect")

                    # Sistema de retry para falhas temporárias
                    max_retries = 3
                    retry_count = 0
                    process_result = None

                    while retry_count <= max_retries:
                        try:
                            process_result = await process_queued_prospect_flow(jid, name)
                            logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Resultado do processamento (tentativa {retry_count + 1}): {process_result}")

                            # Se obteve resultado válido, sair do loop de retry
                            if process_result and process_result not in ['ERROR_GETTING_PROSPECT', 'ERROR_IN_TASK']:
                                break

                        except Exception as e_process:
                            logger.error(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] Erro durante processamento (tentativa {retry_count + 1}): {e_process}", exc_info=True)
                            process_result = 'ERROR_IN_TASK'

                        retry_count += 1
                        if retry_count <= max_retries:
                            retry_delay = min(2 ** retry_count, 30)  # Exponential backoff, max 30s
                            logger.warning(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] Tentativa {retry_count} falhou. Aguardando {retry_delay}s antes da próxima tentativa...")
                            await asyncio.sleep(retry_delay)

                    # Marcar lead como processado para monitoramento
                    from src.core.prospect_management.queue import mark_lead_processed
                    mark_lead_processed()

                    if process_result == 'DEFERRED_OUTSIDE_HOURS':
                        logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Lead adiado - fora do horário permitido")
                        await prospect_queue.put(lead_data)
                        prospect_queue.task_done()
                        await asyncio.sleep(300)
                        continue
                    
                    if process_result == 'PROCESSED':
                        logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Processamento concluído com sucesso")
                        delays = await config_crud.get_prospecting_delays()
                        min_d, max_d = delays.get("min_delay"), delays.get("max_delay")
                        if min_d is not None and max_d is not None and max_d >= min_d:
                            actual_delay = random.uniform(min_d, max_d)
                            logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Aplicando delay aleatório: {actual_delay:.2f}s")
                            await asyncio.sleep(actual_delay)
                        else:
                            logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Usando delay padrão: {settings.QUEUE_PROCESSOR_SLEEP_TIME}s")
                            await asyncio.sleep(settings.QUEUE_PROCESSOR_SLEEP_TIME)
                    
                    elif process_result in ['ERROR_GETTING_PROSPECT', 'ERROR_IN_TASK', 'INVALID_JID', 'TASK_ALREADY_ACTIVE']:
                        logger.warning(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Processamento com problema: {process_result}")

                        # Se falhou múltiplas vezes, adicionar à dead letter queue
                        if retry_count > max_retries:
                            logger.error(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] Lead falhou após {max_retries} tentativas. Adicionando à dead letter queue.")
                            await _add_to_dead_letter_queue(lead_data, process_result, f"Failed after {max_retries} retries")

                        await asyncio.sleep(settings.QUEUE_PROCESSOR_SLEEP_TIME)
                    else:
                        logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Resultado não mapeado: {process_result}")
                        await asyncio.sleep(settings.QUEUE_PROCESSOR_SLEEP_TIME)

                    prospect_queue.task_done()
                    logger.info(f"[{jid}] [PROSPECT_MAIN_QUEUE_LOOP] [DEBUG] Task marcada como concluída na fila")

                except asyncio.TimeoutError:
                    if prospect_queue.empty():
                        logger.debug(f"[PROSPECT_MAIN_QUEUE_LOOP] Queue empty. Waiting for event (timeout {settings.QUEUE_EMPTY_WAIT_TIMEOUT}s).")
                        new_prospect_event.clear()
                        try: await asyncio.wait_for(new_prospect_event.wait(), timeout=settings.QUEUE_EMPTY_WAIT_TIMEOUT)
                        except asyncio.TimeoutError: logger.debug("[PROSPECT_MAIN_QUEUE_LOOP] Timeout waiting for new prospect. Continuing.")

                    # Executar monitoramento periodicamente quando fila está vazia
                    monitoring_counter += 1
                    if monitoring_counter >= monitoring_interval:
                        monitoring_counter = 0
                        await _monitor_and_recover_queue()

                    continue
            except asyncio.CancelledError: logger.info("[PROSPECT_MAIN_QUEUE_LOOP] Loop cancelled."); break
            except Exception as e: logger.error(f"[PROSPECT_MAIN_QUEUE_LOOP] Unexpected error: {e}", exc_info=True); await asyncio.sleep(5.0)
    finally:
        is_processing_queue_main = False
        logger.info("[PROSPECT_MAIN_QUEUE_LOOP] Main loop finished.")

# === SISTEMA DE DEAD LETTER QUEUE ===

async def _add_to_dead_letter_queue(lead_data: Dict[str, str], error_reason: str, error_details: str):
    """
    Adiciona um lead que falhou múltiplas vezes à dead letter queue para análise posterior.
    """
    logger.info(f"[DEAD_LETTER_QUEUE] Adicionando lead {lead_data.get('number')} à dead letter queue. Motivo: {error_reason}")

    if not settings.redis_client:
        logger.error("[DEAD_LETTER_QUEUE] Redis não disponível. Não é possível salvar na dead letter queue.")
        return

    try:
        dead_letter_key = f"dead_letter_queue:{_get_instance_prefix_queue()}"
        dead_letter_entry = {
            "jid": lead_data.get("number"),
            "name": lead_data.get("name"),
            "error_reason": error_reason,
            "error_details": error_details,
            "timestamp": datetime.now(SAO_PAULO_TZ).isoformat(),
            "retry_count": 0,
            "next_retry_at": (datetime.now(SAO_PAULO_TZ) + timedelta(minutes=5)).isoformat()  # Primeira retry em 5 minutos
        }

        # Adicionar ao Redis como uma lista
        await settings.redis_client.lpush(dead_letter_key, json.dumps(dead_letter_entry))

        # Manter apenas os últimos 1000 itens na dead letter queue
        await settings.redis_client.ltrim(dead_letter_key, 0, 999)

        logger.info(f"[DEAD_LETTER_QUEUE] Lead {lead_data.get('number')} adicionado à dead letter queue com sucesso.")

    except Exception as e:
        logger.error(f"[DEAD_LETTER_QUEUE] Erro ao adicionar lead à dead letter queue: {e}", exc_info=True)


# === SISTEMA DE RETRY AUTOMÁTICO PARA DEAD LETTER QUEUE ===

DLQ_MAX_RETRIES = 5  # Número máximo de retries antes de desistir permanentemente
DLQ_RETRY_INTERVALS = [5, 15, 30, 60, 120]  # Intervalos em minutos (exponential backoff)
_dlq_retry_task: Optional[asyncio.Task] = None
_is_dlq_retry_running: bool = False


async def get_dead_letter_queue_items(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Retorna itens da Dead Letter Queue.

    Args:
        limit: Número máximo de itens a retornar

    Returns:
        Lista de itens da DLQ
    """
    if not settings.redis_client:
        logger.warning("[DLQ_RETRY] Redis não disponível para obter itens da DLQ.")
        return []

    try:
        dead_letter_key = f"dead_letter_queue:{_get_instance_prefix_queue()}"
        items_json = await settings.redis_client.lrange(dead_letter_key, 0, limit - 1)
        return [json.loads(item) for item in items_json]
    except Exception as e:
        logger.error(f"[DLQ_RETRY] Erro ao obter itens da DLQ: {e}", exc_info=True)
        return []


async def retry_dead_letter_queue_item(item: Dict[str, Any]) -> bool:
    """
    Tenta reprocessar um item da Dead Letter Queue.

    Args:
        item: Item da DLQ com dados do lead

    Returns:
        True se o retry foi bem-sucedido, False caso contrário
    """
    jid = item.get("jid")
    name = item.get("name")
    retry_count = item.get("retry_count", 0)

    logger.info(f"[DLQ_RETRY] Tentando reprocessar lead {jid} (tentativa {retry_count + 1}/{DLQ_MAX_RETRIES})")

    try:
        # Recriar o lead_data no formato esperado pela fila
        lead_data = {"number": jid, "name": name}

        # Tentar processar novamente
        process_result = await process_queued_prospect_flow(jid, name)

        if process_result and process_result not in ['ERROR_GETTING_PROSPECT', 'ERROR_IN_TASK', 'INVALID_JID']:
            logger.info(f"[DLQ_RETRY] ✅ Lead {jid} reprocessado com sucesso! Resultado: {process_result}")
            return True
        else:
            logger.warning(f"[DLQ_RETRY] ⚠️ Lead {jid} falhou novamente com resultado: {process_result}")
            return False

    except Exception as e:
        logger.error(f"[DLQ_RETRY] ❌ Erro ao reprocessar lead {jid}: {e}", exc_info=True)
        return False


async def process_dead_letter_queue_retries():
    """
    Processa itens da Dead Letter Queue que estão prontos para retry.
    Remove itens que excedem o número máximo de retries.
    """
    logger.info("[DLQ_RETRY] Iniciando processamento de retries da Dead Letter Queue...")

    if not settings.redis_client:
        logger.warning("[DLQ_RETRY] Redis não disponível. Abortando processamento de DLQ.")
        return

    try:
        dead_letter_key = f"dead_letter_queue:{_get_instance_prefix_queue()}"
        items_json = await settings.redis_client.lrange(dead_letter_key, 0, -1)

        if not items_json:
            logger.info("[DLQ_RETRY] Dead Letter Queue está vazia.")
            return

        logger.info(f"[DLQ_RETRY] Encontrados {len(items_json)} itens na DLQ.")

        now = datetime.now(SAO_PAULO_TZ)
        items_to_keep = []
        items_processed = 0
        items_removed = 0

        for item_json in items_json:
            try:
                item = json.loads(item_json)
                jid = item.get("jid")
                retry_count = item.get("retry_count", 0)
                next_retry_at_str = item.get("next_retry_at")

                # Verificar se excedeu o número máximo de retries
                if retry_count >= DLQ_MAX_RETRIES:
                    logger.warning(f"[DLQ_RETRY] Lead {jid} excedeu máximo de {DLQ_MAX_RETRIES} retries. Removendo permanentemente.")
                    items_removed += 1

                    # Enviar alerta sobre remoção permanente
                    try:
                        from src.core.alerts import send_critical_alert
                        await send_critical_alert(
                            alert_type="DEAD_LETTER_QUEUE_FULL",
                            title="Lead removido permanentemente da DLQ",
                            message=f"O lead {jid} falhou {retry_count} vezes e foi removido permanentemente da Dead Letter Queue.",
                            metadata={"jid": jid, "retry_count": retry_count, "last_error": item.get("error_reason")}
                        )
                    except Exception as e:
                        logger.error(f"[DLQ_RETRY] Erro ao enviar alerta: {e}")

                    continue

                # Verificar se está na hora de fazer retry
                if next_retry_at_str:
                    try:
                        next_retry_at = datetime.fromisoformat(next_retry_at_str)
                        if next_retry_at > now:
                            # Ainda não é hora de fazer retry, manter na lista
                            items_to_keep.append(item_json)
                            continue
                    except Exception as e:
                        logger.warning(f"[DLQ_RETRY] Erro ao parsear next_retry_at para {jid}: {e}")

                # Tentar retry
                success = await retry_dead_letter_queue_item(item)
                items_processed += 1

                if success:
                    # Sucesso - não adicionar de volta à lista
                    logger.info(f"[DLQ_RETRY] ✅ Lead {jid} reprocessado com sucesso e removido da DLQ.")
                else:
                    # Falha - atualizar contadores e manter na lista
                    new_retry_count = retry_count + 1
                    retry_interval_minutes = DLQ_RETRY_INTERVALS[min(new_retry_count, len(DLQ_RETRY_INTERVALS) - 1)]
                    next_retry = now + timedelta(minutes=retry_interval_minutes)

                    item["retry_count"] = new_retry_count
                    item["next_retry_at"] = next_retry.isoformat()
                    item["last_retry_at"] = now.isoformat()

                    items_to_keep.append(json.dumps(item))
                    logger.info(f"[DLQ_RETRY] Lead {jid} falhou novamente. Próxima tentativa em {retry_interval_minutes} minutos.")

            except Exception as e:
                logger.error(f"[DLQ_RETRY] Erro ao processar item da DLQ: {e}", exc_info=True)
                # Em caso de erro, manter o item na lista
                items_to_keep.append(item_json)

        # Atualizar a DLQ com os itens restantes
        if items_to_keep:
            # Usar pipeline para operação atômica
            pipe = settings.redis_client.pipeline()
            pipe.delete(dead_letter_key)
            for item in items_to_keep:
                pipe.rpush(dead_letter_key, item)
            await pipe.execute()
        else:
            # DLQ está vazia após processamento
            await settings.redis_client.delete(dead_letter_key)

        logger.info(f"[DLQ_RETRY] Processamento concluído. Processados: {items_processed}, Removidos: {items_removed}, Restantes: {len(items_to_keep)}")

    except Exception as e:
        logger.error(f"[DLQ_RETRY] Erro no processamento da Dead Letter Queue: {e}", exc_info=True)


async def _dlq_retry_loop():
    """
    Loop de background que periodicamente processa retries da Dead Letter Queue.
    """
    global _is_dlq_retry_running

    logger.info("[DLQ_RETRY] Iniciando loop de retry da Dead Letter Queue...")

    while _is_dlq_retry_running:
        try:
            # Processar retries
            await process_dead_letter_queue_retries()

            # Aguardar antes da próxima verificação (1 minuto)
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("[DLQ_RETRY] Loop de retry cancelado.")
            break
        except Exception as e:
            logger.error(f"[DLQ_RETRY] Erro no loop de retry: {e}", exc_info=True)
            await asyncio.sleep(60)  # Aguardar antes de tentar novamente

    _is_dlq_retry_running = False
    logger.info("[DLQ_RETRY] Loop de retry finalizado.")


def start_dlq_retry_processor():
    """
    Inicia o processador de retry da Dead Letter Queue.
    """
    global _dlq_retry_task, _is_dlq_retry_running

    if _is_dlq_retry_running:
        logger.info("[DLQ_RETRY] Processador de retry já está em execução.")
        return

    _is_dlq_retry_running = True

    try:
        loop = asyncio.get_running_loop()
        _dlq_retry_task = loop.create_task(_dlq_retry_loop())
        logger.info("[DLQ_RETRY] Processador de retry da DLQ iniciado.")
    except RuntimeError:
        logger.error("[DLQ_RETRY] Sem loop asyncio disponível para iniciar processador de retry.")
        _is_dlq_retry_running = False


async def stop_dlq_retry_processor():
    """
    Para o processador de retry da Dead Letter Queue.
    """
    global _dlq_retry_task, _is_dlq_retry_running

    logger.info("[DLQ_RETRY] Parando processador de retry da DLQ...")
    _is_dlq_retry_running = False

    if _dlq_retry_task and not _dlq_retry_task.done():
        _dlq_retry_task.cancel()
        try:
            await asyncio.wait_for(_dlq_retry_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        finally:
            _dlq_retry_task = None

    logger.info("[DLQ_RETRY] Processador de retry da DLQ parado.")

# _get_instance_prefix_queue é importado diretamente de queue.py

# === SISTEMA DE RECUPERAÇÃO AUTOMÁTICA ===

async def _monitor_and_recover_queue():
    """
    Função para monitorar a saúde da fila e executar recuperação automática quando necessário.
    """
    logger.debug("[QUEUE_MONITOR] Executando monitoramento e recuperação automática da fila.")

    try:
        from src.core.prospect_management.queue import get_queue_health_status, auto_recover_queue_if_needed

        # Executar health check
        health_status = await get_queue_health_status()

        # Se health score está baixo, tentar recuperação automática
        if health_status["health_score"] < 70:
            logger.warning(f"[QUEUE_MONITOR] Health score baixo detectado: {health_status['health_score']}. Iniciando recuperação automática.")
            recovery_performed = await auto_recover_queue_if_needed()

            if recovery_performed:
                logger.info("[QUEUE_MONITOR] Ações de recuperação executadas.")
            else:
                logger.info("[QUEUE_MONITOR] Nenhuma ação de recuperação foi necessária.")

    except Exception as e:
        logger.error(f"[QUEUE_MONITOR] Erro durante monitoramento e recuperação: {e}", exc_info=True)

# --- Exposing functions from submodules for easier access from main.py or api/ ---
# State related
get_prospect_state = get_prospect
add_new_prospect_state = add_prospect_state
update_prospect_stage = update_prospect_stage_state
add_history_message = add_message_to_history_state

# Queue related
add_to_queue = add_jids_to_prospect_queue
get_is_queue_paused = is_queue_paused
pause_processing_queue = pause_queue
resume_processing_queue = resume_queue
get_current_queue_size = get_queue_size
clear_prospect_queue = clear_queue
get_current_jids_in_queue = get_all_jids_in_memory_queue

# Message Handling related
handle_incoming_message = handle_incoming_message_logic
start_message_handler = start_message_processor
stop_message_handler = stop_message_processor

# Scheduler related
start_follow_up_processing = start_follow_up_scheduler_sch
stop_follow_up_processing = stop_follow_up_scheduler_sch
start_wallet_checker = start_wallet_checker_sch
stop_wallet_checker = stop_wallet_checker_sch

# Statistics related
get_total_prospected = get_total_prospected_count_stats
get_funnel_data = get_funnel_counts_stats
get_messages_sent = get_messages_sent_count_stats
get_active_prospects = get_active_prospect_count_stats
clear_redis_data = clear_all_redis_history_stats

# Config related (from db_operations.config_crud, re-exported for convenience if prospect module is the main interface)
get_prospecting_schedule = config_crud.get_schedule_times
set_prospecting_schedule = config_crud.set_schedule_times
get_all_follow_up_rules = config_crud.get_follow_up_rules
set_all_follow_up_rules = config_crud.set_follow_up_rules

# DB related (from db_operations.prospect_crud, re-exported)
clear_db_leads = prospect_crud.clear_all_leads_from_db
clear_db_conversations = prospect_crud.clear_all_conversations_from_db

# Dead Letter Queue related
get_dlq_items = get_dead_letter_queue_items
retry_dlq_item = retry_dead_letter_queue_item
process_dlq_retries = process_dead_letter_queue_retries
start_dlq_processor = start_dlq_retry_processor
stop_dlq_processor = stop_dlq_retry_processor

async def clear_all_db_leads_and_conversations_main(instance_id: str):
    """Clears all leads and conversation history from the database for the given instance."""
    logger.info(f"[PROSPECT_MAIN_DB_CLEAR] Iniciando limpeza de leads e conversas para instância {instance_id}.")
    leads_cleared = await prospect_crud.clear_all_leads_from_db(instance_id)
    conversations_cleared = await prospect_crud.clear_all_conversations_from_db(instance_id)
    logger.info(f"[PROSPECT_MAIN_DB_CLEAR] Limpeza concluída para instância {instance_id}. Leads removidos: {leads_cleared}, Conversas removidas: {conversations_cleared}.")

logger.info("prospect_management.main_prospect_logic: Module loaded with DLQ retry system.")
