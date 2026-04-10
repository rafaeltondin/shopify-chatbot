# -*- coding: utf-8 -*-
import logging
from typing import Dict, Any, Optional, Literal
import sys # Adicionado para o handler de logging
from collections import Counter

# import redis.asyncio as redis # Removido, pois settings.redis_client é usado

from src.core.config import settings, logger
from src.core.db_operations import config_crud, prospect_crud
from src.core.prospect_management.queue import _get_prospected_set_key_queue, clear_queue

logger = logging.getLogger(__name__)

# Configuração de logging específica para este módulo para garantir a visibilidade dos logs
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout) # Log para stdout
    _formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [STATS_PY_LOG] %(message)s')
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
logger.setLevel(logging.INFO) # Garantir que INFO e acima sejam logados por este logger
logger.propagate = False # Evitar duplicação se o root logger também estiver configurado para stdout

# Redis client will be initialized in main.py and assigned to settings.redis_client

def _get_messages_sent_key_stats() -> str:
    # This key might be better defined in a shared redis_keys module if used by many
    return f"stats:messages_sent:{settings.INSTANCE_ID}"

async def get_total_prospected_count_stats(initiator: Optional[Literal['user', 'llm_agent']] = None) -> int:
    logger.info(f"[STATS_PROSPECT] Calculating total unique prospects, initiator: {initiator}.")
    if not settings.db_pool: # Check db_pool as this now queries DB
        logger.warning("[STATS_PROSPECT] DB pool not available. Returning 0."); return 0
    try:
        # Chama a nova função em prospect_crud que aceita initiator
        count = await prospect_crud.get_total_prospected_count_db(instance_id=settings.INSTANCE_ID, initiator=initiator)
        logger.info(f"[STATS_PROSPECT] Total unique prospects from DB: {count}, initiator: {initiator}")
        return count
    except Exception as e: 
        logger.error(f"[STATS_PROSPECT] Error getting prospected count from DB: {e}", exc_info=True)
        return 0

async def get_funnel_counts_stats(initiator: Optional[Literal['user', 'llm_agent']] = None) -> Dict[str, Any]:
    logger.info(f"[STATS_PROSPECT] Calculating funnel counts, initiator: {initiator}.")
    if not settings.db_pool: # Check db_pool
        logger.warning("[STATS_PROSPECT] DB pool not available. Returning empty funnel."); 
        return {"stages": [], "total_in_funnel": 0}
    try:
        sales_flow_cfg = await config_crud.get_sales_flow_stages()
        stage_map = {s["stage_number"]: s.get("objective", f"Estágio {s['stage_number']}") for s in sales_flow_cfg}
        
        # Busca dados dos estágios do funil baseados no 'current_stage' dos prospects ativos
        stage_data_from_db = await prospect_crud.get_funnel_stages_db(instance_id=settings.INSTANCE_ID, initiator=initiator)

        total_in_funnel = 0
        db_counts = {item['stage_number']: item['count'] for item in stage_data_from_db}
        
        # Usar o sales_flow_cfg como a fonte da verdade para os estágios
        raw_stages_from_db = []
        for stage_config in sales_flow_cfg:
            stage_num = stage_config["stage_number"]
            count = db_counts.pop(stage_num, 0) # Pega a contagem e remove do dict
            raw_stages_from_db.append({
                "stage_number": stage_num,
                "name": stage_config.get("objective", f"Estágio {stage_num}"),
                "count": count
            })
            total_in_funnel += count

        # Adicionar quaisquer estágios "órfãos" (presentes no DB mas não na config)
        if db_counts:
            orphaned_count = sum(db_counts.values())
            if orphaned_count > 0:
                raw_stages_from_db.append({
                    "stage_number": -1, # Usar um número que não conflite
                    "name": "Estágio Inválido/Antigo",
                    "count": orphaned_count
                })
                total_in_funnel += orphaned_count

        # Adicionar contagem de 'Agendamentos' (status='scheduled')
        # Verificar se a configuração do Google Calendar está ativa (exemplo: checando a API key)
        # Esta é uma simplificação; uma verificação mais robusta da configuração do calendário pode ser necessária.
        # Alterado para verificar 'google_calendar_refresh_token' como indicador de configuração do calendário
        google_calendar_config = await config_crud.get_config_value("google_calendar_refresh_token")
        logger.info(f"[STATS_PROSPECT] Valor de 'google_calendar_refresh_token' obtido de config_crud: '{google_calendar_config}' (Tipo: {type(google_calendar_config)})")
        
        scheduled_count = 0
        # A condição agora verifica se google_calendar_refresh_token existe e não é uma string vazia.
        if google_calendar_config and isinstance(google_calendar_config, str) and google_calendar_config.strip(): 
            logger.info(f"[STATS_PROSPECT] 'google_calendar_refresh_token' encontrado e não vazio. Buscando contagem de 'scheduled'.")
            scheduled_count = await prospect_crud.get_prospects_count_by_status_db(
                instance_id=settings.INSTANCE_ID, 
                status='scheduled', 
                initiator=initiator
            )
            logger.info(f"[STATS_PROSPECT] Contagem de leads 'scheduled' (status='scheduled') obtida: {scheduled_count}, para initiator: {initiator}")
            if scheduled_count > 0:
                logger.info(f"[STATS_PROSPECT] scheduled_count ({scheduled_count}) > 0. Adicionando estágio 'Agendamentos'.")
                # Adiciona como um "estágio" virtual ao final da lista para exibição no funil
                # Usamos um stage_number alto ou negativo para evitar colisão, ou um identificador especial.
                # Para simplificar, vamos usar um stage_number que provavelmente não colide (ex: 999)
                # O frontend precisará saber como lidar com este nome/número.
                # Melhor ainda, a API já retorna o nome "Agendamentos".
                raw_stages_from_db.append({
                    "stage_number": 999, # Identificador para o estágio de agendamentos
                    "name": "Agendamentos", # Nome a ser exibido
                    "count": scheduled_count
                })
                # Adicionar ao total_in_funnel se quisermos que ele reflita os agendados também.
                # Se 'total_in_funnel' deve refletir apenas os estágios do sales_flow, não some aqui.
                # Por ora, vamos somar para que o total reflita todos os cards visíveis.
                total_in_funnel += scheduled_count 
                logger.info(f"[STATS_PROSPECT] Adicionado estágio virtual 'Agendamentos' com {scheduled_count} prospects.")

        # Ordenar os estágios por stage_number para referência e cálculo cumulativo
        # Se 'Agendamentos' (999) deve aparecer no final, esta ordenação está OK.
        raw_stages_from_db.sort(key=lambda x: x["stage_number"])

        # Calcular contagens cumulativas (quantos chegaram PELO MENOS a este estágio)
        # Isso é feito iterando de trás para frente nos estágios ordenados.
        cumulative_counts = {}
        current_cumulative = 0
        # Iterar de trás para frente para calcular quantos chegaram *pelo menos* a cada estágio
        # Esta lógica de 'cumulative_counts' e 'denominator_base' pode precisar ser ajustada
        # se 'Agendamentos' for tratado de forma diferente nas taxas de conversão.
        # Por ora, a exibição é de contagens atuais por estágio/status.
        # A lógica de 'percentage_of_total' também é baseada na contagem atual do estágio.

        # Montar os dados finais do funil
        # Obter o total de prospects para calcular o percentual (considerando todos, incluindo agendados, para o denominador)
        # Se 'total_prospects_overall' deve ser apenas dos estágios do sales_flow, ajuste aqui.
        total_prospects_overall_for_percentage = await prospect_crud.get_total_prospected_count_db(instance_id=settings.INSTANCE_ID, initiator=initiator)
        # Se 'scheduled' não são contados como parte do 'total_prospected_count_db' (ex: se são 'completed' ou outro status final),
        # e você quer que o percentual de 'Agendamentos' seja em relação a um total que os inclua,
        # pode ser necessário somar 'scheduled_count' a 'total_prospects_overall_for_percentage' se eles não estiverem já incluídos.
        # Assumindo que get_total_prospected_count_db já inclui todos os prospects relevantes.

        funnel_data = []
        for stage_info in raw_stages_from_db: # Usar a lista que pode conter 'Agendamentos'
            stage_num = stage_info["stage_number"]
            actual_count_in_stage = stage_info["count"]
            
            percentage_of_total = 0.0
            if total_prospects_overall_for_percentage > 0:
                percentage_of_total = (actual_count_in_stage / total_prospects_overall_for_percentage) * 100
            
            funnel_data.append({
                "stage": stage_num,
                "name": stage_info["name"], # Já vem com "Agendamentos" se aplicável
                "count": actual_count_in_stage,
                "percentage_of_total": round(percentage_of_total, 2)
            })

        logger.info(f"[STATS_PROSPECT] Funnel counts (DB+Scheduled, initiator: {initiator}): {funnel_data}. Total in funnel (incl. scheduled): {total_in_funnel}. Total overall for percentage: {total_prospects_overall_for_percentage}.")
        return {"stages": funnel_data, "total_in_funnel": total_in_funnel}
    except Exception as e: 
        logger.error(f"[STATS_PROSPECT] Error calculating funnel counts (initiator: {initiator}): {e}", exc_info=True)
        return {"stages": [], "total_in_funnel": 0}

async def get_messages_sent_count_stats(initiator: Optional[Literal['user', 'llm_agent']] = None) -> int:
    logger.info(f"[STATS_PROSPECT] Getting total messages sent count, initiator: {initiator}.")
    if not settings.db_pool: # Check db_pool
        logger.warning("[STATS_PROSPECT] DB pool not available. Returning 0."); return 0
    try:
        # Chama a nova função em prospect_crud que aceita initiator
        count = await prospect_crud.get_messages_sent_count_db(instance_id=settings.INSTANCE_ID, initiator=initiator)
        logger.info(f"[STATS_PROSPECT] Total messages sent from DB: {count}, initiator: {initiator}")
        return count
    except Exception as e: 
        logger.error(f"[STATS_PROSPECT] Error getting messages sent count from DB: {e}", exc_info=True)
        return 0

async def get_active_prospect_count_stats(initiator: Optional[Literal['user', 'llm_agent']] = None) -> int:
    logger.info(f"[STATS_PROSPECT] Calculating active prospect count (from DB), initiator: {initiator}.")
    if not settings.db_pool: # Check if db_pool is initialized in settings
        logger.error("[STATS_PROSPECT] Database pool not available. Returning 0.")
        return 0
    try:
        # This function is now in prospect_crud
        count = await prospect_crud.get_active_prospect_count_db(instance_id=settings.INSTANCE_ID, initiator=initiator)
        logger.info(f"[STATS_PROSPECT] Active prospect count from DB: {count}, initiator: {initiator}")
        return count
    except Exception as e: 
        logger.error(f"[STATS_PROSPECT] Error getting active prospect count from DB (initiator: {initiator}): {e}", exc_info=True)
        return 0

async def clear_all_redis_history_stats():
    logger.info("[STATS_PROSPECT_CLEAR] Initiating complete Redis history clearing.")
    if not settings.redis_client:
        logger.error("[STATS_PROSPECT_CLEAR] Redis client not available. Clearing aborted.")
        return

    try:
        # Clear prospect queue (in-memory, but related to Redis state)
        # clear_queue já foi importado no topo
        await clear_queue()
        logger.info("[STATS_PROSPECT_CLEAR] In-memory prospect queue cleared.")

        # Delete all prospect state keys
        prospect_keys_pattern = f"prospect:{settings.INSTANCE_ID}:*"
        keys_to_delete = [key async for key in settings.redis_client.scan_iter(match=prospect_keys_pattern, count=100)]
        if keys_to_delete:
            deleted_count = await settings.redis_client.delete(*keys_to_delete)
            logger.info(f"[STATS_PROSPECT_CLEAR] {deleted_count} prospect state keys deleted from Redis.")
        
        # Delete prospected set
        prospected_set_key = _get_prospected_set_key_queue()
        await settings.redis_client.delete(prospected_set_key)
        logger.info(f"[STATS_PROSPECT_CLEAR] Prospected numbers set '{prospected_set_key}' deleted.")

        # Reset messages sent counter
        messages_sent_key = _get_messages_sent_key_stats()
        await settings.redis_client.set(messages_sent_key, "0")
        logger.info(f"[STATS_PROSPECT_CLEAR] Messages sent counter '{messages_sent_key}' reset to 0.")
        
        logger.info("[STATS_PROSPECT_CLEAR] Redis history clearing completed.")
    except Exception as e:
        logger.error(f"[STATS_PROSPECT_CLEAR] Error during Redis history clearing: {e}", exc_info=True)

logger.info("prospect_management.statistics: Module loaded.")
