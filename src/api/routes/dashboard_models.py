# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class StatusResponse(BaseModel):
    status: str
    active_prospects: int
    queue_size: int
    is_processing_queue: bool
    container_url: Optional[str] = None


class EvolutionHealthResponse(BaseModel):
    """Resposta do health check da Evolution API."""
    healthy: bool
    status: str = Field(..., description="Status geral: healthy, degraded, unhealthy, unknown")
    consecutive_failures: int = Field(..., description="Número de falhas consecutivas")
    seconds_since_last_success: Optional[float] = Field(None, description="Segundos desde última conexão bem-sucedida")
    connection_state: Optional[str] = Field(None, description="Estado da conexão WhatsApp: open, close, connecting")
    response_time_ms: Optional[float] = Field(None, description="Tempo de resposta do health check em ms")
    error: Optional[str] = Field(None, description="Mensagem de erro se houver")
    client_version: str = Field(..., description="Versão do cliente Evolution")

class DashboardStatsResponse(BaseModel):
    total_prospects: int = Field(..., description="Total de prospects no sistema.")
    active_prospects: int = Field(..., description="Prospects com status 'active'.")
    messages_sent: int = Field(..., description="Total de mensagens enviadas.")
    total_prompt_tokens: int = Field(..., description="Total de tokens de prompt usados.")
    total_completion_tokens: int = Field(..., description="Total de tokens de completion usados.")
    total_tokens: int = Field(..., description="Soma de todos os tokens usados.")
    total_prospects_user_initiated: int = Field(..., description="Total de prospects iniciados pelo usuário.")
    active_prospects_user_initiated: int = Field(..., description="Prospects ativos iniciados pelo usuário.")
    total_prospects_llm_initiated: int = Field(..., description="Total de prospects iniciados pelo LLM.")
    active_prospects_llm_initiated: int = Field(..., description="Prospects ativos iniciados pelo LLM.")

class RecentActivity(BaseModel):
    jid: str
    last_message_role: str
    last_message_content: str
    timestamp: str

class DashboardData(BaseModel):
    stats: DashboardStatsResponse
    recent_activity: List[RecentActivity]

class FunnelStage(BaseModel):
    stage: int
    count: int

class DashboardFunnelResponse(BaseModel):
    stages: List[FunnelStage]
    total_in_funnel: int

class ConversationInitiator(str, Enum):
    USER = "user"
    LLM_AGENT = "llm_agent"
    ALL = "all"

class ToggleAIQueueOnlyRequest(BaseModel):
    enable: bool

class ConversionRate(BaseModel):
    from_stage: int
    to_stage: int
    conversion_rate: float = Field(..., description="Conversion rate in percentage.")
    from_count: int
    to_count: int

class AvgTimeInStage(BaseModel):
    stage: int
    avg_duration_seconds: float = Field(..., description="Average time spent in this stage in seconds.")

class DashboardAnalyticsResponse(BaseModel):
    conversion_rates: List[ConversionRate]
    avg_time_in_stage: List[AvgTimeInStage]
