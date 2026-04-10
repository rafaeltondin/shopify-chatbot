# -*- coding: utf-8 -*-
import asyncio
import hashlib
import json
import logging
import random
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

# Timezone padrão: America/Sao_Paulo (GMT-3)
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status as http_status,
)
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError as GoogleHttpError
from pydantic import ValidationError

from src.core import security
from src.core.config import settings, logger as core_logger
from src.core.database import get_config_value, set_config_value
from src.core.db_operations import prospect_crud
from src.core.security import User
from src.utils.text_utils import _translate_date_parts_to_ptbr
from src.api.routes.calendar_models import (
    AvailabilitySchedule,
    CalendarStatusResponse,
    CancelMeetingRequest,
    FreeBusyRequest,
    ScheduleMeetingRequest,
)
from src.api.routes.wallet_models import GenericResponse

logger = logging.getLogger(__name__)

# Router para as rotas de autenticação do Google Calendar
auth_calendar_router = APIRouter(prefix="/auth/google/calendar", tags=["Google Calendar Auth"])

# Router para as demais rotas da API do Google Calendar (protegidas)
router = APIRouter(prefix="/calendar", tags=["Google Calendar API"], dependencies=[Depends(security.get_current_user)])

# As rotas /auth/google/calendar e /auth/google/calendar/callback devem ser públicas.
# As outras rotas neste router serão protegidas individualmente.

CLIENT_SECRETS_FILE = Path(settings.BASE_DIR) / "client_secret.json"
GOOGLE_CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar', 
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

async def get_google_credentials() -> Optional[Credentials]:
    """
    Obtém credenciais válidas do Google Calendar do banco de dados.
    
    Returns:
        Credentials object se válido, None caso contrário
    """
    logger.info("[GCAL_HELPER] [DEBUG] Iniciando obtenção de credenciais do Google Calendar")
    
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        logger.error(f"[GCAL_HELPER] [DEBUG] Credenciais OAuth não configuradas - CLIENT_ID: {'✓' if settings.GOOGLE_CLIENT_ID else '✗'}, CLIENT_SECRET: {'✓' if settings.GOOGLE_CLIENT_SECRET else '✗'}")
        return None

    logger.info("[GCAL_HELPER] [DEBUG] Buscando tokens no banco de dados")
    access_token = await get_config_value("google_calendar_access_token")
    refresh_token = await get_config_value("google_calendar_refresh_token")
    expiry_str = await get_config_value("google_calendar_token_expiry")
    
    logger.info(f"[GCAL_HELPER] [DEBUG] Tokens encontrados - Access: {'✓' if access_token else '✗'}, Refresh: {'✓' if refresh_token else '✗'}, Expiry: {expiry_str if expiry_str else '✗'}")
    
    if not access_token and not refresh_token:
        logger.warning("[GCAL_HELPER] [DEBUG] Nenhum token encontrado no banco de dados")
        return None

    token_info = {
        "token": access_token,
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "scopes": GOOGLE_CALENDAR_SCOPES,
    }
    
    if expiry_str:
        token_info["expiry"] = expiry_str
        logger.info(f"[GCAL_HELPER] [DEBUG] Data de expiração configurada: {expiry_str}")
    
    try:
        creds = Credentials.from_authorized_user_info(info=token_info)
        logger.info(f"[GCAL_HELPER] [DEBUG] Objeto Credentials criado com sucesso - Token válido: {'✓' if creds.token else '✗'}, Refresh válido: {'✓' if creds.refresh_token else '✗'}")
        
    except Exception as e:
        logger.error(f"[GCAL_HELPER] [DEBUG] ERRO ao criar Credentials: {e}", exc_info=True)
        return None

    # Verificação de expiração com logs detalhados
    needs_refresh = False
    if not creds.token:
        needs_refresh = True
        logger.info("[GCAL_HELPER] [DEBUG] Token de acesso ausente - refresh necessário")
    elif creds.expiry:
        # CORREÇÃO: Garantir que ambos datetimes sejam offset-aware para comparação
        # creds.expiry pode ser offset-naive (sem timezone), então convertemos para UTC
        current_utc = datetime.now(pytz.UTC)
        expiry_aware = creds.expiry
        if expiry_aware.tzinfo is None:
            # Se expiry não tem timezone, assumimos que está em UTC
            expiry_aware = pytz.UTC.localize(expiry_aware)
        logger.info(f"[GCAL_HELPER] [DEBUG] Verificando expiração - Atual: {current_utc}, Expira: {expiry_aware}")
        if current_utc >= expiry_aware:
            needs_refresh = True
            logger.info(f"[GCAL_HELPER] [DEBUG] Token expirado - refresh necessário")
        else:
            time_until_expiry = expiry_aware - current_utc
            logger.info(f"[GCAL_HELPER] [DEBUG] Token ainda válido por {time_until_expiry}")
    elif not creds.expiry:
        needs_refresh = True
        logger.info("[GCAL_HELPER] [DEBUG] Sem data de expiração - refresh necessário por segurança")

    if needs_refresh and creds.refresh_token:
        try:
            logger.info("[GCAL_HELPER] [DEBUG] Iniciando processo de refresh do token...")
            creds.refresh(GoogleAuthRequest())
            logger.info("[GCAL_HELPER] [DEBUG] Token refresh realizado com sucesso")
            
            # Salvar novos tokens
            await set_config_value("google_calendar_access_token", creds.token)
            if creds.refresh_token and creds.refresh_token != refresh_token:
                await set_config_value("google_calendar_refresh_token", creds.refresh_token)
                logger.info("[GCAL_HELPER] [DEBUG] Refresh token atualizado")
            
            await set_config_value("google_calendar_token_expiry", creds.expiry.isoformat() if creds.expiry else None)
            logger.info(f"[GCAL_HELPER] [DEBUG] Nova expiração salva: {creds.expiry.isoformat() if creds.expiry else 'N/A'}")
            
        except Exception as e:
            logger.error(f"[GCAL_HELPER] [DEBUG] FALHA no refresh do token: {e}", exc_info=True)
            return None

    if not creds.valid:
        logger.warning("[GCAL_HELPER] [DEBUG] Credenciais consideradas inválidas pela biblioteca Google Auth")
        return None

    logger.info("[GCAL_HELPER] [DEBUG] Credenciais válidas obtidas com sucesso")
    return creds

async def build_calendar_service():
    """Constrói o serviço do Google Calendar com credenciais válidas."""
    logger.debug("[GCAL_HELPER] Construindo serviço do Google Calendar.")
    creds = await get_google_credentials()
    if not creds:
        logger.error("[GCAL_HELPER] Não foi possível construir o serviço do Calendar: credenciais ausentes ou inválidas.")
        return None
    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False) 
        logger.info("[GCAL_HELPER] Serviço do Google Calendar construído com sucesso.")
        return service
    except Exception as e:
        logger.error(f"[GCAL_HELPER] Erro ao construir serviço do Google Calendar: {e}", exc_info=True)
        return None

async def format_available_slots_for_llm(free_slots: List[Dict[str, str]]) -> str:
    """
    Formata os horários livres para o contexto do LLM de forma organizada.
    
    Args:
        free_slots: Lista de slots com 'start' e 'end' no formato ISO
        
    Returns:
        String formatada para o LLM
    """
    if not free_slots:
        return "Nenhum horário disponível encontrado."
    
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    slots_by_day = {}
    # Usar datetime.date como chave para ordenação cronológica correta dos dias
    slots_by_day_obj = {} 

    for slot in free_slots:
        try:
            start_dt = datetime.fromisoformat(slot['start']).astimezone(sao_paulo_tz)
            # Usar strftime para obter a string do dia formatada, mas a chave de ordenação será o objeto date
            day_date_obj = start_dt.date()
            day_key_str = start_dt.strftime('%A, %d de %B de %Y') 
            time_str = start_dt.strftime('%H:%M')
            
            if day_date_obj not in slots_by_day_obj:
                slots_by_day_obj[day_date_obj] = {'day_key_str': day_key_str, 'times': []}
            slots_by_day_obj[day_date_obj]['times'].append({
                'time': time_str,
                'iso': slot['start']
            })
        except Exception as e:
            logger.warning(f"[GCAL_HELPER] Erro ao processar slot {slot}: {e}")
            continue
    
    formatted_lines = []
    # Iterar sobre as chaves de data ordenadas
    for day_date_key in sorted(slots_by_day_obj.keys()):
        day_info = slots_by_day_obj[day_date_key]
        day_display_str = day_info['day_key_str']
        times = sorted(day_info['times'], key=lambda x: x['time'])
        time_strings = [t['time'] for t in times]
        # Aplicar tradução aqui
        translated_day_display_str = _translate_date_parts_to_ptbr(day_display_str)
        formatted_lines.append(f"• {translated_day_display_str}: {', '.join(time_strings)}")
    
    return '\n'.join(formatted_lines)

@auth_calendar_router.get("/", tags=["Google Calendar Auth"]) # Rota base para /api/auth/google/calendar
async def auth_google_calendar(request: Request):
    logger.info("[GCAL_AUTH_START] Iniciando fluxo de autenticação do Google Calendar.")
    if not CLIENT_SECRETS_FILE.exists():
        logger.error(f"[GCAL_AUTH_START] Arquivo client_secret.json não encontrado em {CLIENT_SECRETS_FILE}.")
        raise HTTPException(status_code=500, detail="Configuração do servidor OAuth ausente.")
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        logger.error("[GCAL_AUTH_START] GOOGLE_CLIENT_ID ou GOOGLE_CLIENT_SECRET não configurados.")
        raise HTTPException(status_code=500, detail="Credenciais OAuth do servidor não configuradas.")

    redirect_uri = str(request.url_for('auth_google_calendar_callback'))
    logger.debug(f"[GCAL_AUTH_START] Redirect URI para o fluxo OAuth: {redirect_uri}")

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=GOOGLE_CALENDAR_SCOPES,
        redirect_uri=redirect_uri
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline', 
        prompt='consent' 
    )
    logger.info(f"[GCAL_AUTH_START] Redirecionando usuário para URL de autorização do Google: {authorization_url}")
    return RedirectResponse(authorization_url)

@auth_calendar_router.get("/callback", tags=["Google Calendar Auth"], response_model=None) # Rota para /api/auth/google/calendar/callback
async def auth_google_calendar_callback(request: Request, code: str = Query(...), state: Optional[str] = Query(None)):
    logger.info(f"[GCAL_AUTH_CALLBACK] Callback do Google Calendar recebido. Code: {'SIM' if code else 'NÃO'}, State: {state}")

    if not CLIENT_SECRETS_FILE.exists():
        logger.error(f"[GCAL_AUTH_CALLBACK] Arquivo client_secret.json não encontrado.")
        raise HTTPException(status_code=500, detail="Configuração do servidor OAuth ausente no callback.")

    redirect_uri = str(request.url_for('auth_google_calendar_callback'))
    logger.debug(f"[GCAL_AUTH_CALLBACK] Redirect URI usado para buscar token: {redirect_uri}")
    
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=GOOGLE_CALENDAR_SCOPES,
        redirect_uri=redirect_uri
    )
    try:
        logger.info("[GCAL_AUTH_CALLBACK] Trocando código de autorização por tokens...")
        flow.fetch_token(code=code)
        credentials = flow.credentials
        logger.info("[GCAL_AUTH_CALLBACK] Tokens obtidos com sucesso.")

        await set_config_value("google_calendar_access_token", credentials.token)
        if credentials.refresh_token:
            await set_config_value("google_calendar_refresh_token", credentials.refresh_token)
        await set_config_value("google_calendar_token_expiry", credentials.expiry.isoformat() if credentials.expiry else None)
        
        user_info_service = build('oauth2', 'v2', credentials=credentials, cache_discovery=False)
        user_info = user_info_service.userinfo().get().execute()
        user_email = user_info.get('email')
        await set_config_value("google_calendar_email", user_email)

        logger.info(f"[GCAL_AUTH_CALLBACK] Credenciais do Google Calendar salvas para: {user_email}.")
        frontend_success_url = "/static/index.html#/google-calendar-config?gcal_status=success"
        logger.info(f"[GCAL_AUTH_CALLBACK] Redirecionando para: {frontend_success_url}")
        return RedirectResponse(frontend_success_url)
    except Exception as e:
        logger.error(f"[GCAL_AUTH_CALLBACK] Erro: {e}", exc_info=True)
        frontend_error_url = f"/static/index.html#/google-calendar-config?gcal_status=error&message=auth_failed"
        return RedirectResponse(frontend_error_url)

# Modelos AvailabilitySchedule e CalendarStatusResponse movidos para src/api/models.py

@router.get("/status", response_model=CalendarStatusResponse) # Dependência já está no router principal
async def get_calendar_connection_status(current_user: User = Depends(security.get_current_user)):
    logger.info(f"[GCAL_API_STATUS] Verificando status da conexão com Google Calendar para usuário {current_user.username}.")
    try:
        creds = await get_google_credentials()
        email = await get_config_value("google_calendar_email")
        
        is_email_valid = isinstance(email, str) and email.strip() != ""
        are_creds_valid = creds is not None

        if are_creds_valid and is_email_valid:
            logger.info(f"[GCAL_API_STATUS] Conectado ao Google Calendar como: {email}")
            return CalendarStatusResponse(is_connected=True, email=email, message="Conectado ao Google Calendar.")
        else:
            log_message = "[GCAL_API_STATUS] Não conectado. "
            if not are_creds_valid:
                log_message += "Credenciais inválidas ou ausentes (get_google_credentials retornou None). "
            if not is_email_valid:
                log_message += f"Email inválido ou ausente (valor: '{email}')."
            logger.info(log_message.strip())
            return CalendarStatusResponse(is_connected=False, message="Não conectado ao Google Calendar ou credenciais inválidas/expiradas.")
    except HTTPException as http_exc:
        logger.error(f"[GCAL_API_STATUS] HTTPException ao verificar status: {http_exc.detail}", exc_info=True)
        raise http_exc # Re-raise a HTTPException para que o FastAPI a manipule corretamente
    except Exception as e:
        logger.error(f"[GCAL_API_STATUS] Erro inesperado ao verificar status da conexão: {e}", exc_info=True)
        # Retorna um erro 500 genérico, mas com log detalhado
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro interno ao verificar status da conexão com o Google Calendar.")

@router.post("/disconnect", response_model=GenericResponse) # Dependência já está no router principal
async def disconnect_google_calendar(current_user: User = Depends(security.get_current_user)):
    logger.info(f"[GCAL_API_DISCONNECT] Solicitada desconexão do Google Calendar por {current_user.username}.")
    await set_config_value("google_calendar_access_token", "")
    await set_config_value("google_calendar_refresh_token", "")
    await set_config_value("google_calendar_token_expiry", "")
    await set_config_value("google_calendar_email", "")
    logger.info("[GCAL_API_DISCONNECT] Tokens e email do Google Calendar limpos.")
    return GenericResponse(success=True, message="Conta do Google Calendar desconectada.")

@router.get("/availability", response_model=AvailabilitySchedule) # Dependência já está no router principal
async def get_calendar_availability_endpoint(current_user: User = Depends(security.get_current_user)): # Adicionada dependência
    logger.info(f"[GCAL_API_AVAIL_GET] Buscando configuração de disponibilidade para {current_user.username}.")
    schedule_data = await get_config_value("google_calendar_availability_schedule")
    if isinstance(schedule_data, dict):
        logger.info(f"[GCAL_API_AVAIL_GET] Disponibilidade encontrada: {schedule_data}")
        logger.info(f"[GCAL_API_AVAIL_GET_DEBUG] Valor de 'include_video_call' em schedule_data (dict) antes de retornar: {schedule_data.get('include_video_call')} (Tipo: {type(schedule_data.get('include_video_call'))})")
        return AvailabilitySchedule(**schedule_data)
    elif isinstance(schedule_data, str) and schedule_data.strip().startswith('{'):
        try:
            parsed_schedule = json.loads(schedule_data)
            logger.info(f"[GCAL_API_AVAIL_GET] Disponibilidade (string JSON) parseada: {parsed_schedule}")
            logger.info(f"[GCAL_API_AVAIL_GET_DEBUG] Valor de 'include_video_call' em parsed_schedule (JSON) antes de retornar: {parsed_schedule.get('include_video_call')} (Tipo: {type(parsed_schedule.get('include_video_call'))})")
            return AvailabilitySchedule(**parsed_schedule)
        except json.JSONDecodeError:
            logger.error(f"[GCAL_API_AVAIL_GET] Erro ao parsear JSON: {schedule_data}")
            raise HTTPException(status_code=500, detail="Formato inválido para disponibilidade.")
    else:
        logger.warning("[GCAL_API_AVAIL_GET] Disponibilidade não encontrada ou formato inesperado.")
        return AvailabilitySchedule()

# Removida a duplicata de get_calendar_availability_endpoint

@router.post("/availability", response_model=GenericResponse) # Dependência já está no router principal
async def set_calendar_availability_endpoint(schedule: AvailabilitySchedule, current_user: User = Depends(security.get_current_user)):
    logger.info(f"[GCAL_API_AVAIL_POST] Usuário {current_user.username} salvando disponibilidade: {schedule.model_dump_json(indent=2)}")
    logger.info(f"[GCAL_API_AVAIL_POST_DEBUG] Valor de 'include_video_call' recebido no payload: {schedule.include_video_call} (Tipo: {type(schedule.include_video_call)})")
    dumped_schedule = schedule.model_dump()
    logger.info(f"[GCAL_API_AVAIL_POST_DEBUG] Valor de 'include_video_call' no model_dump antes de salvar: {dumped_schedule.get('include_video_call')} (Tipo: {type(dumped_schedule.get('include_video_call'))})")
    success = await set_config_value("google_calendar_availability_schedule", dumped_schedule)
    if success:
        logger.info("[GCAL_API_AVAIL_POST] Disponibilidade salva.")
        return GenericResponse(success=True, message="Configuração de disponibilidade salva.")
    else:
        logger.error("[GCAL_API_AVAIL_POST] Falha ao salvar disponibilidade.")
        raise HTTPException(status_code=500, detail="Falha ao salvar disponibilidade.")

# Modelo ScheduleMeetingRequest movido para src/api/models.py

@router.post("/schedule_meeting", response_model=GenericResponse)
async def schedule_gcal_meeting(
    meeting_details: ScheduleMeetingRequest,
    current_user: User = Depends(security.get_current_user)
):
    """
    Agenda uma reunião no Google Calendar.
    """
    username = current_user.username if current_user else "system"
    logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] INICIANDO agendamento para usuário '{username}'")
    logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Dados recebidos: {meeting_details.model_dump_json(indent=2)}")

    try:
        # Log de verificação de credenciais
        logger.info("[GCAL_API_SCHEDULE] [DEBUG] Verificando credenciais do Google Calendar")
        service = await build_calendar_service()
        if not service:
            logger.error("[GCAL_API_SCHEDULE] [DEBUG] FALHA: Serviço Google Calendar indisponível")
            raise HTTPException(status_code=503, detail="Serviço Google Calendar indisponível. Verifique a configuração de autenticação.")

        logger.info("[GCAL_API_SCHEDULE] [DEBUG] Serviço Google Calendar obtido com sucesso")

        # Processar configuração de videochamada
        is_video_call_explicit = getattr(meeting_details, 'isVideoCall', None)
        
        if is_video_call_explicit is not None:
            is_video_call = is_video_call_explicit
            logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Videochamada definida explicitamente: {is_video_call}")
        else:
            logger.info("[GCAL_API_SCHEDULE] [DEBUG] Videochamada não definida, verificando configuração padrão")
            availability_config_raw = await get_config_value("google_calendar_availability_schedule")
            if isinstance(availability_config_raw, dict):
                video_setting = availability_config_raw.get('include_video_call', False)
                is_video_call = video_setting
                logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Usando configuração padrão de videochamada: {is_video_call}")
            else:
                is_video_call = False
                logger.info("[GCAL_API_SCHEDULE] [DEBUG] Configuração de videochamada não encontrada, usando False")

        user_type = getattr(meeting_details, 'meetingUserType', None)
        prospect_jid_from_request = getattr(meeting_details, 'prospect_jid', None)
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Detalhes finais processados: Videochamada={is_video_call}, Tipo de Usuário={user_type}, Prospect JID={prospect_jid_from_request}")

    except Exception as e:
        logger.error(f"[GCAL_API_SCHEDULE] [DEBUG] ERRO inesperado ao processar detalhes iniciais da reunião: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno ao processar detalhes da reunião.")

    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')

    # Processamento de horários
    start_time_str = meeting_details.start_time
    end_time_str = meeting_details.end_time
    logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Horários recebidos - Início: {start_time_str}, Fim: {end_time_str}")

    try:
        start_time_dt = datetime.fromisoformat(start_time_str)
        end_time_dt = datetime.fromisoformat(end_time_str)
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Horários parseados com sucesso")
    except ValueError as ve:
        logger.error(f"[GCAL_API_SCHEDULE] [DEBUG] ERRO no formato de data/hora: {ve}")
        raise HTTPException(status_code=400, detail=f"Formato de data/hora inválido: {ve}")

    # Garantir timezone
    if start_time_dt.tzinfo is None:
        start_time_aware = sao_paulo_tz.localize(start_time_dt)
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Timezone adicionado ao horário de início")
    else:
        start_time_aware = start_time_dt.astimezone(sao_paulo_tz)
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Horário de início convertido para SP")

    if end_time_dt.tzinfo is None:
        end_time_aware = sao_paulo_tz.localize(end_time_dt)
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Timezone adicionado ao horário de fim")
    else:
        end_time_aware = end_time_dt.astimezone(sao_paulo_tz)
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Horário de fim convertido para SP")
    
    logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Horários finais - Início: {start_time_aware}, Fim: {end_time_aware}")

    # Construir evento
    current_description = meeting_details.description or ""
    if user_type:
        current_description += f"\n\nTipo de Usuário para Agendamento: {user_type}"

    event_body = {
        'summary': meeting_details.summary,
        'description': current_description.strip(),
        'start': {'dateTime': start_time_aware.isoformat(), 'timeZone': str(sao_paulo_tz)},
        'end': {'dateTime': end_time_aware.isoformat(), 'timeZone': str(sao_paulo_tz)},
        'attendees': [{'email': email} for email in meeting_details.attendees] if meeting_details.attendees else [],
    }

    if is_video_call:
        request_id_for_conference = meeting_details.request_id or f"req-{hashlib.md5(datetime.now(SAO_PAULO_TZ).isoformat().encode()).hexdigest()}-{random.randint(1000,9999)}"
        event_body['conferenceData'] = {
            'createRequest': {
                'requestId': request_id_for_conference,
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}
            }
        }
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Videochamada configurada com requestId: {request_id_for_conference}")
    
    logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Corpo do evento preparado: {json.dumps(event_body, indent=2)}")

    try:
        logger.info("[GCAL_API_SCHEDULE] [DEBUG] Enviando requisição para Google Calendar API")
        created_event = service.events().insert(calendarId='primary', body=event_body, conferenceDataVersion=1).execute()
        
        event_id = created_event.get('id')
        event_html_link = created_event.get('htmlLink')
        hangout_link = created_event.get('hangoutLink')
        
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Evento criado com SUCESSO - ID: {event_id}")
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Link do evento: {event_html_link}")
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Link da videochamada: {hangout_link}")

        # Atualizar prospect se fornecido
        if prospect_jid_from_request:
            try:
                logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Atualizando status do prospect {prospect_jid_from_request} para 'scheduled'")
                await prospect_crud.update_prospect_status_db(prospect_jid_from_request, "scheduled", instance_id=settings.INSTANCE_ID)
                logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Status do prospect atualizado com sucesso")

                # ========== CORREÇÃO: ATUALIZAR ESTÁGIO DO PROSPECT PARA "AGENDADO" ==========
                # Quando um agendamento é confirmado via API, o prospect deve avançar no funil
                # para o estágio de "Agendado/Fechamento" (padrão: estágio 4)

                STAGE_AGENDADO = 4  # Estágio padrão para "Agendado/Fechamento"

                # Tentar buscar o estágio correto do sales_flow
                try:
                    from src.core.db_operations.config_crud import get_sales_flow_stages
                    sales_flow = await get_sales_flow_stages(instance_id=settings.INSTANCE_ID)

                    # Procurar estágio que contenha "agend" ou "fechamento" no objetivo
                    for stage in sales_flow:
                        objective = stage.get("objective", "").lower()
                        trigger = stage.get("trigger_description", "").lower()

                        if any(keyword in objective or keyword in trigger
                               for keyword in ["agend", "fechamento", "confirmad", "reunião marcada"]):
                            STAGE_AGENDADO = stage.get("stage_number", 4)
                            logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Encontrado estágio de agendamento: {STAGE_AGENDADO}")
                            break
                except Exception as e_flow:
                    logger.warning(f"[GCAL_API_SCHEDULE] [DEBUG] Erro ao buscar sales_flow: {e_flow}")

                # Buscar estágio atual do prospect
                current_stage = await prospect_crud.get_prospect_stage(prospect_jid_from_request, settings.INSTANCE_ID)
                logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Estágio atual do prospect: {current_stage}, Estágio destino: {STAGE_AGENDADO}")

                # Só avançar se não estiver já no estágio de agendado ou superior
                if current_stage is not None and current_stage < STAGE_AGENDADO:
                    logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] 🔄 Atualizando estágio: {current_stage} → {STAGE_AGENDADO}")

                    await prospect_crud.add_or_update_prospect_db(
                        jid=prospect_jid_from_request,
                        instance_id=settings.INSTANCE_ID,
                        current_stage=STAGE_AGENDADO,
                        status='scheduled'
                    )

                    # Verificar se a atualização foi bem-sucedida
                    updated_stage = await prospect_crud.get_prospect_stage(prospect_jid_from_request, settings.INSTANCE_ID)

                    if updated_stage == STAGE_AGENDADO:
                        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] ✅ Estágio atualizado com sucesso: {current_stage} → {STAGE_AGENDADO}")
                    else:
                        logger.error(f"[GCAL_API_SCHEDULE] [DEBUG] ❌ Falha ao atualizar estágio. Esperado: {STAGE_AGENDADO}, Atual: {updated_stage}")
                else:
                    logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] ℹ️ Prospect já está no estágio {current_stage}. Nenhuma transição necessária.")

                # ========== FIM DA CORREÇÃO ==========

            except Exception as e_db_update:
                logger.error(f"[GCAL_API_SCHEDULE] [DEBUG] ERRO ao atualizar status/estágio do prospect: {e_db_update}", exc_info=True)

        response_data = {
            "event_id": event_id, 
            "html_link": event_html_link,
            "hangout_link": hangout_link
        }
        
        logger.info(f"[GCAL_API_SCHEDULE] [DEBUG] Retornando resposta de sucesso")
        return GenericResponse(success=True, message=f"Reunião agendada com sucesso. ID: {event_id}", data=response_data)
        
    except GoogleHttpError as e:
        error_content = json.loads(e.content.decode())
        error_message = error_content.get("error", {}).get("message", "Erro desconhecido da API do Google.")
        logger.error(f"[GCAL_API_SCHEDULE] [DEBUG] ERRO da Google API: Status {e.resp.status}, Mensagem: {error_message}")
        logger.error(f"[GCAL_API_SCHEDULE] [DEBUG] Detalhes completos do erro: {error_content}")
        raise HTTPException(status_code=e.resp.status, detail=f"Erro da API do Google: {error_message}")
    except Exception as e:
        logger.error(f"[GCAL_API_SCHEDULE] [DEBUG] ERRO INESPERADO no agendamento: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Falha ao criar evento: {str(e)}")

# Modelo FreeBusyRequest movido para src/api/models.py

@router.post("/free_slots", response_model=List[Dict[str, str]]) # Dependência já está no router principal
async def get_free_slots(request_data: FreeBusyRequest, current_user: User = Depends(security.get_current_user)):
    logger.info(f"[GCAL_API_FREESLOTS] Usuário {current_user.username} buscando horários livres: {request_data.model_dump_json()}")
    service = await build_calendar_service()
    if not service:
        logger.error("[GCAL_API_FREESLOTS] Serviço Calendar indisponível.")
        raise HTTPException(status_code=503, detail="Serviço Google Calendar indisponível.")

    try:
        availability_config_raw = await get_config_value("google_calendar_availability_schedule")
        if not isinstance(availability_config_raw, dict):
            logger.warning("[GCAL_API_FREESLOTS] Configuração de disponibilidade não encontrada ou inválida.")
            raise HTTPException(status_code=404, detail="Configuração de disponibilidade do usuário não encontrada.")
        
        user_availability = AvailabilitySchedule(**availability_config_raw)
        logger.debug(f"[GCAL_API_FREESLOTS] Disponibilidade do usuário carregada: {user_availability.model_dump_json(indent=2)}")

        user_timezone = pytz.timezone(request_data.timezone) # Usar o timezone da requisição
        
        # Calcular datas padrão se não fornecidas
        # IMPORTANTE: Sempre começar no mínimo a partir de amanhã para evitar mostrar horários passados
        now_local = datetime.now(user_timezone)
        tomorrow = now_local.date() + timedelta(days=1)

        if request_data.start_date:
            requested_start = datetime.strptime(request_data.start_date, "%Y-%m-%d").date()
            # Garantir que não começamos no passado nem no dia atual
            if requested_start <= now_local.date():
                start_date_obj = tomorrow
                logger.info(f"[GCAL_API_FREESLOTS] start_date solicitado ({requested_start}) é hoje ou passado, ajustando para amanhã: {start_date_obj.isoformat()}")
            else:
                start_date_obj = requested_start
        else:
            start_date_obj = tomorrow
            logger.info(f"[GCAL_API_FREESLOTS] start_date não fornecido, usando padrão: {start_date_obj.isoformat()}")

        if request_data.end_date:
            requested_end = datetime.strptime(request_data.end_date, "%Y-%m-%d").date()
            # Garantir que end_date seja pelo menos igual a start_date
            if requested_end < start_date_obj:
                end_date_obj = start_date_obj + timedelta(days=6)
                logger.info(f"[GCAL_API_FREESLOTS] end_date solicitado ({requested_end}) é anterior a start_date, ajustando para: {end_date_obj.isoformat()}")
            else:
                end_date_obj = requested_end
        else:
            end_date_obj = start_date_obj + timedelta(days=6) # 7 dias a partir do start_date (inclusive)
            logger.info(f"[GCAL_API_FREESLOTS] end_date não fornecido, usando padrão: {end_date_obj.isoformat()}")

        if start_date_obj > end_date_obj:
            logger.warning(f"[GCAL_API_FREESLOTS] Data de início ({start_date_obj}) é posterior à data de fim ({end_date_obj}).")
            raise HTTPException(status_code=400, detail="Data de início não pode ser posterior à data de fim.")

        time_min_gcal = user_timezone.localize(datetime.combine(start_date_obj, time(0, 0, 0)))
        time_max_gcal = user_timezone.localize(datetime.combine(end_date_obj, time(23, 59, 59)))

        logger.info(f"[GCAL_API_FREESLOTS] Buscando eventos no Google Calendar de {time_min_gcal.isoformat()} a {time_max_gcal.isoformat()} (fuso: {request_data.timezone})")
        events_result = service.events().list(
            calendarId='primary', 
            timeMin=time_min_gcal.isoformat(),
            timeMax=time_max_gcal.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        busy_slots_gcal = events_result.get('items', [])
        logger.info(f"[GCAL_API_FREESLOTS] {len(busy_slots_gcal)} eventos encontrados no Google Calendar.")

        free_slots = []
        current_date_iter = start_date_obj # Renomeado para evitar conflito com a variável de data do loop
        
        while current_date_iter <= end_date_obj:
            day_name = current_date_iter.strftime('%A').lower()
            day_availability_str = getattr(user_availability, day_name, [])
            
            if not day_availability_str:
                current_date_iter += timedelta(days=1)
                continue

            for interval_str in day_availability_str:
                try:
                    start_h, start_m = map(int, interval_str.split('-')[0].split(':'))
                    end_h, end_m = map(int, interval_str.split('-')[1].split(':'))
                except ValueError:
                    logger.warning(f"[GCAL_API_FREESLOTS] Formato de intervalo inválido '{interval_str}' para {day_name}. Ignorando.")
                    continue

                slot_start_dt_local = user_timezone.localize(datetime.combine(current_date_iter, time(start_h, start_m)))
                slot_end_dt_local = user_timezone.localize(datetime.combine(current_date_iter, time(end_h, end_m)))
                
                current_potential_start_local = slot_start_dt_local
                while current_potential_start_local < slot_end_dt_local:
                    potential_end_local = current_potential_start_local + timedelta(hours=1)
                    if potential_end_local > slot_end_dt_local:
                        break
                    
                    is_busy = False
                    for busy_event in busy_slots_gcal:
                        busy_start_str = busy_event['start'].get('dateTime', busy_event['start'].get('date'))
                        busy_end_str = busy_event['end'].get('dateTime', busy_event['end'].get('date'))
                        
                        if 'T' not in busy_start_str: # Evento de dia inteiro
                            # Interpreta a data no fuso horário local e define o dia inteiro
                            busy_s_local = user_timezone.localize(datetime.strptime(busy_start_str, "%Y-%m-%d").combine(time.min))
                            busy_e_local = user_timezone.localize(datetime.strptime(busy_end_str, "%Y-%m-%d").combine(time.min))
                        else: # Evento com hora
                            temp_s_dt = datetime.fromisoformat(busy_start_str)
                            temp_e_dt = datetime.fromisoformat(busy_end_str)

                            # Se for naive, assume UTC e converte para o fuso local
                            if temp_s_dt.tzinfo is None: temp_s_dt = pytz.utc.localize(temp_s_dt)
                            if temp_e_dt.tzinfo is None: temp_e_dt = pytz.utc.localize(temp_e_dt)
                            
                            busy_s_local = temp_s_dt.astimezone(user_timezone)
                            busy_e_local = temp_e_dt.astimezone(user_timezone)

                        if max(current_potential_start_local, busy_s_local) < min(potential_end_local, busy_e_local):
                            is_busy = True
                            logger.debug(f"[GCAL_API_FREESLOTS] Slot {current_potential_start_local.isoformat()} - {potential_end_local.isoformat()} está OCUPADO devido a: {busy_event.get('summary', 'Evento sem título')}")
                            break
                    
                    if not is_busy:
                        logger.debug(f"[GCAL_API_FREESLOTS] Slot {current_potential_start_local.isoformat()} - {potential_end_local.isoformat()} está LIVRE.")
                        free_slots.append({
                            "start": current_potential_start_local.isoformat(),
                            "end": potential_end_local.isoformat()
                        })
                    current_potential_start_local = potential_end_local
            current_date_iter += timedelta(days=1)
        
        # Ordenar os slots cronologicamente antes de retornar
        free_slots.sort(key=lambda x: x['start'])
        logger.info(f"[GCAL_API_FREESLOTS] {len(free_slots)} horários livres encontrados e ordenados.")
        return free_slots

    except GoogleHttpError as e:
        error_content = json.loads(e.content.decode())
        error_message = error_content.get("error", {}).get("message", "Erro desconhecido da API do Google.")
        logger.error(f"[GCAL_API_FREESLOTS] Erro Google API: {error_message} (Status: {e.resp.status})", exc_info=True)
        raise HTTPException(status_code=e.resp.status, detail=f"Erro da API do Google ao buscar horários: {error_message}")
    except Exception as e:
        logger.error(f"[GCAL_API_FREESLOTS] Erro ao calcular horários livres: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno ao calcular horários livres: {str(e)}")

@router.post("/cancel_meeting", response_model=GenericResponse) # Dependência já está no router principal
async def cancel_gcal_meeting(cancel_request: CancelMeetingRequest, current_user: User = Depends(security.get_current_user)):
    logger.info(f"[GCAL_API_CANCEL] Usuário {current_user.username} solicitando cancelamento do evento ID: {cancel_request.eventId}")

    service = await build_calendar_service()
    if not service:
        logger.error("[GCAL_API_CANCEL] Serviço Google Calendar indisponível.")
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE, detail="Serviço Google Calendar indisponível.")

    try:
        await asyncio.to_thread(
            service.events().delete(
                calendarId='primary', 
                eventId=cancel_request.eventId
            ).execute
        )
        logger.info(f"[GCAL_API_CANCEL] Evento ID: {cancel_request.eventId} cancelado com sucesso.")
        return GenericResponse(success=True, message=f"Evento ID: {cancel_request.eventId} cancelado com sucesso.")
    except GoogleHttpError as e:
        if e.resp.status == 404:
            logger.warning(f"[GCAL_API_CANCEL] Evento ID: {cancel_request.eventId} não encontrado para cancelamento.")
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Evento ID: {cancel_request.eventId} não encontrado.")
        elif e.resp.status == 410: # Gone - Event already cancelled or deleted
            logger.info(f"[GCAL_API_CANCEL] Evento ID: {cancel_request.eventId} já foi cancelado/removido (HTTP 410).")
            return GenericResponse(success=True, message=f"Evento ID: {cancel_request.eventId} já havia sido cancelado ou removido.")
        else:
            error_content = json.loads(e.content.decode())
            error_message = error_content.get("error", {}).get("message", "Erro desconhecido da API do Google.")
            logger.error(f"[GCAL_API_CANCEL] Erro Google API ao cancelar evento ID: {cancel_request.eventId}: {error_message} (Status: {e.resp.status})", exc_info=True)
            raise HTTPException(status_code=e.resp.status, detail=f"Erro da API do Google ao cancelar evento: {error_message}")
    except Exception as e:
        logger.error(f"[GCAL_API_CANCEL] Erro inesperado ao cancelar evento ID: {cancel_request.eventId}: {e}", exc_info=True)
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Falha ao cancelar evento: {str(e)}")
