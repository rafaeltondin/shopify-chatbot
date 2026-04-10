# -*- coding: utf-8 -*-
"""
API Routes for Tags and Automation Flows

Este módulo expõe os endpoints para:
- Gerenciamento de tags de prospects
- Configuração de definições de tags
- Configuração de fluxos de automação
- Histórico de execuções de automações
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from src.core.config import settings
from src.core import security
from src.core.db_operations import tags_crud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tags", tags=["Tags & Automation"])


# ==================== PYDANTIC MODELS ====================

class TagModel(BaseModel):
    """Modelo para uma tag individual."""
    name: str = Field(..., min_length=1, max_length=100, description="Nome da tag")


class TagListModel(BaseModel):
    """Modelo para lista de tags."""
    tags: List[str] = Field(..., description="Lista de nomes de tags")


class TagDefinitionModel(BaseModel):
    """Modelo para definição completa de uma tag."""
    id: str = Field(..., description="ID único da tag")
    name: str = Field(..., min_length=1, max_length=100, description="Nome da tag")
    color: str = Field(default="#3B82F6", description="Cor da tag em hexadecimal")
    description: Optional[str] = Field(None, max_length=500, description="Descrição da tag")
    auto_triggers: Optional[List[Dict[str, Any]]] = Field(
        default=[],
        description="Gatilhos automáticos para aplicar esta tag"
    )


class TagDefinitionsListModel(BaseModel):
    """Lista de definições de tags."""
    definitions: List[TagDefinitionModel]


class TriggerModel(BaseModel):
    """Modelo para gatilho de automação."""
    type: str = Field(..., description="Tipo de gatilho: tag_added, tag_removed, inactivity, stage_change, keyword_detected, ai_semantic")
    tag: Optional[str] = Field(None, description="Tag que dispara (para tag_added/tag_removed)")
    minutes: Optional[int] = Field(None, description="Minutos de inatividade (para inactivity)")
    from_stage: Optional[int] = Field(None, description="Estágio de origem (para stage_change)")
    to_stage: Optional[int] = Field(None, description="Estágio de destino (para stage_change)")
    keywords: Optional[List[str]] = Field(None, description="Palavras-chave (para keyword_detected)")
    case_sensitive: Optional[bool] = Field(False, description="Case sensitive para keywords")
    intents: Optional[List[str]] = Field(None, description="[DEPRECATED] Usar custom_instruction")
    custom_instruction: Optional[str] = Field(None, description="Instrução customizada para a IA detectar (para ai_semantic)")


class ConditionModel(BaseModel):
    """Modelo para condição de automação."""
    type: str = Field(..., description="Tipo: has_tag, not_has_tag, stage, llm_paused")
    operator: Optional[str] = Field("equals", description="Operador: equals, greater_than, less_than")
    value: Any = Field(..., description="Valor a comparar")


class ActionModel(BaseModel):
    """Modelo para ação de automação."""
    type: str = Field(..., description="Tipo: send_message, send_audio, add_tag, remove_tag, change_stage, change_funnel, pause_llm, resume_llm, notify_team, mark_status, schedule_followup, assign_professional")
    delay_ms: Optional[int] = Field(0, description="Delay em milissegundos antes de executar")
    text: Optional[str] = Field(None, description="Texto da mensagem (para send_message)")
    audio_file: Optional[str] = Field(None, description="Nome do arquivo de áudio (para send_audio)")
    tag: Optional[str] = Field(None, description="Nome da tag (para add_tag/remove_tag)")
    stage: Optional[int] = Field(None, description="Número do estágio (para change_stage)")
    funnel_id: Optional[str] = Field(None, description="ID do funil de destino (para change_funnel)")
    reset_stage: Optional[bool] = Field(True, description="Se deve resetar o estágio para 1 ao mudar de funil (para change_funnel)")
    status: Optional[str] = Field(None, description="Status (para mark_status)")
    message: Optional[str] = Field(None, description="Mensagem (para notify_team)")
    notify_number: Optional[str] = Field(None, description="Número WhatsApp para notificação (para notify_team)")
    delay_minutes: Optional[int] = Field(None, description="Delay em minutos (para schedule_followup)")
    professional: Optional[str] = Field(None, description="Nome ou ID do profissional (para assign_professional)")


class AutomationFlowModel(BaseModel):
    """Modelo completo de um fluxo de automação."""
    id: str = Field(..., description="ID único do fluxo")
    name: str = Field(..., min_length=1, max_length=200, description="Nome do fluxo")
    description: Optional[str] = Field(None, max_length=1000, description="Descrição do fluxo")
    enabled: bool = Field(True, description="Se o fluxo está ativo")
    trigger: TriggerModel = Field(..., description="Gatilho que dispara o fluxo")
    conditions: Optional[List[ConditionModel]] = Field([], description="Condições para executar")
    actions: List[ActionModel] = Field(..., min_items=1, description="Ações a executar")


class AutomationFlowsListModel(BaseModel):
    """Lista de fluxos de automação."""
    flows: List[AutomationFlowModel]


class ProspectTagsResponse(BaseModel):
    """Resposta com tags de um prospect."""
    jid: str
    tags: List[str]


class AllTagsResponse(BaseModel):
    """Resposta com todas as tags em uso."""
    tags: List[Dict[str, Any]]


class AutomationHistoryResponse(BaseModel):
    """Resposta com histórico de automações."""
    executions: List[Dict[str, Any]]


# ==================== TAG ENDPOINTS ====================

@router.get("/prospect/{jid}", response_model=ProspectTagsResponse)
async def get_prospect_tags_endpoint(
    jid: str,
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna as tags de um prospect específico.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_GET_PROSPECT_TAGS] JID: '{jid}'")

    try:
        tags = await tags_crud.get_prospect_tags(jid)

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_GET_PROSPECT_TAGS] Sucesso em {duration:.2f}ms")

        return ProspectTagsResponse(jid=jid, tags=tags)

    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_GET_PROSPECT_TAGS] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prospect/{jid}")
async def add_tag_to_prospect_endpoint(
    jid: str,
    tag_data: TagModel,
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Adiciona uma tag a um prospect.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_ADD_TAG] JID: '{jid}', Tag: '{tag_data.name}'")

    try:
        success = await tags_crud.add_tag_to_prospect(jid, tag_data.name)

        if not success:
            raise HTTPException(status_code=500, detail="Falha ao adicionar tag")

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_ADD_TAG] Sucesso em {duration:.2f}ms")

        return {"message": f"Tag '{tag_data.name}' adicionada com sucesso", "jid": jid, "tag": tag_data.name}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_ADD_TAG] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/prospect/{jid}/{tag}")
async def remove_tag_from_prospect_endpoint(
    jid: str,
    tag: str,
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Remove uma tag de um prospect.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_REMOVE_TAG] JID: '{jid}', Tag: '{tag}'")

    try:
        success = await tags_crud.remove_tag_from_prospect(jid, tag)

        if not success:
            raise HTTPException(status_code=500, detail="Falha ao remover tag")

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_REMOVE_TAG] Sucesso em {duration:.2f}ms")

        return {"message": f"Tag '{tag}' removida com sucesso", "jid": jid, "tag": tag}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_REMOVE_TAG] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/prospect/{jid}")
async def set_prospect_tags_endpoint(
    jid: str,
    tags_data: TagListModel,
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Define todas as tags de um prospect (substitui as existentes).
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_SET_TAGS] JID: '{jid}', Tags: {tags_data.tags}")

    try:
        success = await tags_crud.set_prospect_tags(jid, tags_data.tags)

        if not success:
            raise HTTPException(status_code=500, detail="Falha ao definir tags")

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_SET_TAGS] Sucesso em {duration:.2f}ms")

        return {"message": "Tags atualizadas com sucesso", "jid": jid, "tags": tags_data.tags}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_SET_TAGS] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/all", response_model=AllTagsResponse)
async def get_all_tags_endpoint(
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna todas as tags em uso com contagem de prospects.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_GET_ALL_TAGS] Iniciando busca")

    try:
        tags = await tags_crud.get_all_tags()

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_GET_ALL_TAGS] Sucesso em {duration:.2f}ms - {len(tags)} tags")

        return AllTagsResponse(tags=tags)

    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_GET_ALL_TAGS] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prospects/by-tag/{tag}")
async def get_prospects_by_tag_endpoint(
    tag: str,
    status: Optional[str] = Query(None, description="Filtrar por status"),
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna prospects que possuem uma determinada tag.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_GET_BY_TAG] Tag: '{tag}', Status: '{status}'")

    try:
        prospects = await tags_crud.get_prospects_by_tag(tag, status=status)

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_GET_BY_TAG] Sucesso em {duration:.2f}ms - {len(prospects)} prospects")

        return {"tag": tag, "count": len(prospects), "prospects": prospects}

    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_GET_BY_TAG] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== TAG DEFINITIONS ENDPOINTS ====================

@router.get("/definitions")
async def get_tag_definitions_endpoint(
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna as definições de tags configuradas.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_GET_TAG_DEFINITIONS] Iniciando")

    try:
        definitions = await tags_crud.get_tag_definitions()

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_GET_TAG_DEFINITIONS] Sucesso em {duration:.2f}ms")

        return {"definitions": definitions}

    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_GET_TAG_DEFINITIONS] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/definitions")
async def save_tag_definitions_endpoint(
    data: TagDefinitionsListModel,
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Salva as definições de tags.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_SAVE_TAG_DEFINITIONS] Salvando {len(data.definitions)} definições")

    try:
        definitions_dict = [d.model_dump() for d in data.definitions]
        success = await tags_crud.save_tag_definitions(definitions_dict)

        if not success:
            raise HTTPException(status_code=500, detail="Falha ao salvar definições")

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_SAVE_TAG_DEFINITIONS] Sucesso em {duration:.2f}ms")

        return {"message": "Definições de tags salvas com sucesso", "count": len(data.definitions)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_SAVE_TAG_DEFINITIONS] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AUTOMATION FLOWS ENDPOINTS ====================

@router.get("/automations")
async def get_automation_flows_endpoint(
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna os fluxos de automação configurados.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_GET_AUTOMATIONS] Iniciando")

    try:
        flows = await tags_crud.get_automation_flows()

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_GET_AUTOMATIONS] Sucesso em {duration:.2f}ms - {len(flows)} fluxos")

        return {"flows": flows}

    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_GET_AUTOMATIONS] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/automations")
async def save_automation_flows_endpoint(
    data: AutomationFlowsListModel,
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Salva os fluxos de automação.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_SAVE_AUTOMATIONS] Salvando {len(data.flows)} fluxos")

    try:
        flows_dict = [f.model_dump() for f in data.flows]
        success = await tags_crud.save_automation_flows(flows_dict)

        if not success:
            raise HTTPException(status_code=500, detail="Falha ao salvar fluxos")

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_SAVE_AUTOMATIONS] Sucesso em {duration:.2f}ms")

        return {"message": "Fluxos de automação salvos com sucesso", "count": len(data.flows)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_SAVE_AUTOMATIONS] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AUTOMATION HISTORY ENDPOINTS ====================

@router.get("/automations/history", response_model=AutomationHistoryResponse)
async def get_automation_history_endpoint(
    jid: Optional[str] = Query(None, description="Filtrar por JID"),
    flow_id: Optional[str] = Query(None, description="Filtrar por ID do fluxo"),
    limit: int = Query(50, le=500, description="Limite de resultados"),
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna o histórico de execuções de automações.
    """
    start_time = datetime.now()
    logger.info(f"[{datetime.now().isoformat()}] [API_GET_AUTOMATION_HISTORY] JID: '{jid}', Flow: '{flow_id}', Limit: {limit}")

    try:
        executions = await tags_crud.get_automation_history(jid=jid, flow_id=flow_id, limit=limit)

        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"[{datetime.now().isoformat()}] [API_GET_AUTOMATION_HISTORY] Sucesso em {duration:.2f}ms - {len(executions)} execuções")

        return AutomationHistoryResponse(executions=executions)

    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [API_GET_AUTOMATION_HISTORY] ERRO: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== UTILITY ENDPOINTS ====================

@router.get("/trigger-types")
async def get_trigger_types_endpoint(
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna os tipos de gatilhos disponíveis.
    """
    from src.core.automation_engine import TRIGGER_TYPES
    return {"trigger_types": [{"type": k, "description": v} for k, v in TRIGGER_TYPES.items()]}


@router.get("/action-types")
async def get_action_types_endpoint(
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna os tipos de ações disponíveis.
    """
    from src.core.automation_engine import ACTION_TYPES
    return {"action_types": [{"type": k, "description": v} for k, v in ACTION_TYPES.items()]}


@router.get("/ai-semantic-intents")
async def get_ai_semantic_intents_endpoint(
    current_user: security.User = Depends(security.get_current_user)
):
    """
    Retorna os tipos de intenções semânticas que a IA pode detectar.
    """
    from src.core.automation_engine import AI_SEMANTIC_INTENTS
    return {"intents": [{"type": k, "description": v} for k, v in AI_SEMANTIC_INTENTS.items()]}


logger.info("routes.tags: Module loaded.")
