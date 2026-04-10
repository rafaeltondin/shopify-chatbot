# -*- coding: utf-8 -*-
"""
Appointments API Routes
Endpoints para gerenciamento de agendamentos e confirmações automáticas.
"""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends, status as http_status
import pytz

# Timezone padrão: America/Sao_Paulo (GMT-3)
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

from src.core import security
from src.core.security import User
from src.core.db_operations import appointments_crud
from src.core import appointment_confirmation_scheduler as scheduler
from src.api.routes.appointments_models import (
    CreateAppointmentRequest,
    AppointmentResponse,
    AppointmentListResponse,
    UpdateAppointmentStatusRequest,
    PatientResponseRequest,
    ConfirmationConfigRequest,
    ConfirmationConfigResponse,
    SchedulerStatusResponse,
    AppointmentStatsResponse,
    SendConfirmationRequest,
    GenericMessageResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"],
    dependencies=[Depends(security.get_current_user)]
)


# ============ Agendamentos ============

@router.post("", response_model=GenericMessageResponse)
async def create_appointment(
    request: CreateAppointmentRequest,
    current_user: User = Depends(security.get_current_user)
):
    """Cria um novo agendamento."""
    logger.info(f"[API_APPOINTMENTS] Criando agendamento para {request.prospect_jid}")

    try:
        # Converter string ISO para datetime com timezone de São Paulo
        appointment_dt = datetime.fromisoformat(request.appointment_datetime.replace('Z', '+00:00'))
        if appointment_dt.tzinfo is None:
            appointment_dt = SAO_PAULO_TZ.localize(appointment_dt)
        else:
            appointment_dt = appointment_dt.astimezone(SAO_PAULO_TZ)

        appointment_id = await appointments_crud.create_appointment(
            prospect_jid=request.prospect_jid,
            appointment_datetime=appointment_dt,
            prospect_name=request.prospect_name,
            event_id=request.event_id,
            event_summary=request.event_summary,
            event_description=request.event_description,
            hangout_link=request.hangout_link
        )

        if appointment_id:
            return GenericMessageResponse(
                success=True,
                message=f"Agendamento criado com sucesso",
                data={"appointment_id": appointment_id}
            )
        else:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Falha ao criar agendamento"
            )
    except ValueError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Formato de data inválido: {str(e)}"
        )
    except Exception as e:
        logger.error(f"[API_APPOINTMENTS] Erro ao criar agendamento: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("", response_model=AppointmentListResponse)
async def list_appointments(
    status: Optional[str] = Query(None, description="Filtrar por status"),
    start_date: Optional[str] = Query(None, description="Data inicial (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Data final (YYYY-MM-DD)"),
    prospect_jid: Optional[str] = Query(None, description="Filtrar por JID do prospect"),
    page: int = Query(1, ge=1, description="Página"),
    limit: int = Query(50, ge=1, le=100, description="Itens por página"),
    current_user: User = Depends(security.get_current_user)
):
    """Lista agendamentos com filtros opcionais."""
    logger.info(f"[API_APPOINTMENTS] Listando agendamentos - status={status}, page={page}")

    try:
        # Converter datas com timezone de São Paulo
        start_dt = None
        end_dt = None
        if start_date:
            start_dt = datetime.fromisoformat(start_date)
            if start_dt.tzinfo is None:
                start_dt = SAO_PAULO_TZ.localize(start_dt)
        if end_date:
            end_dt = datetime.fromisoformat(end_date)
            if end_dt.tzinfo is None:
                end_dt = SAO_PAULO_TZ.localize(end_dt)

        offset = (page - 1) * limit

        result = await appointments_crud.get_appointments_list(
            status=status,
            start_date=start_dt,
            end_date=end_dt,
            prospect_jid=prospect_jid,
            limit=limit,
            offset=offset
        )

        return AppointmentListResponse(
            items=result['items'],
            total=result['total'],
            page=page,
            limit=limit
        )
    except Exception as e:
        logger.error(f"[API_APPOINTMENTS] Erro ao listar agendamentos: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/upcoming")
async def get_upcoming_appointments(
    days: int = Query(7, ge=1, le=30, description="Dias à frente"),
    current_user: User = Depends(security.get_current_user)
):
    """Busca agendamentos futuros."""
    logger.info(f"[API_APPOINTMENTS] Buscando agendamentos futuros - dias={days}")

    try:
        appointments = await appointments_crud.get_upcoming_appointments(days_ahead=days)
        return {"items": appointments, "total": len(appointments)}
    except Exception as e:
        logger.error(f"[API_APPOINTMENTS] Erro ao buscar agendamentos futuros: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/stats", response_model=AppointmentStatsResponse)
async def get_appointments_stats(
    current_user: User = Depends(security.get_current_user)
):
    """Retorna estatísticas de agendamentos."""
    logger.info("[API_APPOINTMENTS] Buscando estatísticas de agendamentos")

    try:
        stats = await appointments_crud.get_appointments_stats()
        return AppointmentStatsResponse(**stats)
    except Exception as e:
        logger.error(f"[API_APPOINTMENTS] Erro ao buscar estatísticas: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: int,
    current_user: User = Depends(security.get_current_user)
):
    """Busca um agendamento pelo ID."""
    logger.info(f"[API_APPOINTMENTS] Buscando agendamento {appointment_id}")

    appointment = await appointments_crud.get_appointment_by_id(appointment_id)

    if not appointment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado"
        )

    return AppointmentResponse(**appointment)


@router.patch("/{appointment_id}/status", response_model=GenericMessageResponse)
async def update_appointment_status(
    appointment_id: int,
    request: UpdateAppointmentStatusRequest,
    current_user: User = Depends(security.get_current_user)
):
    """Atualiza o status de um agendamento."""
    logger.info(f"[API_APPOINTMENTS] Atualizando status do agendamento {appointment_id} para {request.status}")

    success = await appointments_crud.update_appointment_status(
        appointment_id=appointment_id,
        status=request.status.value
    )

    if success:
        return GenericMessageResponse(
            success=True,
            message=f"Status atualizado para {request.status.value}"
        )
    else:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado ou falha ao atualizar"
        )


@router.post("/{appointment_id}/patient-response", response_model=GenericMessageResponse)
async def record_patient_response(
    appointment_id: int,
    request: PatientResponseRequest,
    current_user: User = Depends(security.get_current_user)
):
    """Registra a resposta do paciente (confirmação/cancelamento)."""
    logger.info(f"[API_APPOINTMENTS] Registrando resposta do paciente para agendamento {appointment_id}")

    success = await appointments_crud.update_patient_response(
        appointment_id=appointment_id,
        confirmed=request.confirmed,
        response_text=request.response_text
    )

    if success:
        status_text = "confirmada" if request.confirmed else "cancelada"
        return GenericMessageResponse(
            success=True,
            message=f"Presença {status_text} registrada com sucesso"
        )
    else:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado ou falha ao registrar resposta"
        )


# ============ Configurações de Confirmação ============

@router.get("/config/confirmations", response_model=ConfirmationConfigResponse)
async def get_confirmation_config(
    current_user: User = Depends(security.get_current_user)
):
    """Busca configurações de confirmação de agendamentos."""
    logger.info("[API_APPOINTMENTS] Buscando configurações de confirmação")

    config = await appointments_crud.get_confirmation_config()
    return ConfirmationConfigResponse(**config)


@router.post("/config/confirmations", response_model=GenericMessageResponse)
async def save_confirmation_config(
    request: ConfirmationConfigRequest,
    current_user: User = Depends(security.get_current_user)
):
    """Salva configurações de confirmação de agendamentos."""
    logger.info("[API_APPOINTMENTS] Salvando configurações de confirmação")

    success = await appointments_crud.save_confirmation_config(request.model_dump())

    if success:
        return GenericMessageResponse(
            success=True,
            message="Configurações de confirmação salvas com sucesso"
        )
    else:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao salvar configurações"
        )


# ============ Scheduler de Confirmações ============

@router.get("/scheduler/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status(
    current_user: User = Depends(security.get_current_user)
):
    """Retorna o status do scheduler de confirmações."""
    logger.info("[API_APPOINTMENTS] Verificando status do scheduler")

    status = scheduler.get_scheduler_status()
    return SchedulerStatusResponse(**status)


@router.post("/scheduler/pause", response_model=GenericMessageResponse)
async def pause_scheduler(
    current_user: User = Depends(security.get_current_user)
):
    """Pausa o scheduler de confirmações."""
    logger.info("[API_APPOINTMENTS] Pausando scheduler de confirmações")

    scheduler.pause_confirmation_scheduler()
    return GenericMessageResponse(
        success=True,
        message="Scheduler de confirmações pausado"
    )


@router.post("/scheduler/resume", response_model=GenericMessageResponse)
async def resume_scheduler(
    current_user: User = Depends(security.get_current_user)
):
    """Retoma o scheduler de confirmações."""
    logger.info("[API_APPOINTMENTS] Retomando scheduler de confirmações")

    scheduler.resume_confirmation_scheduler()
    return GenericMessageResponse(
        success=True,
        message="Scheduler de confirmações retomado"
    )


@router.post("/scheduler/trigger", response_model=GenericMessageResponse)
async def trigger_manual_check(
    current_user: User = Depends(security.get_current_user)
):
    """Dispara verificação manual de confirmações pendentes."""
    logger.info("[API_APPOINTMENTS] Disparando verificação manual")

    result = await scheduler.trigger_manual_check()
    return GenericMessageResponse(
        success=True,
        message=result.get("message", "Verificação concluída")
    )


@router.post("/send-confirmation", response_model=GenericMessageResponse)
async def send_manual_confirmation(
    request: SendConfirmationRequest,
    current_user: User = Depends(security.get_current_user)
):
    """Envia confirmação manualmente para um agendamento específico."""
    logger.info(f"[API_APPOINTMENTS] Enviando confirmação manual - ID={request.appointment_id}, Tipo={request.confirmation_type}")

    if request.confirmation_type not in ['24h', '1h']:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Tipo de confirmação deve ser '24h' ou '1h'"
        )

    # Buscar agendamento
    appointment = await appointments_crud.get_appointment_by_id(request.appointment_id)

    if not appointment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado"
        )

    # Buscar configurações
    config = await appointments_crud.get_confirmation_config()

    # Enviar confirmação
    success = await scheduler.send_confirmation_message(
        appointment,
        request.confirmation_type,
        config
    )

    if success:
        return GenericMessageResponse(
            success=True,
            message=f"Confirmação {request.confirmation_type} enviada com sucesso"
        )
    else:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao enviar confirmação"
        )


logger.info("appointments.py: Rotas de agendamentos carregadas")
