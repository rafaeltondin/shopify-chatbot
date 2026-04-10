# -*- coding: utf-8 -*-
"""
Professionals Models
Modelos Pydantic para API de gerenciamento de profissionais.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime
from enum import Enum


class BlockType(str, Enum):
    """Tipos de bloqueio de agenda."""
    VACATION = "vacation"
    HOLIDAY = "holiday"
    PERSONAL = "personal"
    TRAINING = "training"
    OTHER = "other"


class TimeSlot(BaseModel):
    """Slot de horário."""
    start: str = Field(..., description="Horário de início (HH:MM)")
    end: str = Field(..., description="Horário de término (HH:MM)")


class WeeklySchedule(BaseModel):
    """Disponibilidade semanal."""
    monday: List[TimeSlot] = []
    tuesday: List[TimeSlot] = []
    wednesday: List[TimeSlot] = []
    thursday: List[TimeSlot] = []
    friday: List[TimeSlot] = []
    saturday: List[TimeSlot] = []
    sunday: List[TimeSlot] = []


class CreateProfessionalRequest(BaseModel):
    """Request para criar um novo profissional."""
    name: str = Field(..., min_length=2, max_length=255, description="Nome completo do profissional")
    specialty: Optional[str] = Field(None, max_length=255, description="Especialidade (ex: Dentista, Nutricionista)")
    registration_number: Optional[str] = Field(None, max_length=100, description="Número de registro (CRM, CRO, etc.)")
    email: Optional[str] = Field(None, max_length=255, description="Email do profissional")
    phone: Optional[str] = Field(None, max_length=50, description="Telefone do profissional")
    photo_url: Optional[str] = Field(None, max_length=500, description="URL da foto")
    room_name: Optional[str] = Field(None, max_length=100, description="Nome da sala/consultório")
    room_number: Optional[str] = Field(None, max_length=50, description="Número da sala")
    color: Optional[str] = Field(None, max_length=7, description="Cor para identificação (hex)")
    bio: Optional[str] = Field(None, description="Biografia/descrição do profissional")
    appointment_duration: int = Field(30, ge=5, le=480, description="Duração padrão da consulta em minutos")
    buffer_time: int = Field(10, ge=0, le=60, description="Intervalo entre consultas em minutos")
    max_daily_appointments: int = Field(20, ge=1, le=100, description="Máximo de agendamentos por dia")
    availability_schedule: Optional[Dict[str, List[Dict[str, str]]]] = Field(None, description="Disponibilidade semanal")
    google_calendar_id: Optional[str] = Field(None, max_length=255, description="ID do calendário Google")


class UpdateProfessionalRequest(BaseModel):
    """Request para atualizar um profissional."""
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    specialty: Optional[str] = None
    registration_number: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    photo_url: Optional[str] = None
    room_name: Optional[str] = None
    room_number: Optional[str] = None
    color: Optional[str] = None
    bio: Optional[str] = None
    appointment_duration: Optional[int] = Field(None, ge=5, le=480)
    buffer_time: Optional[int] = Field(None, ge=0, le=60)
    max_daily_appointments: Optional[int] = Field(None, ge=1, le=100)
    accepts_new_patients: Optional[bool] = None
    is_active: Optional[bool] = None
    availability_schedule: Optional[Dict[str, List[Dict[str, str]]]] = None
    google_calendar_id: Optional[str] = None


class ProfessionalResponse(BaseModel):
    """Resposta com dados de um profissional."""
    id: int
    instance_id: str
    name: str
    specialty: Optional[str] = None
    registration_number: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    photo_url: Optional[str] = None
    room_name: Optional[str] = None
    room_number: Optional[str] = None
    color: str = "#0D9488"
    bio: Optional[str] = None
    appointment_duration: int = 30
    buffer_time: int = 10
    max_daily_appointments: int = 20
    accepts_new_patients: bool = True
    is_active: bool = True
    availability_schedule: Optional[Dict[str, Any]] = None
    google_calendar_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProfessionalListResponse(BaseModel):
    """Resposta com lista de profissionais."""
    items: List[ProfessionalResponse]
    total: int
    page: int = 1
    limit: int = 50


class CreateScheduleBlockRequest(BaseModel):
    """Request para criar um bloqueio de agenda."""
    professional_id: int = Field(..., description="ID do profissional")
    block_type: BlockType = Field(BlockType.OTHER, description="Tipo de bloqueio")
    title: Optional[str] = Field(None, max_length=255, description="Título do bloqueio")
    start_datetime: str = Field(..., description="Data/hora de início (ISO 8601)")
    end_datetime: str = Field(..., description="Data/hora de término (ISO 8601)")
    all_day: bool = Field(False, description="Bloqueio de dia inteiro")
    notes: Optional[str] = Field(None, description="Observações")


class ScheduleBlockResponse(BaseModel):
    """Resposta com dados de um bloqueio."""
    id: int
    professional_id: int
    block_type: str
    title: Optional[str] = None
    start_datetime: str
    end_datetime: str
    all_day: bool = False
    notes: Optional[str] = None
    created_at: Optional[str] = None


class CreateServiceRequest(BaseModel):
    """Request para criar um serviço."""
    professional_id: int = Field(..., description="ID do profissional")
    service_name: str = Field(..., min_length=2, max_length=255, description="Nome do serviço")
    description: Optional[str] = Field(None, description="Descrição do serviço")
    duration_minutes: int = Field(30, ge=5, le=480, description="Duração em minutos")
    price: Optional[float] = Field(None, ge=0, description="Preço do serviço")


class ServiceResponse(BaseModel):
    """Resposta com dados de um serviço."""
    id: int
    professional_id: int
    service_name: str
    description: Optional[str] = None
    duration_minutes: int = 30
    price: Optional[float] = None
    is_active: bool = True
    created_at: Optional[str] = None


class AvailabilitySlot(BaseModel):
    """Slot de disponibilidade."""
    start: str
    end: str


class AvailabilityRequest(BaseModel):
    """Request para buscar disponibilidade."""
    date: str = Field(..., description="Data (YYYY-MM-DD)")


class AvailabilityResponse(BaseModel):
    """Resposta com slots disponíveis."""
    professional_id: int
    date: str
    slots: List[AvailabilitySlot]


class ProfessionalStatsResponse(BaseModel):
    """Resposta com estatísticas de profissionais."""
    total: int = 0
    active: int = 0
    by_specialty: Dict[str, int] = {}
    rooms_in_use: int = 0


class RoomInfo(BaseModel):
    """Informações de uma sala."""
    room_name: str
    room_number: Optional[str] = None


class GenericMessageResponse(BaseModel):
    """Resposta genérica com mensagem."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ============ Google Calendar OAuth Models ============

class ProfessionalCalendarStatusResponse(BaseModel):
    """Resposta com status da conexão do Google Calendar do profissional."""
    is_connected: bool = False
    email: Optional[str] = None
    calendar_id: Optional[str] = None
    last_updated: Optional[str] = None
    message: Optional[str] = None


class FreeSlotsRequest(BaseModel):
    """Request para buscar horários livres de um profissional."""
    start_date: Optional[str] = Field(None, description="Data inicial (YYYY-MM-DD). Padrão: amanhã")
    end_date: Optional[str] = Field(None, description="Data final (YYYY-MM-DD). Padrão: 7 dias após start_date")
    timezone: str = Field("America/Sao_Paulo", description="Timezone para os horários")
    service_id: Optional[int] = Field(None, description="ID do serviço para usar duração específica")


class FreeSlotsResponse(BaseModel):
    """Resposta com horários livres."""
    professional_id: int
    professional_name: str
    slots: List[Dict[str, str]]
    total_slots: int


class ConnectedProfessionalResponse(BaseModel):
    """Profissional com Google Calendar conectado."""
    id: int
    name: str
    specialty: Optional[str] = None
    email: Optional[str] = None
    google_email: str
    calendar_id: str
    oauth_updated: Optional[str] = None
