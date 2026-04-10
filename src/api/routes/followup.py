# -*- coding: utf-8 -*-
"""
Endpoints para gerenciar o follow-up automático com cupons de desconto.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.core.followup_scheduler import (
    get_followup_stats,
    get_followup_history,
    start_followup_scheduler,
    stop_followup_scheduler,
)
from src.core.db_operations.config_crud import get_config_value, set_config_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/followup", tags=["Follow-up"])


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class FollowupConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    check_interval_hours: Optional[int] = None
    min_hours_after_contact: Optional[int] = None
    max_hours_after_contact: Optional[int] = None
    no_purchase_days: Optional[int] = None
    discount_percentage: Optional[float] = None
    discount_expiry_days: Optional[int] = None
    discount_minimum_subtotal: Optional[float] = None
    message_template: Optional[str] = None
    schedule_start_time: Optional[str] = None
    schedule_end_time: Optional[str] = None


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@router.get("/stats")
async def get_stats(days: int = Query(30, ge=1, le=365)):
    """Retorna estatísticas de follow-up (envios, conversões, taxa)."""
    try:
        stats = await get_followup_stats(days)
        return stats
    except Exception as e:
        logger.error(f"Erro ao buscar stats de follow-up: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_history(limit: int = Query(50, ge=1, le=200)):
    """Retorna histórico recente de follow-ups enviados."""
    try:
        history = await get_followup_history(limit)
        return {"followups": history, "total": len(history)}
    except Exception as e:
        logger.error(f"Erro ao buscar histórico: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_config():
    """Retorna configuração atual do follow-up."""
    try:
        keys = [
            "followup_enabled", "followup_check_interval_hours",
            "followup_min_hours_after_contact", "followup_max_hours_after_contact",
            "followup_no_purchase_days", "followup_discount_percentage",
            "followup_discount_expiry_days", "followup_discount_minimum_subtotal",
            "followup_message_template", "followup_schedule_start_time",
            "followup_schedule_end_time", "followup_allowed_weekdays",
        ]
        config = {}
        for key in keys:
            val = await get_config_value(key)
            short_key = key.replace("followup_", "")
            config[short_key] = val

        return config

    except Exception as e:
        logger.error(f"Erro ao buscar config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
async def update_config(update: FollowupConfigUpdate):
    """Atualiza configuração do follow-up."""
    try:
        field_map = {
            "enabled": "followup_enabled",
            "check_interval_hours": "followup_check_interval_hours",
            "min_hours_after_contact": "followup_min_hours_after_contact",
            "max_hours_after_contact": "followup_max_hours_after_contact",
            "no_purchase_days": "followup_no_purchase_days",
            "discount_percentage": "followup_discount_percentage",
            "discount_expiry_days": "followup_discount_expiry_days",
            "discount_minimum_subtotal": "followup_discount_minimum_subtotal",
            "message_template": "followup_message_template",
            "schedule_start_time": "followup_schedule_start_time",
            "schedule_end_time": "followup_schedule_end_time",
        }

        updated = []
        for field, db_key in field_map.items():
            value = getattr(update, field, None)
            if value is not None:
                str_value = str(value).lower() if isinstance(value, bool) else str(value)
                await set_config_value(db_key, str_value)
                updated.append(field)

        return {"updated": updated, "count": len(updated)}

    except Exception as e:
        logger.error(f"Erro ao atualizar config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause")
async def pause_followup():
    """Pausa o scheduler de follow-up."""
    try:
        await stop_followup_scheduler()
        await set_config_value("followup_enabled", "false")
        return {"status": "paused"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume")
async def resume_followup():
    """Retoma o scheduler de follow-up."""
    try:
        await set_config_value("followup_enabled", "true")
        start_followup_scheduler()
        return {"status": "running"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


logger.info("followup.py: Módulo de rotas carregado.")
