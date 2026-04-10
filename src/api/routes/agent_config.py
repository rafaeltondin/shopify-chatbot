# -*- coding: utf-8 -*-
"""
Endpoints para configuração interativa do agente de atendimento.
Usado pelo formulário do dashboard para configurar identidade, conexões,
IA, follow-up e segurança.
"""
import logging
import json
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.db_operations.config_crud import get_config_value, set_config_value
from src.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent-config", tags=["Agent Config"])


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class AgentIdentityConfig(BaseModel):
    agent_name: Optional[str] = None
    store_name: Optional[str] = None
    store_description: Optional[str] = None
    agent_personality: Optional[str] = None


class ShopifyConnectionConfig(BaseModel):
    shopify_store_url: Optional[str] = None
    shopify_access_token: Optional[str] = None


class EvolutionConnectionConfig(BaseModel):
    evolution_api_url: Optional[str] = None
    evolution_api_key: Optional[str] = None
    evolution_instance_name: Optional[str] = None


class LLMConfig(BaseModel):
    llm_model_preference: Optional[str] = None
    llm_temperature: Optional[float] = None
    llm_system_prompt: Optional[str] = None
    product_context: Optional[str] = None


class FollowupConfig(BaseModel):
    followup_enabled: Optional[bool] = None
    followup_min_hours_after_contact: Optional[int] = None
    followup_no_purchase_days: Optional[int] = None
    followup_discount_percentage: Optional[float] = None
    followup_discount_expiry_days: Optional[int] = None
    followup_message_template: Optional[str] = None
    followup_schedule_start_time: Optional[str] = None
    followup_schedule_end_time: Optional[str] = None
    followup_allowed_weekdays: Optional[List[int]] = None


class SecurityConfig(BaseModel):
    require_identity_verification: Optional[bool] = None
    verification_methods: Optional[List[str]] = None  # ["email", "order_number", "name"]


# ─────────────────────────────────────────────
# GET — Buscar configuração completa
# ─────────────────────────────────────────────
@router.get("/all")
async def get_all_config():
    """Retorna toda a configuração do agente em um único request."""
    try:
        config = {}
        keys = [
            # Identidade
            "agent_name", "store_name", "store_description", "agent_personality",
            # Shopify
            "shopify_store_url",
            # Evolution
            "evolution_api_url", "evolution_api_key", "evolution_instance_name",
            # LLM
            "llm_system_prompt", "product_context",
            # Follow-up
            "followup_enabled", "followup_min_hours_after_contact",
            "followup_no_purchase_days", "followup_discount_percentage",
            "followup_discount_expiry_days", "followup_message_template",
            "followup_schedule_start_time", "followup_schedule_end_time",
            "followup_allowed_weekdays",
            # Security
            "require_identity_verification", "verification_methods",
            # Welcome
            "shopify_welcome_message",
        ]

        for key in keys:
            val = await get_config_value(key)
            config[key] = val

        # Adicionar settings de env (read-only, mascarando secrets)
        shopify_token = settings.SHOPIFY_ACCESS_TOKEN or ""
        masked_shopify = f"{shopify_token[:8]}...{shopify_token[-4:]}" if len(shopify_token) > 12 else "Não configurado"

        evo_key = config.get("evolution_api_key") or ""
        masked_evo = f"{evo_key[:8]}...{evo_key[-4:]}" if len(str(evo_key)) > 12 else "Não configurado"

        config["_env"] = {
            "instance_id": settings.INSTANCE_ID,
            "llm_model_preference": settings.LLM_MODEL_PREFERENCE,
            "llm_temperature": settings.LLM_TEMPERATURE,
            "shopify_api_version": settings.SHOPIFY_API_VERSION,
            "shopify_store_url_env": settings.SHOPIFY_STORE_URL or "",
            "shopify_access_token_masked": masked_shopify,
            "shopify_connected": bool(settings.SHOPIFY_STORE_URL and settings.SHOPIFY_ACCESS_TOKEN),
        }
        # Mascarar a API key da Evolution no retorno
        if config.get("evolution_api_key"):
            config["evolution_api_key_masked"] = masked_evo
            config["evolution_api_key"] = masked_evo  # Nunca retornar key real

        return config

    except Exception as e:
        logger.error(f"Erro ao buscar config do agente: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# GET — Buscar seções individuais
# ─────────────────────────────────────────────
@router.get("/identity")
async def get_identity():
    """Retorna configuração de identidade do agente."""
    try:
        return {
            "agent_name": await get_config_value("agent_name") or "Ana",
            "store_name": await get_config_value("store_name") or "",
            "store_description": await get_config_value("store_description") or "",
            "agent_personality": await get_config_value("agent_personality") or "",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/shopify")
async def get_shopify():
    """Retorna configuração da Shopify (dados do env, mascarados)."""
    from src.core.shopify import get_shopify_client
    client = get_shopify_client()

    store_url = settings.SHOPIFY_STORE_URL or ""
    token = settings.SHOPIFY_ACCESS_TOKEN or ""
    masked_token = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else ""

    return {
        "store_url": store_url,
        "shop_url": store_url,
        "access_token": masked_token,
        "api_version": settings.SHOPIFY_API_VERSION,
        "connected": client is not None,
    }


@router.get("/security")
async def get_security():
    """Retorna configuração de segurança."""
    try:
        verification = await get_config_value("require_identity_verification")
        methods = await get_config_value("verification_methods")
        return {
            "require_identity_verification": verification != "false",
            "verification_methods": json.loads(methods) if methods else ["email", "order_number", "name"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PUT — Atualizar seções
# ─────────────────────────────────────────────
@router.put("/identity")
async def update_identity(data: AgentIdentityConfig):
    """Atualiza identidade do agente (nome, loja, personalidade)."""
    return await _save_fields(data.model_dump(exclude_none=True))


@router.put("/shopify")
async def update_shopify(data: ShopifyConnectionConfig):
    """Atualiza conexão Shopify."""
    return await _save_fields(data.model_dump(exclude_none=True))


@router.put("/evolution")
async def update_evolution(data: EvolutionConnectionConfig):
    """Atualiza conexão Evolution API (WhatsApp)."""
    fields = data.model_dump(exclude_none=True)
    # Salvar no formato que o evolution.py espera
    evo_map = {
        "evolution_api_url": "evolution_api_url",
        "evolution_api_key": "evolution_api_key",
        "evolution_instance_name": "evolution_instance_name",
    }
    result = await _save_fields(fields)

    # Limpar cache da Evolution para forçar reconexão
    try:
        from src.core.evolution import clear_evolution_cache
        clear_evolution_cache()
    except Exception:
        pass

    return result


@router.put("/llm")
async def update_llm(data: LLMConfig):
    """Atualiza configuração de IA."""
    return await _save_fields(data.model_dump(exclude_none=True))


@router.put("/followup")
async def update_followup(data: FollowupConfig):
    """Atualiza configuração de follow-up."""
    fields = data.model_dump(exclude_none=True)

    # Converter tipos especiais
    if "followup_enabled" in fields:
        fields["followup_enabled"] = str(fields["followup_enabled"]).lower()
    if "followup_allowed_weekdays" in fields:
        fields["followup_allowed_weekdays"] = json.dumps(fields["followup_allowed_weekdays"])

    return await _save_fields(fields)


@router.put("/security")
async def update_security(data: SecurityConfig):
    """Atualiza configuração de segurança."""
    fields = data.model_dump(exclude_none=True)
    if "require_identity_verification" in fields:
        fields["require_identity_verification"] = str(fields["require_identity_verification"]).lower()
    if "verification_methods" in fields:
        fields["verification_methods"] = json.dumps(fields["verification_methods"])
    return await _save_fields(fields)


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────
async def _save_fields(fields: dict) -> dict:
    """Salva múltiplos campos de configuração."""
    saved = []
    errors = []

    for key, value in fields.items():
        try:
            str_value = str(value) if not isinstance(value, str) else value
            await set_config_value(key, str_value)
            saved.append(key)
        except Exception as e:
            errors.append({"key": key, "error": str(e)})
            logger.error(f"Erro ao salvar config '{key}': {e}")

    return {"saved": saved, "errors": errors, "count": len(saved)}


logger.info("agent_config.py: Rotas de configuração carregadas.")
