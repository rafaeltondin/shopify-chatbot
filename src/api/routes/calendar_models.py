# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, field_validator, model_validator, EmailStr
from typing import Optional, List, Union, Literal
from datetime import time as dt_time, date as dt_date, datetime as dt_datetime

def validate_date_format(value: str) -> str:
    """Valida se a string está no formato YYYY-MM-DD."""
    try:
        dt_date.fromisoformat(value)
        return value
    except ValueError:
        raise ValueError(f"Formato de data inválido: '{value}'. Use YYYY-MM-DD.")

def validate_datetime_format(value: str) -> str:
    """Valida se a string é um datetime ISO 8601 válido."""
    try:
        dt_datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value
    except ValueError:
        raise ValueError(f"Formato de datetime inválido: '{value}'. Use ISO 8601.")

class AvailabilitySchedule(BaseModel):
    monday: Optional[List[str]] = Field(None, example=["09:00-12:00", "14:00-17:00"])
    tuesday: Optional[List[str]] = Field(None, example=["09:00-17:00"])
    wednesday: Optional[List[str]] = Field(None)
    thursday: Optional[List[str]] = Field(None)
    friday: Optional[List[str]] = Field(None)
    saturday: Optional[List[str]] = Field(None)
    sunday: Optional[List[str]] = Field(None)
    include_video_call: Optional[bool] = Field(False, description="Define se a IA pode agendar reuniões com videochamada (Google Meet).")

class CalendarStatusResponse(BaseModel):
    is_connected: bool
    email: Optional[str] = None
    message: str

from datetime import timedelta

class ScheduleMeetingRequest(BaseModel):
    start_time: str
    end_time: Optional[str] = None  # Tornou-se opcional
    summary: str = "Reunião Agendada"
    description: Optional[str] = None
    attendees: Optional[List[EmailStr]] = Field(None, example=["prospect@example.com"])
    request_id: Optional[str] = Field(None, description="Unique request ID for idempotency")
    isVideoCall: Optional[bool] = Field(False, description="Indica se a reunião deve incluir uma videochamada do Google Meet.")
    meetingUserType: Optional[Literal['prospecting_user', 'normal_user']] = Field(None, description="Tipo de usuário associado ao agendamento.")
    prospect_jid: Optional[str] = Field(None, description="JID do prospect associado ao agendamento.")

    @field_validator('start_time', 'end_time')
    def validate_datetime_fields(cls, v: str, info) -> str:
        if v is None:
            return v
        return validate_datetime_format(v)

    @model_validator(mode='after')
    def check_and_set_meeting_times(self) -> 'ScheduleMeetingRequest':
        if not self.start_time:
            # A validação de campo já deve ter pego isso, mas é uma segurança extra.
            return self

        try:
            start_dt = dt_datetime.fromisoformat(self.start_time.replace('Z', '+00:00'))
            
            # Se end_time não for fornecido, calcule-o (start + 30 minutos)
            if not self.end_time:
                end_dt = start_dt + timedelta(minutes=30)
                self.end_time = end_dt.isoformat()
            else:
                end_dt = dt_datetime.fromisoformat(self.end_time.replace('Z', '+00:00'))

            # Se end_time for igual ou anterior a start_time, recalcule-o
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(minutes=30)
                self.end_time = end_dt.isoformat()

        except (ValueError, TypeError) as e:
            # Se houver qualquer erro de parsing, levanta um ValueError claro.
            raise ValueError(f"Erro ao processar datas/horas: {e}")
        
        return self

class CancelMeetingRequest(BaseModel):
    eventId: str = Field(..., description="O ID do evento do Google Calendar a ser cancelado.")

class FreeBusyRequest(BaseModel):
    start_date: Optional[str] = Field(None, example="2025-06-01", description="Optional: Start date in YYYY-MM-DD format. Defaults to tomorrow if not provided.")
    end_date: Optional[str] = Field(None, example="2025-06-07", description="Optional: End date in YYYY-MM-DD format (inclusive). Defaults to 7 days from start_date if not provided.")
    timezone: str = Field("America/Sao_Paulo", description="Timezone for the request, e.g., America/Sao_Paulo")

    @field_validator('start_date', 'end_date')
    def ensure_date_format_if_present(cls, v: Union[str, None]) -> Union[str, None]:
        if v is not None:
            return validate_date_format(v)
        return v

    @model_validator(mode='after')
    def check_end_date_after_start_date(self) -> 'FreeBusyRequest':
        if self.end_date and self.start_date:
            try:
                start_d = dt_date.fromisoformat(self.start_date)
                end_d = dt_date.fromisoformat(self.end_date)
                if end_d < start_d:
                    raise ValueError('Data de término deve ser igual ou após a data de início.')
            except ValueError as e:
                raise ValueError(str(e))
        return self
        
    @field_validator('timezone')
    def check_timezone_validity(cls, v: str) -> str:
        try:
            import pytz
            pytz.timezone(v)
            return v
        except pytz.exceptions.UnknownTimeZoneError:
            raise ValueError(f"Timezone inválido: '{v}'.")
