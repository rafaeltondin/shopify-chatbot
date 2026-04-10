# -*- coding: utf-8 -*-
"""
Professionals API Routes
Endpoints para gerenciamento de profissionais (médicos, dentistas, etc.)
e suas agendas em clínicas multi-profissionais.
"""
import json
import logging
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional, List, Dict

import pytz
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError as GoogleHttpError

from src.core.config import settings
from src.core import security
from src.core.db_operations import professionals_crud

from .professionals_models import (
    CreateProfessionalRequest,
    UpdateProfessionalRequest,
    ProfessionalResponse,
    ProfessionalListResponse,
    CreateScheduleBlockRequest,
    ScheduleBlockResponse,
    CreateServiceRequest,
    ServiceResponse,
    AvailabilityRequest,
    AvailabilityResponse,
    AvailabilitySlot,
    ProfessionalStatsResponse,
    RoomInfo,
    GenericMessageResponse,
    ProfessionalCalendarStatusResponse,
    FreeSlotsRequest,
    FreeSlotsResponse,
    ConnectedProfessionalResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/professionals", tags=["Professionals"])


# ============ CRUD de Profissionais ============

@router.post(
    "",
    response_model=GenericMessageResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Criar novo profissional"
)
async def create_professional(request: CreateProfessionalRequest):
    """Cria um novo profissional na clínica."""
    logger.info(f"[PROFESSIONALS] Criando profissional: {request.name}, instance_id: {settings.INSTANCE_ID}")

    try:
        professional_id = await professionals_crud.create_professional(
            name=request.name,
            specialty=request.specialty,
            registration_number=request.registration_number,
            email=request.email,
            phone=request.phone,
            photo_url=request.photo_url,
            room_name=request.room_name,
            room_number=request.room_number,
            color=request.color,
            bio=request.bio,
            appointment_duration=request.appointment_duration,
            buffer_time=request.buffer_time,
            max_daily_appointments=request.max_daily_appointments,
            availability_schedule=request.availability_schedule,
            google_calendar_id=request.google_calendar_id,
            instance_id=settings.INSTANCE_ID  # IMPORTANTE: Passar instance_id explicitamente
        )

        if professional_id:
            return GenericMessageResponse(
                success=True,
                message=f"Profissional '{request.name}' criado com sucesso",
                data={"id": professional_id}
            )
        else:
            raise HTTPException(status_code=500, detail="Erro ao criar profissional")

    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao criar profissional: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "",
    response_model=ProfessionalListResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Listar profissionais"
)
async def list_professionals(
    specialty: Optional[str] = Query(None, description="Filtrar por especialidade"),
    room_name: Optional[str] = Query(None, description="Filtrar por sala"),
    is_active: Optional[bool] = Query(None, description="Filtrar por status ativo"),
    accepts_new_patients: Optional[bool] = Query(None, description="Filtrar por aceita novos pacientes"),
    limit: int = Query(50, ge=1, le=100, description="Limite de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginação")
):
    """Lista profissionais com filtros opcionais."""
    logger.debug(f"[PROFESSIONALS] Listando profissionais: specialty={specialty}, room={room_name}")

    try:
        result = await professionals_crud.get_professionals_list(
            specialty=specialty,
            room_name=room_name,
            is_active=is_active,
            accepts_new_patients=accepts_new_patients,
            limit=limit,
            offset=offset
        )

        return ProfessionalListResponse(
            items=result['items'],
            total=result['total'],
            page=(offset // limit) + 1 if limit > 0 else 1,
            limit=limit
        )

    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao listar profissionais: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/stats",
    response_model=ProfessionalStatsResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Estatísticas de profissionais"
)
async def get_professionals_stats():
    """Retorna estatísticas dos profissionais."""
    logger.debug("[PROFESSIONALS] Buscando estatísticas de profissionais")

    try:
        stats = await professionals_crud.get_professionals_stats()
        return ProfessionalStatsResponse(**stats)
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao buscar estatísticas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/specialties",
    response_model=list,
    dependencies=[Depends(security.get_current_user)],
    summary="Listar especialidades"
)
async def list_specialties():
    """Lista todas as especialidades cadastradas."""
    logger.debug("[PROFESSIONALS] Listando especialidades")

    try:
        specialties = await professionals_crud.get_all_specialties()
        return specialties
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao listar especialidades: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/rooms",
    response_model=list,
    dependencies=[Depends(security.get_current_user)],
    summary="Listar salas"
)
async def list_rooms():
    """Lista todas as salas cadastradas."""
    logger.debug("[PROFESSIONALS] Listando salas")

    try:
        rooms = await professionals_crud.get_all_rooms()
        return rooms
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao listar salas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{professional_id}",
    response_model=ProfessionalResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Buscar profissional por ID"
)
async def get_professional(professional_id: int):
    """Busca um profissional pelo ID."""
    logger.debug(f"[PROFESSIONALS] Buscando profissional ID: {professional_id}, instance_id: {settings.INSTANCE_ID}")

    try:
        professional = await professionals_crud.get_professional_by_id(
            professional_id,
            instance_id=settings.INSTANCE_ID
        )

        if not professional:
            raise HTTPException(status_code=404, detail="Profissional não encontrado")

        return ProfessionalResponse(**professional)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao buscar profissional: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/{professional_id}",
    response_model=GenericMessageResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Atualizar profissional"
)
async def update_professional(professional_id: int, request: UpdateProfessionalRequest):
    """Atualiza dados de um profissional."""
    logger.info(f"[PROFESSIONALS] Atualizando profissional ID: {professional_id}, instance_id: {settings.INSTANCE_ID}")

    try:
        # Filtrar campos não-nulos
        updates = {k: v for k, v in request.model_dump().items() if v is not None}

        if not updates:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        logger.debug(f"[PROFESSIONALS] Campos para atualizar: {list(updates.keys())}")

        success = await professionals_crud.update_professional(
            professional_id,
            updates,
            instance_id=settings.INSTANCE_ID
        )

        if success:
            return GenericMessageResponse(
                success=True,
                message="Profissional atualizado com sucesso"
            )
        else:
            # Log adicional para debug
            logger.warning(f"[PROFESSIONALS] Profissional {professional_id} não encontrado na instance {settings.INSTANCE_ID}")
            raise HTTPException(status_code=404, detail="Profissional não encontrado")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao atualizar profissional: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{professional_id}",
    response_model=GenericMessageResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Desativar profissional"
)
async def deactivate_professional(professional_id: int):
    """Desativa um profissional (soft delete)."""
    logger.info(f"[PROFESSIONALS] Desativando profissional ID: {professional_id}, instance_id: {settings.INSTANCE_ID}")

    try:
        success = await professionals_crud.delete_professional(
            professional_id,
            instance_id=settings.INSTANCE_ID
        )

        if success:
            return GenericMessageResponse(
                success=True,
                message="Profissional desativado com sucesso"
            )
        else:
            raise HTTPException(status_code=404, detail="Profissional não encontrado")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao desativar profissional: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============ Disponibilidade ============

@router.get(
    "/{professional_id}/availability",
    response_model=AvailabilityResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Buscar disponibilidade"
)
async def get_availability(
    professional_id: int,
    date: str = Query(..., description="Data (YYYY-MM-DD)")
):
    """Retorna os horários disponíveis de um profissional em uma data."""
    logger.debug(f"[PROFESSIONALS] Buscando disponibilidade: professional={professional_id}, date={date}, instance_id={settings.INSTANCE_ID}")

    try:
        # Parse da data
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")

        slots = await professionals_crud.get_professional_availability(
            professional_id,
            target_date,
            instance_id=settings.INSTANCE_ID
        )

        return AvailabilityResponse(
            professional_id=professional_id,
            date=date,
            slots=[AvailabilitySlot(**slot) for slot in slots]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao buscar disponibilidade: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============ Bloqueios de Agenda ============

@router.post(
    "/blocks",
    response_model=GenericMessageResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Criar bloqueio de agenda"
)
async def create_schedule_block(request: CreateScheduleBlockRequest):
    """Cria um bloqueio na agenda de um profissional."""
    logger.info(f"[PROFESSIONALS] Criando bloqueio para profissional ID: {request.professional_id}")

    try:
        # Parse das datas
        try:
            start_dt = datetime.fromisoformat(request.start_datetime.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(request.end_datetime.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data/hora inválido")

        if end_dt <= start_dt:
            raise HTTPException(status_code=400, detail="Data de término deve ser posterior à data de início")

        block_id = await professionals_crud.create_schedule_block(
            professional_id=request.professional_id,
            start_datetime=start_dt,
            end_datetime=end_dt,
            block_type=request.block_type.value,
            title=request.title,
            all_day=request.all_day,
            notes=request.notes
        )

        if block_id:
            return GenericMessageResponse(
                success=True,
                message="Bloqueio de agenda criado com sucesso",
                data={"id": block_id}
            )
        else:
            raise HTTPException(status_code=500, detail="Erro ao criar bloqueio")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao criar bloqueio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{professional_id}/blocks",
    response_model=list,
    dependencies=[Depends(security.get_current_user)],
    summary="Listar bloqueios de agenda"
)
async def list_schedule_blocks(
    professional_id: int,
    start_date: str = Query(..., description="Data inicial (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Data final (YYYY-MM-DD)")
):
    """Lista bloqueios de agenda de um profissional em um período."""
    logger.debug(f"[PROFESSIONALS] Listando bloqueios: professional={professional_id}, instance_id={settings.INSTANCE_ID}")

    try:
        # Parse das datas
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")

        blocks = await professionals_crud.get_schedule_blocks(
            professional_id=professional_id,
            start_date=start_dt,
            end_date=end_dt,
            instance_id=settings.INSTANCE_ID
        )

        # Converter datetime para string
        for block in blocks:
            for key in ['start_datetime', 'end_datetime', 'created_at', 'updated_at']:
                if block.get(key) and isinstance(block[key], datetime):
                    block[key] = block[key].isoformat()

        return blocks

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao listar bloqueios: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/blocks/{block_id}",
    response_model=GenericMessageResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Deletar bloqueio de agenda"
)
async def delete_schedule_block(block_id: int):
    """Deleta um bloqueio de agenda."""
    logger.info(f"[PROFESSIONALS] Deletando bloqueio ID: {block_id}")

    try:
        success = await professionals_crud.delete_schedule_block(block_id)

        if success:
            return GenericMessageResponse(
                success=True,
                message="Bloqueio deletado com sucesso"
            )
        else:
            raise HTTPException(status_code=404, detail="Bloqueio não encontrado")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao deletar bloqueio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============ Serviços ============

@router.post(
    "/services",
    response_model=GenericMessageResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Criar serviço"
)
async def create_service(request: CreateServiceRequest):
    """Cria um novo serviço para um profissional."""
    logger.info(f"[PROFESSIONALS] Criando serviço '{request.service_name}' para profissional ID: {request.professional_id}")

    try:
        service_id = await professionals_crud.create_service(
            professional_id=request.professional_id,
            service_name=request.service_name,
            description=request.description,
            duration_minutes=request.duration_minutes,
            price=request.price
        )

        if service_id:
            return GenericMessageResponse(
                success=True,
                message=f"Serviço '{request.service_name}' criado com sucesso",
                data={"id": service_id}
            )
        else:
            raise HTTPException(status_code=500, detail="Erro ao criar serviço")

    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao criar serviço: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{professional_id}/services",
    response_model=list,
    dependencies=[Depends(security.get_current_user)],
    summary="Listar serviços"
)
async def list_services(
    professional_id: int,
    active_only: bool = Query(True, description="Apenas serviços ativos")
):
    """Lista serviços de um profissional."""
    logger.debug(f"[PROFESSIONALS] Listando serviços do profissional ID: {professional_id}, instance_id={settings.INSTANCE_ID}")

    try:
        services = await professionals_crud.get_professional_services(
            professional_id=professional_id,
            instance_id=settings.INSTANCE_ID,
            active_only=active_only
        )

        # Converter datetime para string
        for service in services:
            for key in ['created_at', 'updated_at']:
                if service.get(key) and isinstance(service[key], datetime):
                    service[key] = service[key].isoformat()
            # Converter Decimal para float
            if service.get('price'):
                service['price'] = float(service['price'])

        return services

    except Exception as e:
        logger.error(f"[PROFESSIONALS] Erro ao listar serviços: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============ Google Calendar OAuth ============

# Configurações OAuth
CLIENT_SECRETS_FILE = Path(settings.BASE_DIR) / "client_secret.json"
GOOGLE_CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# Router público para OAuth callback (sem autenticação)
auth_professionals_router = APIRouter(prefix="/auth/professionals", tags=["Professional OAuth"])


async def get_professional_google_credentials(professional_id: int) -> Optional[Credentials]:
    """
    Obtém credenciais válidas do Google Calendar para um profissional específico.

    Args:
        professional_id: ID do profissional

    Returns:
        Credentials object se válido, None caso contrário
    """
    logger.info(f"[PROF_GCAL] Obtendo credenciais para profissional {professional_id}")

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        logger.error("[PROF_GCAL] Credenciais OAuth não configuradas")
        return None

    # Buscar tokens do banco
    oauth_data = await professionals_crud.get_professional_oauth(professional_id)
    if not oauth_data:
        logger.warning(f"[PROF_GCAL] Nenhum token encontrado para profissional {professional_id}")
        return None

    token_info = {
        "token": oauth_data.get('access_token'),
        "refresh_token": oauth_data.get('refresh_token'),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "scopes": GOOGLE_CALENDAR_SCOPES,
    }

    if oauth_data.get('token_expiry'):
        token_info["expiry"] = oauth_data['token_expiry']

    try:
        creds = Credentials.from_authorized_user_info(info=token_info)
    except Exception as e:
        logger.error(f"[PROF_GCAL] Erro ao criar Credentials: {e}", exc_info=True)
        return None

    # Verificar se precisa refresh
    needs_refresh = False
    if not creds.token:
        needs_refresh = True
    elif creds.expiry:
        if datetime.utcnow() >= creds.expiry:
            needs_refresh = True
    else:
        needs_refresh = True

    if needs_refresh and creds.refresh_token:
        try:
            logger.info(f"[PROF_GCAL] Fazendo refresh do token para profissional {professional_id}")
            creds.refresh(GoogleAuthRequest())

            # Salvar novos tokens
            await professionals_crud.update_professional_oauth_token(
                professional_id=professional_id,
                access_token=creds.token,
                token_expiry=creds.expiry
            )
            logger.info(f"[PROF_GCAL] Token atualizado com sucesso")

        except Exception as e:
            logger.error(f"[PROF_GCAL] Falha no refresh do token: {e}", exc_info=True)
            return None

    if not creds.valid:
        logger.warning(f"[PROF_GCAL] Credenciais inválidas para profissional {professional_id}")
        return None

    return creds


async def build_professional_calendar_service(professional_id: int):
    """Constrói o serviço do Google Calendar para um profissional."""
    creds = await get_professional_google_credentials(professional_id)
    if not creds:
        return None
    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        logger.error(f"[PROF_GCAL] Erro ao construir serviço: {e}", exc_info=True)
        return None


@router.get(
    "/{professional_id}/calendar/auth",
    summary="Iniciar OAuth do Google Calendar para profissional"
)
async def start_professional_oauth(professional_id: int, request: Request):
    """
    Inicia o fluxo OAuth para conectar o Google Calendar de um profissional.
    Este endpoint não requer autenticação pois apenas redireciona para o Google OAuth.
    A validação é feita verificando se o profissional existe.
    """
    logger.info(f"[PROF_GCAL] Iniciando OAuth para profissional {professional_id}")

    # Verificar se profissional existe
    professional = await professionals_crud.get_professional_by_id(professional_id)
    if not professional:
        raise HTTPException(status_code=404, detail="Profissional não encontrado")

    if not CLIENT_SECRETS_FILE.exists():
        logger.error(f"[PROF_GCAL] Arquivo client_secret.json não encontrado")
        raise HTTPException(status_code=500, detail="Configuração OAuth ausente")

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Credenciais OAuth não configuradas")

    # Usar a rota de callback correta
    redirect_uri = str(request.url_for('professional_oauth_callback'))
    logger.debug(f"[PROF_GCAL] Redirect URI: {redirect_uri}")

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=GOOGLE_CALENDAR_SCOPES,
        redirect_uri=redirect_uri
    )

    # State contém o professional_id para recuperar no callback
    state = f"prof_{professional_id}"

    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=state
    )

    logger.info(f"[PROF_GCAL] Redirecionando para Google OAuth")
    return RedirectResponse(authorization_url)


@auth_professionals_router.get(
    "/calendar/callback",
    summary="Callback OAuth do Google Calendar para profissional"
)
async def professional_oauth_callback(
    request: Request,
    code: str = Query(...),
    state: Optional[str] = Query(None)
):
    """Callback do OAuth - troca code por tokens e salva para o profissional."""
    logger.info(f"[PROF_GCAL_CALLBACK] Callback recebido. State: {state}")

    if not state or not state.startswith("prof_"):
        logger.error("[PROF_GCAL_CALLBACK] State inválido")
        return RedirectResponse("/static/index.html#settings?oauth_status=error&message=invalid_state")

    try:
        professional_id = int(state.replace("prof_", ""))
    except ValueError:
        logger.error(f"[PROF_GCAL_CALLBACK] Professional ID inválido no state: {state}")
        return RedirectResponse("/static/index.html#settings?oauth_status=error&message=invalid_professional_id")

    if not CLIENT_SECRETS_FILE.exists():
        return RedirectResponse("/static/index.html#settings?oauth_status=error&message=oauth_config_missing")

    redirect_uri = str(request.url_for('professional_oauth_callback'))

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=GOOGLE_CALENDAR_SCOPES,
        redirect_uri=redirect_uri
    )

    try:
        logger.info("[PROF_GCAL_CALLBACK] Trocando código por tokens")
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Obter email do usuário
        user_info_service = build('oauth2', 'v2', credentials=credentials, cache_discovery=False)
        user_info = user_info_service.userinfo().get().execute()
        user_email = user_info.get('email')

        # Salvar tokens no banco
        await professionals_crud.save_professional_oauth(
            professional_id=professional_id,
            google_email=user_email,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            token_expiry=credentials.expiry,
            scopes=','.join(credentials.scopes) if credentials.scopes else None
        )

        logger.info(f"[PROF_GCAL_CALLBACK] OAuth salvo para profissional {professional_id}, email: {user_email}")
        return RedirectResponse(f"/static/index.html#settings?oauth_status=success&professional_id={professional_id}")

    except Exception as e:
        logger.error(f"[PROF_GCAL_CALLBACK] Erro: {e}", exc_info=True)
        return RedirectResponse(f"/static/index.html#settings?oauth_status=error&message=auth_failed")


@router.get(
    "/{professional_id}/calendar/status",
    response_model=ProfessionalCalendarStatusResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Status da conexão Google Calendar do profissional"
)
async def get_professional_calendar_status(professional_id: int):
    """Retorna o status da conexão do Google Calendar de um profissional."""
    logger.debug(f"[PROF_GCAL] Verificando status para profissional {professional_id}, instance_id={settings.INSTANCE_ID}")

    try:
        status = await professionals_crud.is_professional_google_connected(
            professional_id,
            instance_id=settings.INSTANCE_ID
        )

        if status.get('is_connected'):
            return ProfessionalCalendarStatusResponse(
                is_connected=True,
                email=status.get('email'),
                calendar_id=status.get('calendar_id'),
                last_updated=status.get('last_updated'),
                message="Google Calendar conectado"
            )
        else:
            return ProfessionalCalendarStatusResponse(
                is_connected=False,
                message="Google Calendar não conectado"
            )

    except Exception as e:
        logger.error(f"[PROF_GCAL] Erro ao verificar status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao verificar status")


@router.post(
    "/{professional_id}/calendar/disconnect",
    response_model=GenericMessageResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Desconectar Google Calendar do profissional"
)
async def disconnect_professional_calendar(professional_id: int):
    """Desconecta o Google Calendar de um profissional."""
    logger.info(f"[PROF_GCAL] Desconectando Google Calendar do profissional {professional_id}, instance_id={settings.INSTANCE_ID}")

    try:
        success = await professionals_crud.delete_professional_oauth(
            professional_id,
            instance_id=settings.INSTANCE_ID
        )

        if success:
            return GenericMessageResponse(
                success=True,
                message="Google Calendar desconectado com sucesso"
            )
        else:
            return GenericMessageResponse(
                success=False,
                message="Profissional não tinha Google Calendar conectado"
            )

    except Exception as e:
        logger.error(f"[PROF_GCAL] Erro ao desconectar: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao desconectar")


@router.get(
    "/calendar/connected",
    response_model=List[ConnectedProfessionalResponse],
    dependencies=[Depends(security.get_current_user)],
    summary="Listar profissionais com Google Calendar conectado"
)
async def list_connected_professionals():
    """Lista todos os profissionais que têm Google Calendar conectado."""
    logger.debug("[PROF_GCAL] Listando profissionais com Google Calendar conectado")

    try:
        connected = await professionals_crud.get_all_connected_professionals()
        return [ConnectedProfessionalResponse(**p) for p in connected]

    except Exception as e:
        logger.error(f"[PROF_GCAL] Erro ao listar conectados: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao listar profissionais conectados")


@router.post(
    "/{professional_id}/free_slots",
    response_model=FreeSlotsResponse,
    dependencies=[Depends(security.get_current_user)],
    summary="Buscar horários livres de um profissional"
)
async def get_professional_free_slots(
    professional_id: int,
    request_data: FreeSlotsRequest
):
    """
    Busca horários livres de um profissional cruzando:
    - availability_schedule (disponibilidade semanal)
    - professional_schedule_blocks (férias, folgas)
    - scheduled_appointments (agendamentos existentes)
    - Google Calendar (eventos ocupados, se conectado)
    """
    logger.info(f"[PROF_FREE_SLOTS] Buscando slots para profissional {professional_id}, instance_id={settings.INSTANCE_ID}")

    # Buscar dados do profissional
    professional = await professionals_crud.get_professional_by_id(
        professional_id,
        instance_id=settings.INSTANCE_ID
    )
    if not professional:
        raise HTTPException(status_code=404, detail="Profissional não encontrado")

    user_timezone = pytz.timezone(request_data.timezone)

    # Calcular datas padrão se não fornecidas
    # IMPORTANTE: Sempre começar no mínimo a partir de amanhã para evitar mostrar horários passados
    now_local = datetime.now(user_timezone)
    tomorrow = now_local.date() + timedelta(days=1)

    if request_data.start_date:
        requested_start = datetime.strptime(request_data.start_date, "%Y-%m-%d").date()
        # Garantir que não começamos no passado nem no dia atual
        if requested_start <= now_local.date():
            start_date = tomorrow
            logger.info(f"[PROF_FREE_SLOTS] start_date solicitado ({requested_start}) é hoje ou passado, ajustando para amanhã: {start_date.isoformat()}")
        else:
            start_date = requested_start
    else:
        start_date = tomorrow

    if request_data.end_date:
        requested_end = datetime.strptime(request_data.end_date, "%Y-%m-%d").date()
        # Garantir que end_date seja pelo menos igual a start_date
        if requested_end < start_date:
            end_date = start_date + timedelta(days=6)
            logger.info(f"[PROF_FREE_SLOTS] end_date solicitado ({requested_end}) é anterior a start_date, ajustando para: {end_date.isoformat()}")
        else:
            end_date = requested_end
    else:
        end_date = start_date + timedelta(days=6)

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="Data de início não pode ser posterior à data de fim")

    # Obter duração do slot
    slot_duration = professional.get('appointment_duration', 30)
    buffer_time = professional.get('buffer_time', 10)

    # Se service_id fornecido, usar duração do serviço
    if request_data.service_id:
        services = await professionals_crud.get_professional_services(
            professional_id,
            instance_id=settings.INSTANCE_ID
        )
        for service in services:
            if service.get('id') == request_data.service_id:
                slot_duration = service.get('duration_minutes', slot_duration)
                break

    total_slot_duration = slot_duration + buffer_time

    logger.info(
        f"[PROF_FREE_SLOTS] Parâmetros: slot_duration={slot_duration}min, "
        f"buffer_time={buffer_time}min, total_interval={total_slot_duration}min, "
        f"período={start_date} a {end_date}"
    )

    # Buscar availability_schedule do profissional
    availability_schedule = professional.get('availability_schedule') or {}

    # Buscar bloqueios (férias, folgas)
    blocks = await professionals_crud.get_schedule_blocks(
        professional_id=professional_id,
        start_date=datetime.combine(start_date, time.min),
        end_date=datetime.combine(end_date, time.max),
        instance_id=settings.INSTANCE_ID
    )

    # Buscar agendamentos existentes
    # TODO: Implementar busca de agendamentos do profissional

    # Buscar eventos do Google Calendar (se conectado)
    google_events = []
    status = await professionals_crud.is_professional_google_connected(
        professional_id,
        instance_id=settings.INSTANCE_ID
    )
    if status.get('is_connected'):
        service = await build_professional_calendar_service(professional_id)
        if service:
            try:
                time_min = user_timezone.localize(datetime.combine(start_date, time(0, 0, 0)))
                time_max = user_timezone.localize(datetime.combine(end_date, time(23, 59, 59)))

                events_result = service.events().list(
                    calendarId='primary',
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                google_events = events_result.get('items', [])
                logger.info(f"[PROF_FREE_SLOTS] {len(google_events)} eventos do Google Calendar")
            except Exception as e:
                logger.warning(f"[PROF_FREE_SLOTS] Erro ao buscar Google Calendar: {e}")

    # Mapear dias da semana para o formato do availability_schedule
    day_mapping = {
        0: 'monday', 1: 'tuesday', 2: 'wednesday', 3: 'thursday',
        4: 'friday', 5: 'saturday', 6: 'sunday'
    }

    free_slots = []
    current_date = start_date

    while current_date <= end_date:
        day_name = day_mapping[current_date.weekday()]
        day_schedule = availability_schedule.get(day_name, [])

        if not day_schedule:
            current_date += timedelta(days=1)
            continue

        # Processar cada intervalo de disponibilidade
        for interval in day_schedule:
            try:
                if isinstance(interval, dict):
                    start_h, start_m = map(int, interval['start'].split(':'))
                    end_h, end_m = map(int, interval['end'].split(':'))
                elif isinstance(interval, str):
                    parts = interval.split('-')
                    start_h, start_m = map(int, parts[0].split(':'))
                    end_h, end_m = map(int, parts[1].split(':'))
                else:
                    continue
            except (ValueError, KeyError, IndexError):
                continue

            interval_start = user_timezone.localize(
                datetime.combine(current_date, time(start_h, start_m))
            )
            interval_end = user_timezone.localize(
                datetime.combine(current_date, time(end_h, end_m))
            )

            # Gerar slots dentro do intervalo
            slot_start = interval_start
            # O slot precisa caber (slot_duration), não precisa do buffer após o último slot
            while slot_start + timedelta(minutes=slot_duration) <= interval_end:
                slot_end = slot_start + timedelta(minutes=slot_duration)
                is_available = True

                # Verificar bloqueios
                for block in blocks:
                    block_start = block.get('start_datetime')
                    block_end = block.get('end_datetime')
                    if isinstance(block_start, str):
                        block_start = datetime.fromisoformat(block_start)
                    if isinstance(block_end, str):
                        block_end = datetime.fromisoformat(block_end)

                    if block_start.tzinfo is None:
                        block_start = user_timezone.localize(block_start)
                    if block_end.tzinfo is None:
                        block_end = user_timezone.localize(block_end)

                    if max(slot_start, block_start) < min(slot_end, block_end):
                        is_available = False
                        break

                # Verificar eventos do Google Calendar
                if is_available:
                    for event in google_events:
                        event_start_str = event['start'].get('dateTime', event['start'].get('date'))
                        event_end_str = event['end'].get('dateTime', event['end'].get('date'))

                        if 'T' in event_start_str:
                            event_start = datetime.fromisoformat(event_start_str)
                            event_end = datetime.fromisoformat(event_end_str)
                        else:
                            event_start = user_timezone.localize(
                                datetime.strptime(event_start_str, "%Y-%m-%d")
                            )
                            event_end = user_timezone.localize(
                                datetime.strptime(event_end_str, "%Y-%m-%d")
                            )

                        if event_start.tzinfo is None:
                            event_start = pytz.utc.localize(event_start)
                        if event_end.tzinfo is None:
                            event_end = pytz.utc.localize(event_end)

                        event_start = event_start.astimezone(user_timezone)
                        event_end = event_end.astimezone(user_timezone)

                        if max(slot_start, event_start) < min(slot_end, event_end):
                            logger.debug(
                                f"[PROF_FREE_SLOTS] Slot {slot_start.strftime('%H:%M')} bloqueado por evento Google: "
                                f"'{event.get('summary', 'Sem título')}' ({event_start.strftime('%H:%M')}-{event_end.strftime('%H:%M')})"
                            )
                            is_available = False
                            break

                if is_available:
                    free_slots.append({
                        "start": slot_start.isoformat(),
                        "end": slot_end.isoformat()
                    })

                slot_start += timedelta(minutes=total_slot_duration)

        current_date += timedelta(days=1)

    # Ordenar slots
    free_slots.sort(key=lambda x: x['start'])

    logger.info(f"[PROF_FREE_SLOTS] {len(free_slots)} slots livres encontrados")

    return FreeSlotsResponse(
        professional_id=professional_id,
        professional_name=professional.get('name', ''),
        slots=free_slots,
        total_slots=len(free_slots)
    )


logger.info("[PROFESSIONALS] Módulo de API de profissionais carregado")
