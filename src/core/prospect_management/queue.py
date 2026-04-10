# -*- coding: utf-8 -*-
import logging
import asyncio
from typing import List, Optional, Dict, Any # Adicionado Dict, Any
from datetime import datetime
import pytz

from src.core.config import settings
# logger de config não é importado, pois o logger local é usado.

logger = logging.getLogger(__name__)

# Redis client will be initialized in main.py and assigned to settings.redis_client
# In-memory queue and event for new prospects
prospect_queue: asyncio.Queue[Dict[str, Optional[str]]] = asyncio.Queue() # ALTERADO O TIPO
new_prospect_event = asyncio.Event()

_cached_instance_prefix_queue = None
_cached_keys_queue = {}

def _get_instance_prefix_queue() -> str:
    global _cached_instance_prefix_queue
    if _cached_instance_prefix_queue is None:
        _cached_instance_prefix_queue = settings.INSTANCE_ID
    return _cached_instance_prefix_queue

def _get_prospected_set_key_queue() -> str:
    key_name = "prospected_set"
    if key_name not in _cached_keys_queue: 
        _cached_keys_queue[key_name] = f"prospected_numbers:{_get_instance_prefix_queue()}"
    return _cached_keys_queue[key_name]

def _get_queue_paused_key_queue() -> str:
    key_name = "queue_paused"
    if key_name not in _cached_keys_queue: 
        _cached_keys_queue[key_name] = f"queue:paused:{_get_instance_prefix_queue()}"
    return _cached_keys_queue[key_name]

async def add_jids_to_prospect_queue(leads_list: List[Dict[str, Optional[str]]]): # ALTERADO O TIPO DO ARGUMENTO
    logger.info(f"[QUEUE_ADD] Adicionando {len(leads_list)} leads (com nomes) à fila de prospecção.")
    if not leads_list: 
        logger.info("[QUEUE_ADD] Lista de leads vazia.")
        return

    if settings.redis_client:
        try:
            prospected_key = _get_prospected_set_key_queue()
            # Extrair apenas os JIDs para adicionar ao conjunto do Redis
            jids_only = [lead["number"] for lead in leads_list]
            added_to_set = await settings.redis_client.sadd(prospected_key, *jids_only)
            logger.info(f"[QUEUE_ADD] {added_to_set} novos JIDs adicionados ao conjunto Redis '{prospected_key}'.")
        except Exception as e_redis: 
            logger.error(f"[QUEUE_ADD] Erro ao adicionar JIDs ao conjunto Redis: {e_redis}", exc_info=True)
    else: 
        logger.warning("[QUEUE_ADD] Cliente Redis não disponível, JIDs não adicionados ao conjunto de prospectados.")

    added_count = 0
    for lead in leads_list: # Agora itera sobre dicionários
        try:
            await prospect_queue.put(lead) # Coloca o dicionário completo na fila
            added_count += 1
            logger.debug(f"[QUEUE_ADD] Lead {lead.get('number')} (Nome: {lead.get('name')}) adicionado à fila em memória.") # ATUALIZADO LOG
        except Exception as e_q: 
            logger.error(f"[QUEUE_ADD] Erro ao adicionar lead {lead.get('number')} à fila: {e_q}", exc_info=True)
    
    if added_count > 0:
        logger.info(f"[QUEUE_ADD] {added_count} leads adicionados à fila. Disparando evento.")
        new_prospect_event.set()
    else: 
        logger.info("[QUEUE_ADD] Nenhum lead efetivamente adicionado à fila.")

async def is_queue_paused() -> bool:
    logger.debug("[QUEUE_STATUS] Verificando se a fila está pausada.")
    if not settings.redis_client:
        logger.warning("[QUEUE_STATUS] Cliente Redis não disponível. Assumindo não pausada.")
        return False
    try:
        paused_str = await settings.redis_client.get(_get_queue_paused_key_queue())
        is_paused_val = paused_str == "true"
        # Log apenas em DEBUG para evitar spam (chamado frequentemente pelo loop principal)
        logger.debug(f"[QUEUE_STATUS] Fila está {'pausada' if is_paused_val else 'ativa'} (valor Redis: '{paused_str}').")
        return is_paused_val
    except Exception as e:
        logger.error(f"[QUEUE_STATUS] Erro ao verificar pausa: {e}. Assumindo não pausada.", exc_info=True)
        return False

async def pause_queue() -> bool:
    logger.info("[QUEUE_CONTROL] Solicitado PAUSAR processamento da fila.")
    if not settings.redis_client:
        logger.error("[QUEUE_CONTROL] Cliente Redis não disponível.")
        return False
    try:
        await settings.redis_client.set(_get_queue_paused_key_queue(), "true")
        # Adicionar timestamp da pausa para monitoramento
        pause_timestamp_key = f"queue:pause_timestamp:{_get_instance_prefix_queue()}"
        await settings.redis_client.set(pause_timestamp_key, datetime.now(pytz.utc).isoformat())
        logger.info(f"[QUEUE_CONTROL] Fila PAUSADA. Chave '{_get_queue_paused_key_queue()}' definida como 'true'.")
        return True
    except Exception as e:
        logger.error(f"[QUEUE_CONTROL] Erro ao pausar fila: {e}", exc_info=True)
        return False

async def resume_queue() -> bool:
    logger.info("[QUEUE_CONTROL] Solicitado RETOMAR processamento da fila.")
    if not settings.redis_client: 
        logger.error("[QUEUE_CONTROL] Cliente Redis não disponível.")
        return False
    try:
        await settings.redis_client.set(_get_queue_paused_key_queue(), "false")
        logger.info(f"[QUEUE_CONTROL] Fila RETOMADA. Chave '{_get_queue_paused_key_queue()}' definida como 'false'.")
        new_prospect_event.set() 
        return True
    except Exception as e: 
        logger.error(f"[QUEUE_CONTROL] Erro ao retomar fila: {e}", exc_info=True)
        return False

async def get_queue_size() -> int:
    q_size = prospect_queue.qsize()
    logger.debug(f"[QUEUE_INFO] Tamanho atual da fila em memória: {q_size}")
    return q_size

async def clear_queue() -> int:
    logger.info("[QUEUE_CONTROL] Solicitado LIMPAR fila em memória.")
    size_before = prospect_queue.qsize()
    cleared_count = 0
    while not prospect_queue.empty():
        try: 
            # Como a fila agora armazena dicionários, o tipo retornado por get_nowait() muda
            prospect_queue.get_nowait() # Não precisa usar o valor retornado, apenas esvaziar
            prospect_queue.task_done()
            cleared_count += 1
        except asyncio.QueueEmpty: 
            break
    logger.info(f"[QUEUE_CONTROL] Fila limpa. Removidos {cleared_count} itens. Tamanho antes: {size_before}, agora: {prospect_queue.qsize()}.")
    return cleared_count

async def get_all_jids_in_memory_queue() -> List[str]:
    """
    Retorna uma cópia de todos os JIDs atualmente na fila em memória, sem consumi-los.
    Adaptado para a fila que armazena dicionários {'number': 'jid', 'name': 'name'}.
    """
    logger.debug("[QUEUE_INFO] Obtendo todos os JIDs da fila em memória.")
    if prospect_queue.empty():
        logger.info("[QUEUE_INFO] Fila em memória está vazia.")
        return []
    
    try:
        current_items_raw = list(prospect_queue._queue) # Isso retorna a lista de dicionários
        jids_only = [item["number"] for item in current_items_raw if "number" in item] # Extrai apenas JIDs
        logger.info(f"[QUEUE_INFO] {len(jids_only)} JIDs encontrados na fila em memória.")
        return jids_only
    except AttributeError:
        logger.error("[QUEUE_INFO] Não foi possível acessar o atributo interno '_queue' da asyncio.Queue. A implementação pode ter mudado.")
        return []
    except Exception as e:
        logger.error(f"[QUEUE_INFO] Erro inesperado ao tentar obter JIDs da fila: {e}", exc_info=True)
        return []

async def is_jid_in_prospected_set(jid: str) -> bool:
    """
    Verifica se um JID está no conjunto Redis de números prospectados.
    Esta é a verificação correta para saber se um lead foi prospectado,
    independentemente do status atual na fila de processamento.
    """
    logger.debug(f"[QUEUE_INFO] Verificando se JID '{jid}' está no conjunto de prospectados.")
    if not settings.redis_client:
        logger.warning("[QUEUE_INFO] Cliente Redis não disponível. Assumindo que JID não está prospectado.")
        return False

    try:
        prospected_key = _get_prospected_set_key_queue()
        is_member = await settings.redis_client.sismember(prospected_key, jid)
        logger.info(f"[QUEUE_INFO] JID '{jid}' {'está' if is_member else 'não está'} no conjunto de prospectados '{prospected_key}'.")
        return bool(is_member)
    except Exception as e:
        logger.error(f"[QUEUE_INFO] Erro ao verificar se JID '{jid}' está no conjunto de prospectados: {e}", exc_info=True)
        return False

# === SISTEMA DE MONITORAMENTO E HEALTH CHECK ===

# Cache para métricas de health check
_health_metrics = {
    "last_health_check": None,
    "consecutive_failures": 0,
    "last_processed_lead": None,
    "processor_restarts": 0,
    "redis_connection_failures": 0,
    "queue_stuck_count": 0
}

async def get_queue_health_status() -> Dict[str, Any]:
    """
    Retorna status detalhado de saúde da fila e sistema de processamento.
    """
    logger.debug("[QUEUE_HEALTH] Executando health check da fila.")

    health_status = {
        "queue_size": 0,
        "is_paused": False,
        "redis_connected": False,
        "processor_running": False,
        "last_activity": None,
        "health_score": 0,
        "issues": [],
        "metrics": _health_metrics.copy(),
        "timestamp": datetime.now(pytz.utc).isoformat()
    }

    try:
        # Verificar tamanho da fila
        health_status["queue_size"] = await get_queue_size()

        # Verificar se está pausada
        health_status["is_paused"] = await is_queue_paused()

        # Verificar conexão Redis
        if settings.redis_client:
            try:
                await settings.redis_client.ping()
                health_status["redis_connected"] = True
            except Exception as e:
                health_status["redis_connected"] = False
                health_status["issues"].append(f"Redis connection failed: {str(e)}")
                _health_metrics["redis_connection_failures"] += 1
        else:
            health_status["issues"].append("Redis client not initialized")

        # Verificar se o processador está rodando
        from src.core.prospect_management.main_prospect_logic import is_processing_queue_main
        health_status["processor_running"] = is_processing_queue_main

        if not is_processing_queue_main:
            health_status["issues"].append("Queue processor is not running")

        # Verificar se a fila está travada (muitos itens, processador rodando, mas sem progresso)
        if (health_status["queue_size"] > 5 and
            health_status["processor_running"] and
            not health_status["is_paused"] and
            _health_metrics["last_processed_lead"] and
            (datetime.now(pytz.utc) - _health_metrics["last_processed_lead"]).seconds > 300):
            health_status["issues"].append("Queue appears to be stuck - no progress in 5+ minutes")
            _health_metrics["queue_stuck_count"] += 1

        # Calcular health score (0-100)
        score = 100
        if health_status["issues"]:
            score -= len(health_status["issues"]) * 20
        if _health_metrics["consecutive_failures"] > 3:
            score -= 30
        if health_status["queue_size"] > 100:
            score -= 10  # Penalizar fila muito grande

        health_status["health_score"] = max(0, score)

        # Atualizar métricas
        _health_metrics["last_health_check"] = datetime.now(pytz.utc)
        if health_status["issues"]:
            _health_metrics["consecutive_failures"] += 1
        else:
            _health_metrics["consecutive_failures"] = 0

        logger.info(f"[QUEUE_HEALTH] Health check completed. Score: {health_status['health_score']}, Issues: {len(health_status['issues'])}")

    except Exception as e:
        logger.error(f"[QUEUE_HEALTH] Erro durante health check: {e}", exc_info=True)
        health_status["issues"].append(f"Health check failed: {str(e)}")
        health_status["health_score"] = 0
        _health_metrics["consecutive_failures"] += 1

    return health_status

async def auto_recover_queue_if_needed() -> bool:
    """
    Executa recuperação automática da fila se problemas forem detectados.
    """
    logger.info("[QUEUE_RECOVERY] Iniciando verificação para auto-recuperação.")

    health_status = await get_queue_health_status()
    recovery_performed = False

    try:
        # Recuperação 1: Reativar processador se parado
        if not health_status["processor_running"] and health_status["queue_size"] > 0:
            logger.warning("[QUEUE_RECOVERY] Processador parado com itens na fila. Tentando reiniciar...")
            from src.core.prospect_management.main_prospect_logic import start_queue_processor_main
            start_queue_processor_main()
            recovery_performed = True
            _health_metrics["processor_restarts"] += 1
            logger.info("[QUEUE_RECOVERY] Processador reiniciado.")

        # Recuperação 2: Retomar fila se pausada sem motivo aparente
        if health_status["is_paused"] and health_status["queue_size"] > 0:
            # Verificar se foi pausada recentemente (últimos 5 minutos)
            try:
                if settings.redis_client:
                    pause_timestamp_key = f"queue:pause_timestamp:{_get_instance_prefix_queue()}"
                    pause_time_str = await settings.redis_client.get(pause_timestamp_key)

                    should_resume = True
                    if pause_time_str:
                        try:
                            pause_time = datetime.fromisoformat(pause_time_str)
                            if (datetime.now(pytz.utc) - pause_time).seconds < 300:  # Pausada há menos de 5 min
                                should_resume = False
                        except:
                            pass  # Se erro ao parsear, assume que deve retomar

                    if should_resume:
                        logger.warning("[QUEUE_RECOVERY] Fila pausada há mais de 5 minutos com itens pendentes. Retomando...")
                        await resume_queue()
                        recovery_performed = True
                        logger.info("[QUEUE_RECOVERY] Fila retomada automaticamente.")
            except Exception as e:
                logger.error(f"[QUEUE_RECOVERY] Erro ao verificar timestamp de pausa: {e}")

        # Recuperação 3: Verificar e reconectar Redis se necessário
        if not health_status["redis_connected"]:
            logger.warning("[QUEUE_RECOVERY] Redis desconectado. Tentando reconectar...")
            try:
                from src.core.prospect_management.main_prospect_logic import initialize_redis_main
                await initialize_redis_main()
                if settings.redis_client:
                    await settings.redis_client.ping()
                    logger.info("[QUEUE_RECOVERY] Redis reconectado com sucesso.")
                    recovery_performed = True
            except Exception as e:
                logger.error(f"[QUEUE_RECOVERY] Falha ao reconectar Redis: {e}")

        # Recuperação 4: Resetar fila se travada há muito tempo
        if (_health_metrics["queue_stuck_count"] > 3 and
            health_status["queue_size"] > 0 and
            health_status["processor_running"]):
            logger.critical("[QUEUE_RECOVERY] Fila travada detectada múltiplas vezes. Executando reset do processador...")
            try:
                from src.core.prospect_management.main_prospect_logic import stop_queue_processor_main, start_queue_processor_main
                await stop_queue_processor_main()
                await asyncio.sleep(2)
                start_queue_processor_main()
                _health_metrics["queue_stuck_count"] = 0
                recovery_performed = True
                logger.info("[QUEUE_RECOVERY] Reset do processador completado.")
            except Exception as e:
                logger.error(f"[QUEUE_RECOVERY] Erro durante reset do processador: {e}")

        if recovery_performed:
            logger.info("[QUEUE_RECOVERY] Ações de recuperação executadas com sucesso.")
        else:
            logger.debug("[QUEUE_RECOVERY] Nenhuma ação de recuperação necessária.")

    except Exception as e:
        logger.error(f"[QUEUE_RECOVERY] Erro durante processo de auto-recuperação: {e}", exc_info=True)

    return recovery_performed

def mark_lead_processed():
    """
    Marca timestamp do último lead processado para monitoramento.
    """
    _health_metrics["last_processed_lead"] = datetime.now(pytz.utc)

logger.info("prospect_management.queue: Module loaded.")
