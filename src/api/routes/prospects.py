# -*- coding: utf-8 -*-
import logging
from typing import Optional, List, Dict
from fastapi import APIRouter, BackgroundTasks, HTTPException, status as http_status, Request
from pydantic import ValidationError

from src.core import prospect as prospect_manager
from src.core import evolution as evolution_api
from src.core.config import settings
from src.utils import formatting
from src.core.db_operations import prospect_crud
from src.core.prospect_management import state as prospect_state_manager

logger = logging.getLogger(__name__)
router = APIRouter()

from src.api.routes.prospects_models import (
    ProspectRequest, ProspectResponse,
    ProspectListItem, ProspectListResponse, ProspectHistoryResponse,
    ConversationHistoryItem, ProspectLLMPauseRequest
)
from src.api.routes.wallet_models import GenericResponse
from src.api.routes.config_models import UpdateProspectFunnelRequest

@router.post("/prospect", response_model=ProspectResponse, tags=["Prospects"])
async def add_prospects_endpoint(
    request: Request,
    background_tasks: BackgroundTasks
):
    logger.info(f"[PROSPECT_ADD_ENDPOINT] Request received. Content-Type: {request.headers.get('content-type')}")

    raw_body_bytes = await request.body()
    decoded_body = raw_body_bytes.decode('utf-8')

    try:
        # Tenta inferir o formato da requisição com base no Content-Type
        if request.headers.get('content-type', '').startswith('text/csv'):
            prospect_request_data = {"numbers_with_names": decoded_body}
        else:
            try:
                # Se não é CSV, tenta interpretar como JSON
                json_data = await request.json()
                prospect_request_data = json_data
            except Exception:
                # Fallback: Se não é CSV e falha ao parsear como JSON, assume que o corpo é texto simples para numbers_with_names
                prospect_request_data = {"numbers_with_names": decoded_body}
        
        # Valida os dados usando o modelo Pydantic ProspectRequest
        validated_request = ProspectRequest(**prospect_request_data)
        logger.info(f"[PROSPECT_ADD_ENDPOINT] Validated request data. Numbers received: {len(validated_request.numbers) if validated_request.numbers else 0}, Numbers with names received content length: {len(validated_request.numbers_with_names) if validated_request.numbers_with_names else 0}")
    
    except ValidationError as e:
        logger.warning(f"[PROSPECT_ADD_ENDPOINT] Validation error processing request body: {e.errors()}")
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Erro de validação na entrada dos prospects: " + str(e.errors())
        )
    except Exception as e:
        logger.error(f"[PROSPECT_ADD_ENDPOINT] Unexpected error during request body processing: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Formato de entrada inválido. Esperado CSV de números ou JSON."
        )

    parsed_leads: List[Dict[str, Optional[str]]] = []
    numbers_for_validation = []
    seen_numbers = set()  # ✅ CORREÇÃO: Rastrear números já processados

    if validated_request.numbers:
        for number in validated_request.numbers:
            cleaned_num = ''.join(filter(str.isdigit, number))
            if not cleaned_num or cleaned_num in seen_numbers:  # ✅ Skip duplicatas
                continue
            seen_numbers.add(cleaned_num)
            numbers_for_validation.append(cleaned_num)
            parsed_leads.append({"number": cleaned_num, "name": None})

    elif validated_request.numbers_with_names:
        for line in validated_request.numbers_with_names.splitlines():
            if not line.strip():
                continue
            parts = line.strip().split(',', 1)
            raw_number = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else None
            cleaned_num = ''.join(filter(str.isdigit, raw_number))
            if not cleaned_num or cleaned_num in seen_numbers:  # ✅ Skip duplicatas
                continue
            seen_numbers.add(cleaned_num)
            numbers_for_validation.append(cleaned_num)
            parsed_leads.append({"number": cleaned_num, "name": name})

    if not parsed_leads:
        logger.warning("[PROSPECT_ADD] No valid phone numbers provided in the request.")
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Nenhum número de telefone válido fornecido"
        )

    logger.info(f"[PROSPECT_ADD] ✅ Parsed {len(parsed_leads)} unique leads (duplicates removed).")

    try:
        # ✅ CORREÇÃO: Remover duplicatas garantindo lista única
        unique_numbers_for_validation = list(dict.fromkeys(numbers_for_validation))
        logger.info(f"[PROSPECT_ADD] Validating {len(unique_numbers_for_validation)} unique numbers with Evolution API...")

        # Verifica os números com a Evolution API
        numbers_on_whatsapp = await evolution_api.check_whatsapp_numbers(unique_numbers_for_validation)
        
        if not numbers_on_whatsapp:
            logger.warning("[PROSPECT_ADD] Evolution API did not confirm any provided numbers have WhatsApp accounts.")
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Nenhum dos números fornecidos possui uma conta no WhatsApp ou a verificação falhou."
            )

        valid_leads = []
        for lead in parsed_leads:
            if lead['number'] in numbers_on_whatsapp:
                valid_leads.append({
                    'number': lead['number'],
                    'name': lead['name'],
                    'jid': formatting.format_number_for_evolution(lead['number'])
                })
        
        if not valid_leads:
            logger.warning("[PROSPECT_ADD] No valid numbers remain after filtering by WhatsApp presence.")
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Nenhum número restante possui conta no WhatsApp após o filtro."
            )

        initial_size = await prospect_manager.get_queue_size()
        submitted_count = len(valid_leads)
        
        if submitted_count > 0:
            background_tasks.add_task(
                prospect_manager.add_jids_to_prospect_queue,
                valid_leads
            )
            logger.info(f"[PROSPECT_ADD] {submitted_count} leads successfully added to the queue.")

        return ProspectResponse(
            message=f"{submitted_count} número(s) válido(s) submetido(s)",
            submitted_count=submitted_count,
            initial_queue_size=initial_size,
            current_queue_size=initial_size + submitted_count
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROSPECT_ADD] Unexpected error during numbers processing: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar e verificar números de WhatsApp."
        )

@router.get("/prospects/{jid}/history", response_model=ProspectHistoryResponse, tags=["Prospects"])
async def get_prospect_history_endpoint(jid: str):
    logger.info(f"[API_PROSPECT_HISTORY] Fetching history for JID: {jid}")
    cleaned_jid = formatting.clean_phone_number(jid)
    if not cleaned_jid:
        logger.warning(f"[API_PROSPECT_HISTORY] Invalid JID '{jid}' after cleaning.")
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Número de prospect inválido fornecido para histórico.")
    
    logger.debug(f"[API_PROSPECT_HISTORY] Cleaned JID for lookup: '{cleaned_jid}'")
    try:
        instance_id = settings.INSTANCE_ID
        history_data = await prospect_manager.get_prospect_conversation_history(cleaned_jid, instance_id=instance_id)
        validated_history = [ConversationHistoryItem(**item) for item in history_data]
        logger.info(f"[API_PROSPECT_HISTORY] History for '{cleaned_jid}' found with {len(validated_history)} entries.")
        return ProspectHistoryResponse(jid=cleaned_jid, history=validated_history)
    except Exception as e:
        logger.error(f"[API_PROSPECT_HISTORY] Error fetching history for {cleaned_jid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error fetching history.")

@router.get("/prospects", response_model=ProspectListResponse, tags=["Prospects"])
async def list_prospects_endpoint(
    status: Optional[str] = None,
    stage: Optional[int] = None,
    jid_search: Optional[str] = None,
    funnel_id: Optional[str] = None,
    limit: int = 15,
    offset: int = 0
):
    logger.info(f"[API_PROSPECTS_LIST] Listing prospects: status='{status}', stage={stage}, jid_search='{jid_search}', funnel_id='{funnel_id}', limit={limit}, offset={offset}")
    try:
        prospects_data, total_count = await prospect_crud.get_prospects_list(
            status=status,
            stage=stage,
            jid_search=jid_search,
            funnel_id=funnel_id,
            limit=limit,
            offset=offset
        )
        
        prospects_list_items = [
            ProspectListItem(
                jid=p['jid'],
                name=p['name'],
                current_stage=p['current_stage'],
                status=p['status'],
                llm_paused=p['llm_paused'],
                last_interaction_at=p['last_interaction_at'],
                created_at=p['created_at'],
                tags=p.get('tags', [])
            )
            for p in prospects_data
        ]
        
        logger.info(f"[{settings.INSTANCE_ID}] [API_PROSPECTS_LIST] {len(prospects_list_items)} prospects returned. Total: {total_count}.")
        return ProspectListResponse(prospects=prospects_list_items, total_count=total_count)
    except Exception as e:
        logger.error(f"[API_PROSPECTS_LIST] Error listing prospects: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error listing prospects.")

@router.get("/prospects/{jid}/profile-picture", tags=["Prospects"])
async def get_prospect_profile_picture_endpoint(jid: str):
    """
    Busca a URL da foto de perfil do WhatsApp de um prospect.
    Retorna a URL direta da foto ou null se não disponível.
    """
    logger.info(f"[API_PROFILE_PICTURE] Fetching profile picture for JID: {jid}")
    cleaned_jid = formatting.clean_phone_number(jid)
    if not cleaned_jid:
        logger.warning(f"[API_PROFILE_PICTURE] Invalid JID '{jid}' after cleaning.")
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Número inválido.")

    try:
        profile_url = await evolution_api.fetch_profile_picture_url(cleaned_jid)
        return {"jid": cleaned_jid, "profile_picture_url": profile_url}
    except Exception as e:
        logger.error(f"[API_PROFILE_PICTURE] Error fetching profile picture for {cleaned_jid}: {e}", exc_info=True)
        return {"jid": cleaned_jid, "profile_picture_url": None}


@router.post("/prospects/{jid}/toggle-llm-pause", response_model=GenericResponse, tags=["Prospects"])
async def toggle_prospect_llm_pause_endpoint(jid: str, request_data: ProspectLLMPauseRequest):
    logger.info(f"[API_TOGGLE_LLM_PAUSE] Request to toggle LLM pause for JID (raw): {jid}, LLM Paused: {request_data.llm_paused}")
    cleaned_jid = formatting.clean_phone_number(jid)
    if not cleaned_jid:
        logger.warning(f"[API_TOGGLE_LLM_PAUSE] Invalid JID '{jid}' after cleaning.")
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Número de prospect inválido fornecido.")

    logger.debug(f"[API_TOGGLE_LLM_PAUSE] Cleaned JID: '{cleaned_jid}', Desired LLM Paused State: {request_data.llm_paused}")
    try:
        instance_id = settings.INSTANCE_ID
        success = await prospect_crud.update_prospect_llm_pause_status_db(
            jid=cleaned_jid,
            llm_paused=request_data.llm_paused,
            instance_id=instance_id
        )
        if success:
            try:
                prospect_state = await prospect_state_manager.get_prospect(cleaned_jid)
                if prospect_state:
                    prospect_state.llm_paused = request_data.llm_paused
                    await prospect_state_manager.save_prospect(prospect_state)
                    logger.info(f"[API_TOGGLE_LLM_PAUSE] Redis state for prospect '{cleaned_jid}' updated with llm_paused: {request_data.llm_paused}.")
                else:
                    logger.info(f"[API_TOGGLE_LLM_PAUSE] Prospect '{cleaned_jid}' not found in Redis. No Redis update needed, will be loaded from DB on next access.")
            except Exception as e_redis:
                logger.error(f"[API_TOGGLE_LLM_PAUSE] Error updating Redis state for prospect '{cleaned_jid}': {e_redis}", exc_info=True)

            message = f"LLM responses for prospect '{cleaned_jid}' are now {'paused' if request_data.llm_paused else 'resumed'}."
            logger.info(f"[API_TOGGLE_LLM_PAUSE] {message}")
            return GenericResponse(success=True, message=message)
        else:
            logger.warning(f"[API_TOGGLE_LLM_PAUSE] Failed to update LLM pause status for prospect '{cleaned_jid}'. Prospect not found or status unchanged.")
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Prospect '{cleaned_jid}' not found or LLM pause status already set to {request_data.llm_paused}.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_TOGGLE_LLM_PAUSE] Error updating LLM pause status for {cleaned_jid}: {e}", exc_info=True)
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error updating LLM pause status.")


@router.patch("/prospects/{jid}/funnel", response_model=GenericResponse, tags=["Prospects"])
async def update_prospect_funnel_endpoint(jid: str, request_data: UpdateProspectFunnelRequest):
    """
    Atualiza o funil de vendas de um prospect específico.

    Quando um prospect muda de funil:
    - Por padrão, ele volta para o estágio 1 do novo funil
    - Opcionalmente, pode-se definir um estágio específico de destino
    """
    logger.info(f"[API_UPDATE_PROSPECT_FUNNEL] Request to update funnel for JID: {jid} to funnel_id: {request_data.funnel_id}")
    cleaned_jid = formatting.clean_phone_number(jid)
    if not cleaned_jid:
        logger.warning(f"[API_UPDATE_PROSPECT_FUNNEL] Invalid JID '{jid}' after cleaning.")
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Número de prospect inválido.")

    try:
        # Verify the funnel exists
        from src.core.db_operations.funnel_crud import get_funnel_by_id
        funnel = await get_funnel_by_id(settings.INSTANCE_ID, request_data.funnel_id)
        if not funnel:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Funil '{request_data.funnel_id}' não encontrado."
            )

        if not funnel.get("is_active"):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Funil '{request_data.funnel_id}' está inativo."
            )

        # Validate target stage if provided
        if not request_data.reset_stage and request_data.target_stage:
            stages = funnel.get("stages", [])
            stage_numbers = [s.get("stage_number") for s in stages]
            if request_data.target_stage not in stage_numbers:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"Estágio {request_data.target_stage} não existe no funil '{request_data.funnel_id}'."
                )

        # Update the prospect's funnel
        success = await prospect_crud.update_prospect_funnel_db(
            jid=cleaned_jid,
            funnel_id=request_data.funnel_id,
            instance_id=settings.INSTANCE_ID,
            reset_stage=request_data.reset_stage,
            target_stage=request_data.target_stage
        )

        if success:
            # Also update Redis state if prospect is cached
            try:
                prospect_state = await prospect_state_manager.get_prospect(cleaned_jid)
                if prospect_state:
                    new_stage = 1 if request_data.reset_stage else (request_data.target_stage or 1)
                    prospect_state.stage = new_stage
                    await prospect_state_manager.save_prospect(prospect_state)
                    logger.info(f"[API_UPDATE_PROSPECT_FUNNEL] Redis state updated for '{cleaned_jid}' to stage {new_stage}")
            except Exception as e_redis:
                logger.error(f"[API_UPDATE_PROSPECT_FUNNEL] Error updating Redis state: {e_redis}", exc_info=True)

            new_stage = 1 if request_data.reset_stage else (request_data.target_stage or 1)
            message = f"Prospect '{cleaned_jid}' movido para funil '{funnel.get('name')}' no estágio {new_stage}."
            logger.info(f"[API_UPDATE_PROSPECT_FUNNEL] {message}")
            return GenericResponse(success=True, message=message)
        else:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Prospect '{cleaned_jid}' não encontrado."
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_UPDATE_PROSPECT_FUNNEL] Error updating funnel for {cleaned_jid}: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao atualizar funil do prospect."
        )


# ==================== DADOS DO PACIENTE PARA CLÍNICAS ====================

@router.get("/prospect/{jid}/patient-data", tags=["Prospects"])
async def get_prospect_patient_data_endpoint(jid: str):
    """
    Busca os dados do paciente (CPF, nome completo, data de nascimento) de um prospect.

    Args:
        jid: Identificador do prospect (WhatsApp JID)

    Returns:
        Dict com cpf, full_name, birth_date e status de completude
    """
    logger.info(f"[API_GET_PATIENT_DATA] Buscando dados do paciente para JID '{jid}'")

    try:
        cleaned_jid = formatting.format_jid(jid) or jid

        # Buscar dados do paciente
        patient_check = await prospect_crud.check_patient_data_complete(cleaned_jid, settings.INSTANCE_ID)

        if patient_check.get('data') is None:
            # Prospect não encontrado
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Prospect '{cleaned_jid}' não encontrado."
            )

        return {
            "success": True,
            "jid": cleaned_jid,
            "is_complete": patient_check.get('is_complete', False),
            "missing_fields": patient_check.get('missing_fields', []),
            "data": patient_check.get('data', {})
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_GET_PATIENT_DATA] Erro ao buscar dados do paciente para '{jid}': {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao buscar dados do paciente."
        )


@router.put("/prospect/{jid}/patient-data", tags=["Prospects"])
async def update_prospect_patient_data_endpoint(jid: str, request: Request):
    """
    Atualiza os dados do paciente (CPF, nome completo, data de nascimento) de um prospect.

    Body (JSON):
        - cpf: CPF do paciente (opcional)
        - full_name: Nome completo do paciente (opcional)
        - birth_date: Data de nascimento (opcional, formato: DD/MM/YYYY ou YYYY-MM-DD)

    Returns:
        Status da atualização
    """
    logger.info(f"[API_UPDATE_PATIENT_DATA] Atualizando dados do paciente para JID '{jid}'")

    try:
        data = await request.json()
        cleaned_jid = formatting.format_jid(jid) or jid

        cpf = data.get('cpf')
        full_name = data.get('full_name')
        birth_date = data.get('birth_date')

        # Validar CPF se fornecido
        if cpf:
            if not prospect_crud.validate_cpf(cpf):
                logger.warning(f"[API_UPDATE_PATIENT_DATA] CPF inválido fornecido para '{cleaned_jid}': {cpf}")
                # Não rejeitamos, apenas logamos o warning - salvaremos mesmo assim

        # Atualizar no banco
        success = await prospect_crud.update_prospect_patient_data(
            jid=cleaned_jid,
            instance_id=settings.INSTANCE_ID,
            cpf=cpf,
            full_name=full_name,
            birth_date=birth_date
        )

        if success:
            # Buscar dados atualizados
            updated_data = await prospect_crud.get_prospect_patient_data(cleaned_jid, settings.INSTANCE_ID)
            return {
                "success": True,
                "message": "Dados do paciente atualizados com sucesso.",
                "jid": cleaned_jid,
                "data": updated_data
            }
        else:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Prospect '{cleaned_jid}' não encontrado ou nenhuma alteração realizada."
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_UPDATE_PATIENT_DATA] Erro ao atualizar dados do paciente para '{jid}': {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao atualizar dados do paciente."
        )


@router.get("/prospect/{jid}/patient-data/validate", tags=["Prospects"])
async def validate_prospect_patient_data_endpoint(jid: str):
    """
    Valida se os dados do paciente estão completos para permitir agendamento.

    Args:
        jid: Identificador do prospect (WhatsApp JID)

    Returns:
        - is_complete: bool - Se todos os dados estão preenchidos
        - missing_fields: list - Campos faltantes
        - can_schedule: bool - Se pode prosseguir com agendamento
    """
    logger.info(f"[API_VALIDATE_PATIENT_DATA] Validando dados do paciente para JID '{jid}'")

    try:
        cleaned_jid = formatting.format_jid(jid) or jid

        patient_check = await prospect_crud.check_patient_data_complete(cleaned_jid, settings.INSTANCE_ID)

        if patient_check.get('data') is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Prospect '{cleaned_jid}' não encontrado."
            )

        is_complete = patient_check.get('is_complete', False)
        missing_fields = patient_check.get('missing_fields', [])

        # Traduzir campos faltantes para português
        field_translations = {
            'cpf': 'CPF',
            'full_name': 'Nome Completo',
            'birth_date': 'Data de Nascimento'
        }
        missing_translated = [field_translations.get(f, f) for f in missing_fields]

        return {
            "success": True,
            "jid": cleaned_jid,
            "is_complete": is_complete,
            "missing_fields": missing_fields,
            "missing_fields_display": missing_translated,
            "can_schedule": is_complete,
            "message": "Dados completos. Pode prosseguir com agendamento." if is_complete else f"Faltam os seguintes dados: {', '.join(missing_translated)}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_VALIDATE_PATIENT_DATA] Erro ao validar dados do paciente para '{jid}': {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao validar dados do paciente."
        )
