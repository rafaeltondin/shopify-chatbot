# -*- coding: utf-8 -*-
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...core.security import get_current_user
from ...utils.llm_utils import get_metrics, reset_metrics, _circuit_breaker
from ...utils.config_loader import get_dynamic_config, get_config_loader
from ...core.config import settings

router = APIRouter(prefix="/llm", tags=["LLM Monitoring"])
logger = logging.getLogger(__name__)

# --- Modelos de Resposta ---

class LLMMetricsResponse(BaseModel):
    total_requests: int
    successful_requests: int
    failed_requests: int
    success_rate: float
    total_tokens: int
    total_cost: float
    avg_response_time: float
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float
    collected_at: datetime

class CircuitBreakerStatus(BaseModel):
    state: str
    failure_count: int
    last_failure_time: Optional[datetime]
    failure_threshold: int
    timeout_seconds: int

class LLMHealthResponse(BaseModel):
    status: str  # healthy, degraded, unhealthy
    metrics: LLMMetricsResponse
    circuit_breaker: CircuitBreakerStatus
    config_loaded: bool
    config_version: str
    uptime_seconds: int

class ConfigResponse(BaseModel):
    version: str
    environment: str
    cache_enabled: bool
    rate_limiting_enabled: bool
    circuit_breaker_enabled: bool
    streaming_enabled: bool
    monitoring_enabled: bool
    conversation_models: List[str]
    scheduling_models: List[str]
    formatting_models: List[str]

class ConfigUpdateRequest(BaseModel):
    section: str  # 'cache', 'rate_limiting', 'models', etc.
    updates: Dict[str, Any]

# --- Endpoints ---

@router.get("/health", response_model=LLMHealthResponse)
async def get_llm_health(current_user: dict = Depends(get_current_user)):
    """Retorna status de saúde completo do sistema LLM"""
    try:
        metrics = get_metrics()
        config = get_dynamic_config()
        
        # Calcular métricas derivadas
        success_rate = (metrics.successful_requests / metrics.total_requests * 100) if metrics.total_requests > 0 else 0
        cache_hit_rate = (metrics.cache_hits / (metrics.cache_hits + metrics.cache_misses) * 100) if (metrics.cache_hits + metrics.cache_misses) > 0 else 0
        
        # Status de saúde baseado em métricas
        if success_rate >= 95 and _circuit_breaker.state.value == "closed":
            health_status = "healthy"
        elif success_rate >= 85:
            health_status = "degraded" 
        else:
            health_status = "unhealthy"
        
        return LLMHealthResponse(
            status=health_status,
            metrics=LLMMetricsResponse(
                total_requests=metrics.total_requests,
                successful_requests=metrics.successful_requests,
                failed_requests=metrics.failed_requests,
                success_rate=success_rate,
                total_tokens=metrics.total_tokens,
                total_cost=metrics.total_cost,
                avg_response_time=metrics.avg_response_time,
                cache_hits=metrics.cache_hits,
                cache_misses=metrics.cache_misses,
                cache_hit_rate=cache_hit_rate,
                collected_at=datetime.now()
            ),
            circuit_breaker=CircuitBreakerStatus(
                state=_circuit_breaker.state.value,
                failure_count=_circuit_breaker.failure_count,
                last_failure_time=datetime.fromtimestamp(_circuit_breaker.last_failure_time) if _circuit_breaker.last_failure_time else None,
                failure_threshold=_circuit_breaker.failure_threshold,
                timeout_seconds=_circuit_breaker.timeout
            ),
            config_loaded=config is not None,
            config_version=config.version if config else "unknown",
            uptime_seconds=0  # TODO: Implementar uptime tracking
        )
        
    except Exception as e:
        logger.error(f"Erro ao obter health status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter status de saúde: {str(e)}"
        )

@router.get("/metrics", response_model=LLMMetricsResponse)
async def get_llm_metrics(current_user: dict = Depends(get_current_user)):
    """Retorna métricas detalhadas do LLM"""
    try:
        metrics = get_metrics()
        
        success_rate = (metrics.successful_requests / metrics.total_requests * 100) if metrics.total_requests > 0 else 0
        cache_hit_rate = (metrics.cache_hits / (metrics.cache_hits + metrics.cache_misses) * 100) if (metrics.cache_hits + metrics.cache_misses) > 0 else 0
        
        return LLMMetricsResponse(
            total_requests=metrics.total_requests,
            successful_requests=metrics.successful_requests,
            failed_requests=metrics.failed_requests,
            success_rate=success_rate,
            total_tokens=metrics.total_tokens,
            total_cost=metrics.total_cost,
            avg_response_time=metrics.avg_response_time,
            cache_hits=metrics.cache_hits,
            cache_misses=metrics.cache_misses,
            cache_hit_rate=cache_hit_rate,
            collected_at=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Erro ao obter métricas: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter métricas: {str(e)}"
        )

@router.post("/metrics/reset")
async def reset_llm_metrics(current_user: dict = Depends(get_current_user)):
    """Reseta métricas do LLM"""
    try:
        reset_metrics()
        logger.info(f"Métricas resetadas pelo usuário: {current_user.get('sub', 'unknown')}")
        return {"message": "Métricas resetadas com sucesso"}
        
    except Exception as e:
        logger.error(f"Erro ao resetar métricas: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao resetar métricas: {str(e)}"
        )

@router.get("/config", response_model=ConfigResponse)
async def get_llm_config(current_user: dict = Depends(get_current_user)):
    """Retorna configuração atual do LLM"""
    try:
        config = get_dynamic_config()
        
        if not config:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Configuração LLM não carregada"
            )
        
        return ConfigResponse(
            version=config.version,
            environment=config.environment,
            cache_enabled=config.cache_enabled,
            rate_limiting_enabled=config.rate_limiting_enabled,
            circuit_breaker_enabled=config.circuit_breaker_enabled,
            streaming_enabled=config.streaming_enabled,
            monitoring_enabled=config.monitoring_enabled,
            conversation_models=config.conversation_models,
            scheduling_models=config.scheduling_models,
            formatting_models=config.formatting_models
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao obter configuração: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter configuração: {str(e)}"
        )

@router.post("/config/reload")
async def reload_llm_config(current_user: dict = Depends(get_current_user)):
    """Recarrega configuração do LLM"""
    try:
        config_loader = get_config_loader()
        await config_loader.reload_config()
        
        logger.info(f"Configuração recarregada pelo usuário: {current_user.get('sub', 'unknown')}")
        return {"message": "Configuração recarregada com sucesso"}
        
    except Exception as e:
        logger.error(f"Erro ao recarregar configuração: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao recarregar configuração: {str(e)}"
        )

@router.get("/circuit-breaker/status")
async def get_circuit_breaker_status(current_user: dict = Depends(get_current_user)):
    """Retorna status do circuit breaker"""
    try:
        return CircuitBreakerStatus(
            state=_circuit_breaker.state.value,
            failure_count=_circuit_breaker.failure_count,
            last_failure_time=datetime.fromtimestamp(_circuit_breaker.last_failure_time) if _circuit_breaker.last_failure_time else None,
            failure_threshold=_circuit_breaker.failure_threshold,
            timeout_seconds=_circuit_breaker.timeout
        )
        
    except Exception as e:
        logger.error(f"Erro ao obter status do circuit breaker: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter status do circuit breaker: {str(e)}"
        )

@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker(current_user: dict = Depends(get_current_user)):
    """Reseta o circuit breaker forçadamente"""
    try:
        _circuit_breaker.failure_count = 0
        _circuit_breaker.last_failure_time = None
        _circuit_breaker.state = _circuit_breaker.state.CLOSED
        
        logger.info(f"Circuit breaker resetado pelo usuário: {current_user.get('sub', 'unknown')}")
        return {"message": "Circuit breaker resetado com sucesso"}
        
    except Exception as e:
        logger.error(f"Erro ao resetar circuit breaker: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao resetar circuit breaker: {str(e)}"
        )

@router.get("/models/available")
async def get_available_models(current_user: dict = Depends(get_current_user)):
    """Retorna modelos disponíveis por contexto"""
    try:
        config = get_dynamic_config()
        
        if not config:
            # Fallback para configuração estática
            return {
                "conversation": settings.LLM_CONVERSATION_MODELS,
                "scheduling": settings.LLM_SCHEDULING_MODELS,
                "formatting": settings.LLM_FORMATTING_MODELS
            }
        
        return {
            "conversation": config.conversation_models,
            "scheduling": config.scheduling_models,
            "formatting": config.formatting_models
        }
        
    except Exception as e:
        logger.error(f"Erro ao obter modelos disponíveis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter modelos disponíveis: {str(e)}"
        )

@router.get("/status/summary")
async def get_status_summary(current_user: dict = Depends(get_current_user)):
    """Retorna resumo rápido do status"""
    try:
        metrics = get_metrics()
        config = get_dynamic_config()
        
        success_rate = (metrics.successful_requests / metrics.total_requests * 100) if metrics.total_requests > 0 else 0
        
        return {
            "status": "operational" if success_rate >= 95 else "degraded" if success_rate >= 85 else "down",
            "success_rate": round(success_rate, 2),
            "total_requests": metrics.total_requests,
            "total_cost": round(metrics.total_cost, 4),
            "avg_response_time": round(metrics.avg_response_time, 2),
            "circuit_breaker_state": _circuit_breaker.state.value,
            "config_loaded": config is not None,
            "cache_enabled": config.cache_enabled if config else False,
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Erro ao obter resumo de status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter resumo de status: {str(e)}"
        )

logger.info("LLM Monitoring API carregada com endpoints de health, métricas, configuração e circuit breaker")