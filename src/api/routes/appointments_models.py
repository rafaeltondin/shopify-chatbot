# -*- coding: utf-8 -*-
"""
Appointment Confirmation Models
Modelos Pydantic para API de confirmação de agendamentos.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime
from enum import Enum


class AppointmentStatus(str, Enum):
    """Status possíveis de um agendamento."""
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class CreateAppointmentRequest(BaseModel):
    """Request para criar um novo agendamento."""
    prospect_jid: str = Field(..., description="JID do prospect (número WhatsApp)")
    appointment_datetime: str = Field(..., description="Data e hora do agendamento (ISO 8601)")
    prospect_name: Optional[str] = Field(None, description="Nome do prospect")
    professional_id: Optional[int] = Field(None, description="ID do profissional responsável")
    service_name: Optional[str] = Field(None, description="Nome do serviço/procedimento")
    event_id: Optional[str] = Field(None, description="ID do evento no Google Calendar")
    event_summary: Optional[str] = Field(None, description="Título/resumo do evento")
    event_description: Optional[str] = Field(None, description="Descrição do evento")
    hangout_link: Optional[str] = Field(None, description="Link da videochamada")


class AppointmentResponse(BaseModel):
    """Resposta com dados de um agendamento."""
    id: int
    instance_id: str
    prospect_jid: str
    prospect_name: Optional[str] = None
    professional_id: Optional[int] = None
    service_name: Optional[str] = None
    appointment_datetime: str
    event_id: Optional[str] = None
    event_summary: Optional[str] = None
    event_description: Optional[str] = None
    hangout_link: Optional[str] = None
    confirmation_24h_sent: bool = False
    confirmation_24h_sent_at: Optional[str] = None
    confirmation_1h_sent: bool = False
    confirmation_1h_sent_at: Optional[str] = None
    patient_confirmed: Optional[bool] = None
    patient_response: Optional[str] = None
    status: str = "scheduled"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AppointmentListResponse(BaseModel):
    """Resposta com lista de agendamentos."""
    items: List[AppointmentResponse]
    total: int
    page: int = 1
    limit: int = 50


class UpdateAppointmentStatusRequest(BaseModel):
    """Request para atualizar status de um agendamento."""
    status: AppointmentStatus = Field(..., description="Novo status do agendamento")


class PatientResponseRequest(BaseModel):
    """Request para registrar resposta do paciente."""
    confirmed: bool = Field(..., description="Se o paciente confirmou presença")
    response_text: Optional[str] = Field(None, description="Texto da resposta do paciente")


class ConfirmationConfigRequest(BaseModel):
    """Request para configurações de confirmação."""
    enabled: bool = Field(True, description="Sistema de confirmações habilitado")
    send_24h_before: bool = Field(True, description="Enviar confirmação 24h antes")
    send_1h_before: bool = Field(True, description="Enviar confirmação 1h antes")
    message_24h: Optional[str] = Field(None, description="Mensagem personalizada para 24h")
    message_1h: Optional[str] = Field(None, description="Mensagem personalizada para 1h")


class ConfirmationConfigResponse(BaseModel):
    """Resposta com configurações de confirmação."""
    enabled: bool = True
    send_24h_before: bool = True
    send_1h_before: bool = True
    message_24h: Optional[str] = None
    message_1h: Optional[str] = None


class SchedulerStatusResponse(BaseModel):
    """Resposta com status do scheduler de confirmações."""
    running: bool
    paused: bool
    check_interval_seconds: int


class AppointmentStatsResponse(BaseModel):
    """Resposta com estatísticas de agendamentos."""
    total: int = 0
    by_status: Dict[str, int] = {}
    today: int = 0
    this_week: int = 0
    confirmations_24h_sent: int = 0
    confirmations_1h_sent: int = 0
    confirmation_rate: float = 0.0


class SendConfirmationRequest(BaseModel):
    """Request para enviar confirmação manual."""
    appointment_id: int = Field(..., description="ID do agendamento")
    confirmation_type: str = Field(..., description="Tipo de confirmação: '24h' ou '1h'")


class GenericMessageResponse(BaseModel):
    """Resposta genérica com mensagem."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
