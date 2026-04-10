# -*- coding: utf-8 -*-
"""
Endpoints da API — Shopify WhatsApp Chatbot.
Rotas simplificadas para atendimento ao cliente.
"""
import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from src.core.config import settings
from src.core import security
from src.core.evolution import check_api_health, get_api_health_metrics
from src.core.shopify import get_shopify_client
from src.core.websocket_manager import manager

# Import routers
from src.api.routes import auth, webhooks, dashboard, config_endpoints, prospects
from src.api.routes.products import router as products_router
from src.api.routes.orders import router as orders_router
from src.api.routes.shopify_webhooks import router as shopify_webhooks_router
from src.api.routes.llm_monitoring import router as llm_monitoring_router
from src.api.routes.followup import router as followup_router
from src.api.routes.agent_config import router as agent_config_router

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── Rotas públicas ───
router.include_router(auth.router)
router.include_router(webhooks.router)
router.include_router(shopify_webhooks_router)

# ─── Rotas protegidas ───
router.include_router(products_router, dependencies=[Depends(security.get_current_user)])
router.include_router(orders_router, dependencies=[Depends(security.get_current_user)])
router.include_router(prospects.router, dependencies=[Depends(security.get_current_user)])
router.include_router(dashboard.router, dependencies=[Depends(security.get_current_user)])
router.include_router(config_endpoints.router, dependencies=[Depends(security.get_current_user)])
router.include_router(llm_monitoring_router, dependencies=[Depends(security.get_current_user)])
router.include_router(followup_router, dependencies=[Depends(security.get_current_user)])
router.include_router(agent_config_router, dependencies=[Depends(security.get_current_user)])


# ─── Status (público) ───
@router.get("/status", tags=["Status"])
async def get_status():
    """Status geral do chatbot."""
    shopify_client = get_shopify_client()
    return {
        "status": "online" if shopify_client else "degraded",
        "shopify_connected": shopify_client is not None,
        "site_url": settings.SITE_URL if settings.SITE_URL != "https://localhost:8000" else None,
    }


# ─── Health check Evolution API (público) ───
@router.get("/health/evolution", tags=["Health"])
async def get_evolution_health():
    """Verifica conexão com Evolution API (WhatsApp)."""
    try:
        result = await check_api_health()
        metrics = get_api_health_metrics()
        return {
            "healthy": result.get("healthy", False),
            "status": metrics.get("status", "unknown"),
            "connection_state": result.get("connection_state"),
            "response_time_ms": result.get("response_time_ms"),
            "error": result.get("error"),
        }
    except Exception as e:
        return {"healthy": False, "status": "error", "error": str(e)}


# ─── Health check geral (usado pelo dashboard) ───
@router.get("/health/status", tags=["Health"])
async def get_health_status():
    """Status geral do agente para o dashboard."""
    shopify_client = get_shopify_client()
    return {
        "status": "online" if shopify_client else "degraded",
        "shopify_connected": shopify_client is not None,
        "agent_name": "Ana",
    }


# ─── Health check LLM ───
@router.get("/health/llm", tags=["Health"])
async def get_llm_health():
    """Verifica se LLM está configurado."""
    has_key = bool(settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY)
    return {
        "healthy": has_key,
        "status": "connected" if has_key else "no_api_key",
        "model": settings.LLM_MODEL_PREFERENCE,
        "temperature": settings.LLM_TEMPERATURE,
    }


# ─── Health check Shopify (público) ───
@router.get("/health/shopify", tags=["Health"])
async def get_shopify_health():
    """Verifica conexão com Shopify API."""
    client = get_shopify_client()
    if not client:
        return {"healthy": False, "error": "Shopify client não configurado"}

    try:
        # Buscar 1 produto para testar a conexão
        products = await client.get_products(first=1)
        return {
            "healthy": True,
            "store": client.store_domain,
            "api_version": client.api_version,
            "products_accessible": len(products) > 0,
        }
    except Exception as e:
        return {"healthy": False, "store": client.store_domain, "error": str(e)}


# ─── WebSocket ───
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        manager.disconnect(websocket)


logger.info("endpoints.py: Rotas configuradas (modo atendimento e-commerce).")
