# -*- coding: utf-8 -*-
import logging
import asyncio
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query # Adicionado Query
from pydantic import ValidationError

from src.core import prospect as prospect_manager

from src.core.db_operations.prospect_crud import get_funnel_analytics_db
from src.api.routes.dashboard_models import (
    DashboardStatsResponse, DashboardFunnelResponse,
    ConversationInitiator,
    ToggleAIQueueOnlyRequest,
    DashboardAnalyticsResponse
)
from src.api.routes.wallet_models import GenericResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Endpoint para controle de IA por fila de prospecção ---
@router.get("/dashboard/ai-queue-only", response_model=GenericResponse, tags=["Dashboard"])
async def get_ai_queue_only_status():
    logger.info("[API_DASH_AI_QUEUE_ONLY] Buscando status da flag 'AI para leads da fila de prospecção'.")
    from src.core.db_operations.config_crud import get_ai_for_prospect_queue_only
    current_status = await get_ai_for_prospect_queue_only()
    message = "A IA responde apenas para leads da fila de prospecção." if current_status else "A IA responde para todos os leads (pró-ativos e reativos)."
    logger.debug(f"[API_DASH_AI_QUEUE_ONLY] Status retornado: {current_status}. Mensagem: {message}")
    return GenericResponse(success=True, message=message, data={"enabled": current_status})

@router.post("/dashboard/ai-queue-only", response_model=GenericResponse, tags=["Dashboard"])
async def toggle_ai_queue_only(request_data: ToggleAIQueueOnlyRequest):
    enable = request_data.enable # Acessar o campo 'enable' do modelo
    logger.info(f"[API_DASH_AI_QUEUE_ONLY] Recebida requisição para definir 'AI para leads da fila de prospecção' para: {enable}.")
    from src.core.db_operations.config_crud import set_ai_for_prospect_queue_only
    try:
        success = await set_ai_for_prospect_queue_only(enable)
        if success:
            message = "Configuração salva. A IA responderá apenas para leads da fila de prospecção." if enable else "Configuração salva. A IA responderá para todos os leads (pró-ativos e reativos)."
            logger.info(f"[API_DASH_AI_QUEUE_ONLY] Configuração atualizada com sucesso para {enable}.")
            return GenericResponse(success=True, message=message, data={"enabled": enable})
        else:
            logger.error(f"[API_DASH_AI_QUEUE_ONLY] Falha ao salvar configuração 'AI para leads da fila de prospecção'.")
            raise HTTPException(status_code=500, detail="Falha ao salvar configuração.")
    except Exception as e:
        logger.error(f"[API_DASH_AI_QUEUE_ONLY] Erro ao processar requisição de toggle: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno: {e}")


@router.get("/dashboard/stats", response_model=DashboardStatsResponse, tags=["Dashboard"])
async def get_dashboard_stats_endpoint(
    initiator_filter: Optional[ConversationInitiator] = Query(None, alias="initiator_filter", description="Filter stats by conversation initiator ('user' or 'llm_agent', or omit for all).")
):
    logger.info(f"[API_DASH_STATS] Buscando estatísticas do dashboard para iniciador: {initiator_filter}...")
    try:
        # Se o filtro for 'all' ou None, buscamos totais e também por iniciador específico
        # Se o filtro for 'user' ou 'llm_agent', buscamos apenas para esse iniciador

        # Métricas que sempre usam o filtro principal (ou None para todos)
        messages_sent_fut = prospect_manager.get_messages_sent_count(initiator=initiator_filter if initiator_filter != ConversationInitiator.ALL else None)
        # get_total_token_usage é importado diretamente de database, mas deveria ser chamado via prospect_manager se o filtro for aplicado consistentemente
        # Por ora, vamos assumir que prospect_manager.get_total_token_usage existe e aceita initiator
        # Se não, esta chamada precisa ser ajustada ou a função em prospect_manager criada/atualizada.
        # Para manter a consistência com o projeto antigo, vamos assumir que prospect_manager tem uma função get_total_token_usage
        # que internamente chama a de database.py (que já foi atualizada para aceitar initiator).
        # No novo prospect.py, get_total_token_usage é importado de prospect_crud, que foi atualizado.
        token_usage_fut = prospect_manager.get_total_token_usage(initiator=initiator_filter if initiator_filter != ConversationInitiator.ALL else None)

        # Contagens de prospectos
        # Para a visualização 'Todos' (initiator_filter is None ou ALL), os KPIs principais devem refletir o total geral.
        # Para filtros específicos ('user' ou 'llm_agent'), eles refletem esse filtro.
        main_filter_for_kpi = None
        if initiator_filter == ConversationInitiator.ALL or initiator_filter is None:
            main_filter_for_kpi = None # Alterado para None para refletir o total geral
        else:
            main_filter_for_kpi = initiator_filter
            
        total_prospects_main_fut = prospect_manager.get_total_prospected_count(initiator=main_filter_for_kpi)
        active_prospects_main_fut = prospect_manager.get_active_prospect_count(initiator=main_filter_for_kpi)
        
        # Contagens específicas por iniciador para preencher os campos detalhados (sempre buscamos estas para o caso 'all')
        total_prospects_user_fut = prospect_manager.get_total_prospected_count(initiator=ConversationInitiator.USER)
        active_prospects_user_fut = prospect_manager.get_active_prospect_count(initiator=ConversationInitiator.USER)
        total_prospects_llm_fut = prospect_manager.get_total_prospected_count(initiator=ConversationInitiator.LLM_AGENT)
        active_prospects_llm_fut = prospect_manager.get_active_prospect_count(initiator=ConversationInitiator.LLM_AGENT)

        (messages_sent, token_usage,
         total_prospects_main, active_prospects_main,
         total_prospects_user, active_prospects_user,
         total_prospects_llm, active_prospects_llm) = await asyncio.gather(
            messages_sent_fut, token_usage_fut,
            total_prospects_main_fut, active_prospects_main_fut,
            total_prospects_user_fut, active_prospects_user_fut,
            total_prospects_llm_fut, active_prospects_llm_fut
        )
        
        token_usage_dict = token_usage if isinstance(token_usage, dict) else {}
        
        logger.debug(
            f"[API_DASH_STATS] Estatísticas coletadas (Iniciador Filtro: {initiator_filter}): "
            f"Total Principal={total_prospects_main}, Ativos Principal={active_prospects_main}, Msgs={messages_sent}, Tokens={token_usage_dict}, "
            f"UserInitiated={{Total:{total_prospects_user}, Active:{active_prospects_user}}}, "
            f"LLMInitiated={{Total:{total_prospects_llm}, Active:{active_prospects_llm}}}"
        )
        
        return DashboardStatsResponse(
            total_prospects=total_prospects_main, # Este será o total geral se initiator_filter for None/ALL, ou filtrado caso contrário
            active_prospects=active_prospects_main, # Similar ao total_prospects
            messages_sent=messages_sent, # Já filtrado ou total
            total_prompt_tokens=token_usage_dict.get("prompt_tokens", 0),
            total_completion_tokens=token_usage_dict.get("completion_tokens", 0),
            total_tokens=token_usage_dict.get("total_tokens", 0),
            total_prospects_user_initiated=total_prospects_user,
            active_prospects_user_initiated=active_prospects_user,
            total_prospects_llm_initiated=total_prospects_llm,
            active_prospects_llm_initiated=active_prospects_llm
        )
    except Exception as e:
        logger.error(f"[API_DASH_STATS] Erro ao buscar estatísticas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching dashboard stats.")

@router.get("/dashboard/funnel", response_model=DashboardFunnelResponse, tags=["Dashboard"])
async def get_dashboard_funnel_endpoint(
    initiator: Optional[ConversationInitiator] = Query(None, description="Filter funnel by conversation initiator ('user' or 'llm_agent', or omit for all).")
):
    logger.info(f"[API_DASH_FUNNEL] Buscando dados do funil do dashboard para iniciador: {initiator}...")
    try:
        # Passar o filtro 'initiator' (que pode ser None) para a função subjacente
        funnel_data = await prospect_manager.get_funnel_counts(initiator=initiator if initiator != ConversationInitiator.ALL else None)
        logger.debug(f"[API_DASH_FUNNEL] Dados do funil coletados: {funnel_data}")
        return DashboardFunnelResponse(
            stages=funnel_data.get("stages", []),
            total_in_funnel=funnel_data.get("total_in_funnel", 0)
        )
    except ValidationError as ve:
        logger.error(f"[API_DASH_FUNNEL] Erro de validação Pydantic: {ve}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Validation error in funnel data: {ve}")
    except Exception as e:
        logger.error(f"[API_DASH_FUNNEL] Erro ao buscar dados do funil: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching funnel data.")

@router.post("/dashboard/clear-history", response_model=GenericResponse, tags=["Dashboard"])
async def clear_history_endpoint(background_tasks: BackgroundTasks):
    logger.info("[API_DASH_CLEAR_HISTORY] Recebida requisição para limpar todo o histórico.")
    try:
        # A função clear_all_db_leads_and_conversations foi movida para prospect_manager (main_prospect_logic)
        # e espera instance_id.
        # clear_all_redis_history também está em prospect_manager.
        from src.core.config import settings # Para obter INSTANCE_ID
        
        background_tasks.add_task(prospect_manager.clear_all_redis_history) # Nome correto em prospect_manager
        background_tasks.add_task(prospect_manager.clear_all_db_leads_and_conversations, settings.INSTANCE_ID) # Passando instance_id
        
        logger.info("[API_DASH_CLEAR_HISTORY] Tarefas de limpeza de histórico adicionadas ao background.")
        return GenericResponse(success=True, message="Solicitação de limpeza de histórico recebida. O processo ocorrerá em segundo plano.")
    except Exception as e:
        logger.error(f"[API_DASH_CLEAR_HISTORY] Erro ao iniciar a limpeza de histórico: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao iniciar a limpeza de histórico.")

@router.get("/dashboard/analytics", response_model=DashboardAnalyticsResponse, tags=["Dashboard"])
async def get_dashboard_analytics_endpoint(
    initiator: Optional[ConversationInitiator] = Query(None, description="Filter analytics by conversation initiator ('user' or 'llm_agent', or omit for all).")
):
    logger.info(f"[API_DASH_ANALYTICS] Buscando dados de analytics do funil para iniciador: {initiator}...")
    try:
        analytics_data = await get_funnel_analytics_db(initiator=initiator if initiator != ConversationInitiator.ALL else None)
        logger.debug(f"[API_DASH_ANALYTICS] Dados de analytics coletados: {analytics_data}")
        return DashboardAnalyticsResponse(
            conversion_rates=analytics_data.get("conversion_rates", []),
            avg_time_in_stage=analytics_data.get("avg_time_in_stage", [])
        )
    except ValidationError as ve:
        logger.error(f"[API_DASH_ANALYTICS] Erro de validação Pydantic: {ve}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Validation error in analytics data: {ve}")
    except Exception as e:
        logger.error(f"[API_DASH_ANALYTICS] Erro ao buscar dados de analytics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching funnel analytics data.")

# ✅ FASE 4: Endpoint para métricas de retry do sistema de database
@router.get("/dashboard/db-retry-metrics", response_model=GenericResponse, tags=["Dashboard"])
async def get_db_retry_metrics_endpoint():
    """
    Retorna métricas de retry das operações de banco de dados.
    Útil para monitorar a saúde do sistema e identificar problemas de lock/deadlock.
    """
    logger.info("[API_DASH_DB_RETRY_METRICS] Buscando métricas de retry do banco de dados...")
    try:
        from src.core.db_operations.prospect_crud import get_retry_metrics

        metrics = get_retry_metrics()

        # Calcular estatísticas derivadas
        success_rate = (metrics["total_successes"] / metrics["total_operations"] * 100) if metrics["total_operations"] > 0 else 100.0
        avg_retries = (metrics["total_retries"] / metrics["total_successes"]) if metrics["total_successes"] > 0 else 0.0
        failure_rate = (metrics["total_failures"] / metrics["total_operations"] * 100) if metrics["total_operations"] > 0 else 0.0

        metrics_summary = {
            **metrics,
            "success_rate_percent": round(success_rate, 2),
            "failure_rate_percent": round(failure_rate, 2),
            "avg_retries_per_success": round(avg_retries, 2)
        }

        logger.info(f"[API_DASH_DB_RETRY_METRICS] Métricas coletadas: {metrics_summary}")

        return GenericResponse(
            success=True,
            message="Métricas de retry coletadas com sucesso",
            data=metrics_summary
        )
    except Exception as e:
        logger.error(f"[API_DASH_DB_RETRY_METRICS] Erro ao buscar métricas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar métricas de retry.")
