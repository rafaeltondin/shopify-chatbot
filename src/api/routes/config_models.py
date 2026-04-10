# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, field_validator, model_validator, HttpUrl
from typing import Optional, List, Dict, Any, Union, Literal
from datetime import time as dt_time, date as dt_date, datetime as dt_datetime

def validate_time_format(value: str) -> str:
    """Valida se a string está no formato HH:MM."""
    try:
        dt_time.fromisoformat(value)
        return value
    except ValueError:
        raise ValueError(f"Formato de hora inválido: '{value}'. Use HH:MM.")

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

class ProspectingConfigRequest(BaseModel):
    start_time: str
    end_time: str
    min_delay: int = Field(..., ge=0)
    max_delay: int = Field(..., ge=0)
    allowed_weekdays: List[int] = Field(..., description="Lista de inteiros (0=Seg, 6=Dom)")

    @field_validator('start_time', 'end_time')
    def validate_time_fields(cls, v: str) -> str:
        return validate_time_format(v)

    @field_validator('allowed_weekdays')
    def validate_weekdays_range(cls, v: list, info) -> list:
        if not all(0 <= day <= 6 for day in v):
            raise ValueError('Dias da semana permitidos devem estar entre 0 (Segunda) e 6 (Domingo).')
        if len(set(v)) != len(v):
            raise ValueError('Dias da semana permitidos não devem conter duplicados.')
        return v
    
    @model_validator(mode='after')
    def check_max_delay(self) -> 'ProspectingConfigRequest':
        if self.max_delay < self.min_delay:
            raise ValueError('Atraso máximo não pode ser menor que o atraso mínimo.')
        return self

class ProspectingConfigResponse(ProspectingConfigRequest):
    pass

class FollowUpRule(BaseModel):
    stage: int
    delay_value: int = Field(..., ge=1)
    delay_unit: Literal["days", "minutes"]
    start_time: str
    end_time: str
    message: str = Field(..., min_length=1)
    enabled: bool = True
    funnel_id: Optional[str] = Field(None, description="ID do funil específico. Se None, aplica a todos os funis.")

    @field_validator('start_time', 'end_time')
    def validate_time_fields(cls, v: str, info) -> str:
        return validate_time_format(v)

    @model_validator(mode='after')
    def check_end_time_after_start_time(self) -> 'FollowUpRule':
        try:
            dt_time.fromisoformat(self.start_time)
            dt_time.fromisoformat(self.end_time)
        except ValueError:
            pass
        return self

class FollowUpConfigRequest(BaseModel):
    rules: List[FollowUpRule]

class FollowUpConfigResponse(FollowUpConfigRequest):
    pass

class EvolutionConfigRequest(BaseModel):
    url: HttpUrl
    api_key: str
    instance_name: str = Field(..., min_length=1)

class EvolutionConfigResponse(BaseModel):
    url: Optional[str] = None
    api_key: Optional[str] = None
    instance_name: Optional[str] = None

class ProductContextRequest(BaseModel):
    context: Optional[str] = Field(None, description="Contexto do produto em formato de texto livre.")
    db_url: Optional[str] = Field(None, description="URL de conexão com o banco de dados externo.")
    sql_query: Optional[str] = Field(None, description="Query SQL a ser executada no banco de dados externo.")

class ProductContextResponse(BaseModel):
    context: Optional[str] = None
    db_url: Optional[str] = None
    sql_query: Optional[str] = None
    db_data: Optional[List[Dict[str, Any]]] = None

class SystemPromptRequest(BaseModel):
    system_prompt: str

class SystemPromptResponse(SystemPromptRequest):
    pass

class LLMConfigRequest(BaseModel):
    llm_model_preference: str
    llm_temperature: float = Field(..., ge=0.0, le=2.0)

class LLMConfigResponse(BaseModel):
    llm_model_preference: str
    llm_temperature: float

class SalesFlowActionItem(BaseModel):
    type: Literal['send_text', 'send_audio']
    delay_ms: int = Field(0, ge=0)
    text: Optional[Union[str, List[str]]] = None
    audio_file: Optional[str] = None

class SalesFlowStageBase(BaseModel):
    """Modelo base para estágios do funil de vendas."""
    stage_number: int
    trigger_description: str = ""
    objective: str = ""
    action_type: Literal['sequence', 'ask_llm'] = 'ask_llm'
    action_sequence: Optional[List[SalesFlowActionItem]] = None
    action_llm_prompt: Optional[str] = None


class SalesFlowStage(SalesFlowStageBase):
    """Modelo com validação rigorosa para criação/atualização de estágios."""

    @model_validator(mode='after')
    def validate_first_stage_rules(self) -> 'SalesFlowStage':
        """✅ VALIDAÇÃO CRÍTICA: Primeiro estágio DEVE ser sequence"""
        if self.stage_number == 1:
            if self.action_type != 'sequence':
                raise ValueError(f"Primeiro estágio (stage_number=1) DEVE ter action_type='sequence', mas recebeu '{self.action_type}'")

            if not isinstance(self.action_sequence, list) or len(self.action_sequence) == 0:
                raise ValueError("Primeiro estágio DEVE ter action_sequence como lista não-vazia")

            has_send_text = any(
                action.type == 'send_text'
                for action in self.action_sequence
            )
            if not has_send_text:
                raise ValueError("Primeiro estágio DEVE ter pelo menos uma ação do tipo 'send_text'")

            if self.action_llm_prompt is not None:
                raise ValueError("Primeiro estágio DEVE ter action_llm_prompt=null")

        return self


class SalesFlowStageResponse(SalesFlowStageBase):
    """Modelo sem validação rigorosa para leitura (compatível com dados legados)."""
    pass


class SalesFlowConfigRequest(BaseModel):
    stages: List[SalesFlowStage]

    @model_validator(mode='after')
    def validate_stages_order(self) -> 'SalesFlowConfigRequest':
        """✅ VALIDAÇÃO: Garantir ordem sequencial e primeiro estágio correto"""
        if not self.stages:
            raise ValueError("Lista de estágios não pode estar vazia")

        # Ordenar por stage_number
        self.stages.sort(key=lambda s: s.stage_number)

        # Verificar se existe estágio 1
        if self.stages[0].stage_number != 1:
            raise ValueError("Deve existir um estágio com stage_number=1")

        return self


class SalesFlowConfigResponse(BaseModel):
    """Response model para leitura de funil (compatível com dados legados)."""
    stages: List[SalesFlowStageResponse]

class GenerateSalesFlowRequest(BaseModel):
    ai_funnel_tips: Optional[str] = None

class FirstMessageConfig(BaseModel):
    messages: List[str] = Field(..., min_length=1, max_length=20, description="List of up to 20 different first prospecting messages.")
    enabled: bool = Field(True, description="Enable or disable message rotation.")

class FirstMessageConfigResponse(FirstMessageConfig):
    pass


# --- Insufficient Context Notification Config ---
class InsufficientContextNotificationRequest(BaseModel):
    """Configuração para notificação quando o LLM não tem contexto suficiente."""
    enabled: bool = Field(True, description="Habilita ou desabilita a notificação de contexto insuficiente.")
    notification_whatsapp_number: Optional[str] = Field(None, description="Número de WhatsApp para receber notificações (formato: 5511999999999).")
    notification_message_template: str = Field(
        "⚠️ *Contexto Insuficiente Detectado*\n\n📱 *Cliente:* {customer_phone}\n💬 *Mensagem:* {customer_message}\n\n❓ O agente de IA não encontrou informações suficientes no contexto para responder esta pergunta.\n\n⏰ *Horário:* {timestamp}",
        description="Template da mensagem de notificação. Variáveis: {customer_phone}, {customer_message}, {timestamp}, {customer_name}"
    )
    suppress_response_to_customer: bool = Field(False, description="Se True, não envia nenhuma resposta ao cliente quando detectar contexto insuficiente.")
    customer_fallback_message: str = Field(
        "Entendi sua dúvida. Vou verificar essa informação e retorno em breve!",
        description="Mensagem enviada ao cliente quando contexto é insuficiente (se suppress_response_to_customer=False)."
    )

    @field_validator('notification_whatsapp_number')
    def validate_whatsapp_number(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == '':
            return None
        # Remove caracteres não numéricos
        cleaned = ''.join(filter(str.isdigit, v))
        if len(cleaned) < 10 or len(cleaned) > 15:
            raise ValueError(f"Número de WhatsApp inválido: '{v}'. Deve ter entre 10 e 15 dígitos.")
        return cleaned


class InsufficientContextNotificationResponse(InsufficientContextNotificationRequest):
    pass


# --- Stage Change Notification Config ---
class StageNotificationRule(BaseModel):
    """Regra de notificação para quando um prospect atinge uma etapa específica."""
    # ge=0 para permitir 0 como etapa especial "Agendamentos" (scheduled)
    stage_number: int = Field(..., ge=0, description="Número da etapa que dispara a notificação. Use 0 para etapa especial 'Agendamentos'.")
    enabled: bool = Field(True, description="Se esta regra está ativa.")
    message_template: str = Field(
        "🎯 *Prospect Avançou de Etapa!*\n\n👤 *Nome:* {prospect_name}\n📱 *Telefone:* {prospect_phone}\n\n📊 *Nova Etapa:* {stage_name} (Etapa {stage_number})\n⏰ *Horário:* {timestamp}",
        description="Template da mensagem. Variáveis: {prospect_name}, {prospect_phone}, {stage_name}, {stage_number}, {old_stage_name}, {old_stage_number}, {timestamp}"
    )
    funnel_id: Optional[str] = Field(None, description="ID do funil específico. Se None, aplica a todos os funis.")


class StageChangeNotificationRequest(BaseModel):
    """Configuração completa para notificações de mudança de etapa."""
    enabled: bool = Field(True, description="Habilita ou desabilita todas as notificações de mudança de etapa.")
    notification_whatsapp_number: Optional[str] = Field(None, description="Número de WhatsApp para receber notificações (formato: 5511999999999).")
    notify_all_stages: bool = Field(True, description="Se True, notifica para todas as etapas. Se False, usa stage_rules.")
    notify_all_funnels: bool = Field(True, description="Se True, notifica para todos os funis. Se False, usa funnel_id das stage_rules.")
    stage_rules: List[StageNotificationRule] = Field(default_factory=list, description="Regras específicas por etapa (usado quando notify_all_stages=False).")
    default_message_template: str = Field(
        "🎯 *Prospect Avançou de Etapa!*\n\n👤 *Nome:* {prospect_name}\n📱 *Telefone:* {prospect_phone}\n\n📊 *Etapa Anterior:* {old_stage_name}\n📊 *Nova Etapa:* {stage_name}\n⏰ *Horário:* {timestamp}",
        description="Template padrão da mensagem quando notify_all_stages=True."
    )

    @field_validator('notification_whatsapp_number')
    @classmethod
    def validate_whatsapp_number(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v.strip() == '':
            return None
        # Remove caracteres não numéricos
        cleaned = ''.join(filter(str.isdigit, v))
        if len(cleaned) < 10 or len(cleaned) > 15:
            raise ValueError(f"Número de WhatsApp inválido: '{v}'. Deve ter entre 10 e 15 dígitos.")
        return cleaned


class StageChangeNotificationResponse(StageChangeNotificationRequest):
    pass


# --- Sales Funnels (Múltiplos Funis de Vendas) ---
class SalesFunnel(BaseModel):
    """Modelo completo de um funil de vendas."""
    funnel_id: str = Field(..., min_length=1, max_length=100, description="ID único do funil (UUID ou slug)")
    name: str = Field(..., min_length=1, max_length=255, description="Nome descritivo do funil")
    description: Optional[str] = Field(None, max_length=1000, description="Descrição opcional do funil")
    stages: List[SalesFlowStageResponse] = Field(..., description="Lista de estágios do funil")
    is_default: bool = Field(False, description="Se é o funil padrão da instância")
    is_active: bool = Field(True, description="Se o funil está ativo")
    created_at: Optional[str] = Field(None, description="Data de criação (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="Data da última atualização (ISO 8601)")


class SalesFunnelSummary(BaseModel):
    """Modelo resumido para listagem de funis."""
    funnel_id: str
    name: str
    description: Optional[str] = None
    stages_count: int = Field(0, description="Número de estágios no funil")
    is_default: bool = False
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FunnelListResponse(BaseModel):
    """Response para listagem de funis."""
    funnels: List[SalesFunnelSummary] = Field(default_factory=list)
    total: int = Field(0, description="Total de funis encontrados")


class CreateFunnelRequest(BaseModel):
    """Request para criar um novo funil."""
    name: str = Field(..., min_length=1, max_length=255, description="Nome do funil")
    description: Optional[str] = Field(None, max_length=1000, description="Descrição opcional")
    stages: Optional[List[SalesFlowStage]] = Field(None, description="Estágios do funil (opcional, pode copiar de outro)")
    copy_from_funnel_id: Optional[str] = Field(None, description="ID do funil para copiar estágios")
    set_as_default: bool = Field(False, description="Definir como funil padrão")


class UpdateFunnelRequest(BaseModel):
    """Request para atualizar um funil existente."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Novo nome do funil")
    description: Optional[str] = Field(None, max_length=1000, description="Nova descrição")
    stages: Optional[List[SalesFlowStage]] = Field(None, description="Novos estágios do funil")
    is_active: Optional[bool] = Field(None, description="Se o funil está ativo")


class UpdateProspectFunnelRequest(BaseModel):
    """Request para mudar o funil de um prospect."""
    funnel_id: str = Field(..., min_length=1, description="ID do novo funil")
    reset_stage: bool = Field(True, description="Se deve resetar o estágio para 1")
    target_stage: Optional[int] = Field(None, ge=1, description="Estágio de destino (se reset_stage=False)")


class FunnelResponse(BaseModel):
    """Response após operações de funil."""
    success: bool
    message: str
    funnel: Optional[SalesFunnel] = None
