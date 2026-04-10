# -*- coding: utf-8 -*-
"""
LLM Manager Module - Sistema completo de gerenciamento de LLM com OpenRouter
Versão atualizada com coleta obrigatória de nome e email para agendamento
"""
import logging
import json
import re
import asyncio
import httpx
import time
from typing import List, Dict, Any, Optional, Tuple, AsyncGenerator, Union
import pytz
from datetime import datetime, timedelta

from openai import AsyncOpenAI, APIError, RateLimitError, BadRequestError
from pydantic import BaseModel, Field, ValidationError
from typing import Literal

from .config import settings, logger
from .db_operations.config_crud import get_product_context, get_llm_system_prompt, get_sales_flow_stages, get_config_value, get_ai_for_prospect_queue_only
from .db_operations import professionals_crud
from .security import create_access_token
from ..utils.text_utils import _translate_date_parts_to_ptbr
from ..utils.llm_utils import (
    TaskType, get_models_by_task, build_openrouter_headers, build_provider_config,
    retry_with_exponential_backoff, get_metrics, _cache, InsufficientCreditsError
)

# Configure module logger
logger = logging.getLogger(__name__)

# =============================================================================
# PYDANTIC MODELS (in dependency order)
# =============================================================================

class ToolArgumentAnalysis(BaseModel):
    """Análise detalhada dos argumentos de uma ferramenta"""
    is_valid: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    confidence_score: float = 0.0
    detected_issues: List[str] = []
    suggested_fixes: List[str] = []
    extracted_first_json: Optional[str] = None

class ToolExecutionResult(BaseModel):
    """Resultado da execução de uma ferramenta"""
    success: bool
    result: Any
    error: Optional[str] = None
    execution_time: float
    cached: bool = False
    argument_analysis: Optional[ToolArgumentAnalysis] = None

class LLMTextResponse(BaseModel):
    """Resposta estruturada do LLM para conversas"""
    action: Literal["send_text", "wait", "fetch_available_slots", "schedule_meeting_via_api", "collect_user_data"] = Field(..., description="A ação a ser executada.")
    text: Optional[str] = Field(None, description="O texto a ser enviado ao cliente.")
    reason: str = Field(..., description="A justificativa detalhada para a ação tomada.")
    next_stage: Optional[int] = Field(None, description="O próximo estágio do funil, se uma mudança for identificada.")
    requires_scheduling: bool = Field(default=False, description="Indica se precisa de agendamento.")
    scheduling_context: Optional[Dict[str, Any]] = Field(None, description="Contexto para agendamento se necessário.")
    arguments: Optional[Dict[str, Any]] = Field(None, description="Argumentos para ferramentas quando action é fetch_available_slots ou schedule_meeting_via_api")
    required_data: Optional[List[str]] = Field(None, description="Lista de dados necessários (nome, email) para continuar")

class ScheduleMeetingToolSchema(BaseModel):
    """Schema para agendamento de reunião"""
    start_time: str = Field(..., description="Horário de início no formato ISO 8601 (ex: '2024-08-23T14:00:00-03:00').")
    end_time: str = Field(..., description="Horário de término no formato ISO 8601 (ex: '2024-08-23T15:00:00-03:00').")
    summary: str = Field(..., description="Título ou resumo da reunião (ex: 'Demonstração do Produto').")
    description: Optional[str] = Field(None, description="Descrição detalhada ou pauta da reunião.")
    attendees: List[str] = Field(..., description="Lista de e-mails dos participantes, incluindo o do cliente.")
    isVideoCall: bool = Field(default=True, description="Indica se deve ser criada uma chamada de vídeo (Google Meet).")
    meetingUserType: Literal["prospecting_user", "normal_user"] = Field(default="prospecting_user", description="Tipo de usuário para quem a reunião está sendo agendada.")
    customer_name: Optional[str] = Field(None, description="Nome do cliente para registro")

class LLMResponseData(BaseModel):
    """Dados de resposta do LLM"""
    action_data: Dict[str, Any]
    token_usage: Dict[str, int]
    model_used: str
    response_time: float
    cached: bool = False
    tools_executed: List[str] = []

class SalesFlowAction(BaseModel):
    """Ação dentro de um funil de vendas"""
    type: Literal["send_text"]
    delay_ms: int
    text: str

class SalesFlowStage(BaseModel):
    """Estágio do funil de vendas"""
    stage_number: int
    objective: str
    trigger_description: str
    action_type: Literal["sequence", "ask_llm"]
    action_sequence: Optional[List[SalesFlowAction]] = None
    action_llm_prompt: Optional[str] = None

class SalesFlow(BaseModel):
    """Funil de vendas completo"""
    stages: List[SalesFlowStage]

# =============================================================================
# CUSTOMER DATA STORAGE
# =============================================================================

class CustomerDataStore:
    """Armazenamento temporário de dados do cliente para agendamento"""
    
    def __init__(self):
        self._store = {}
        logger.info("CustomerDataStore inicializado")
    
    def set_customer_data(self, chat_id: str, data: Dict[str, Any]):
        """Armazena dados do cliente por chat_id"""
        if chat_id not in self._store:
            self._store[chat_id] = {}
        self._store[chat_id].update(data)
        logger.info(f"Dados do cliente atualizados para chat {chat_id}: {data}")
    
    def get_customer_data(self, chat_id: str) -> Dict[str, Any]:
        """Recupera dados do cliente por chat_id"""
        return self._store.get(chat_id, {})
    
    def has_required_data(self, chat_id: str, require_professional: bool = False, require_patient_data: bool = True) -> Tuple[bool, List[str]]:
        """
        Verifica se tem todos os dados necessários para agendamento.

        Args:
            chat_id: ID do chat
            require_professional: Se True, verifica se professional_id foi coletado
            require_patient_data: Se True, verifica CPF, nome completo e data de nascimento (padrão True para clínicas)

        Returns:
            Tuple (tem_todos_dados, lista_de_faltantes)
        """
        data = self.get_customer_data(chat_id)
        missing = []

        name = data.get('name', '').strip() if data.get('name') else ''
        email = data.get('email', '').strip() if data.get('email') else ''

        if not name:
            missing.append('nome')
        if not email:
            missing.append('email')

        # Verificar professional_id se necessário
        if require_professional and not data.get('professional_id'):
            missing.append('profissional')

        # ========== DADOS DO PACIENTE PARA CLÍNICAS MÉDICAS ==========
        if require_patient_data:
            cpf = data.get('cpf', '').strip() if data.get('cpf') else ''
            full_name = data.get('full_name', '').strip() if data.get('full_name') else ''
            birth_date = data.get('birth_date', '').strip() if data.get('birth_date') else ''

            if not cpf:
                missing.append('cpf')
            if not full_name:
                missing.append('nome_completo')
            if not birth_date:
                missing.append('data_nascimento')

        logger.debug(f"[{chat_id}] Verificação de dados - Nome: '{name}', Email: '{email}', CPF: '{data.get('cpf')}', Nome Completo: '{data.get('full_name')}', Nascimento: '{data.get('birth_date')}', Professional: {data.get('professional_id')}, Faltando: {missing}")

        return len(missing) == 0, missing

    def get_professional_id(self, chat_id: str) -> Optional[int]:
        """Retorna o ID do profissional selecionado, se houver."""
        data = self.get_customer_data(chat_id)
        return data.get('professional_id')

    def get_professional_name(self, chat_id: str) -> Optional[str]:
        """Retorna o nome do profissional selecionado, se houver."""
        data = self.get_customer_data(chat_id)
        return data.get('professional_name')
    
    def clear_customer_data(self, chat_id: str):
        """Limpa dados do cliente após agendamento"""
        if chat_id in self._store:
            del self._store[chat_id]
            logger.info(f"Dados do cliente limpos para chat {chat_id}")

# Instância global do armazenamento de dados do cliente
_customer_store = CustomerDataStore()

# =============================================================================
# UTILITY CLASSES
# =============================================================================

class ToolExecutionLogger:
    """Sistema de logging avançado para execução de ferramentas"""

    def __init__(self):
        self.execution_stats = {}
        self.error_patterns = {}
        self.performance_metrics = {}
        logger.info("ToolExecutionLogger inicializado")

    def log_execution_start(self, tool_name: str, arguments: str, call_id: str = None):
        """Log do início da execução de uma ferramenta"""
        try:
            logger.info(f"🚀 [TOOL_START] {tool_name} | ID: {call_id or 'N/A'}")
            logger.debug(f"📝 [TOOL_ARGS] {tool_name} | Argumentos: {arguments[:200]}{'...' if len(arguments) > 200 else ''}")

            if tool_name not in self.execution_stats:
                self.execution_stats[tool_name] = {"calls": 0, "successes": 0, "failures": 0}
            self.execution_stats[tool_name]["calls"] += 1
        except Exception as e:
            logger.error(f"Erro em log_execution_start: {e}", exc_info=True)

    def log_execution_success(self, tool_name: str, result: Any, execution_time: float, call_id: str = None):
        """Log de execução bem-sucedida"""
        try:
            logger.info(f"✅ [TOOL_SUCCESS] {tool_name} | Tempo: {execution_time:.2f}s | ID: {call_id or 'N/A'}")
            logger.debug(f"📤 [TOOL_RESULT] {tool_name} | Resultado: {str(result)[:300]}{'...' if len(str(result)) > 300 else ''}")

            if tool_name in self.execution_stats:
                self.execution_stats[tool_name]["successes"] += 1

            if tool_name not in self.performance_metrics:
                self.performance_metrics[tool_name] = {"times": [], "avg_time": 0.0}

            self.performance_metrics[tool_name]["times"].append(execution_time)
            if len(self.performance_metrics[tool_name]["times"]) > 100:
                self.performance_metrics[tool_name]["times"].pop(0)

            avg_time = sum(self.performance_metrics[tool_name]["times"]) / len(self.performance_metrics[tool_name]["times"])
            self.performance_metrics[tool_name]["avg_time"] = avg_time
        except Exception as e:
            logger.error(f"Erro em log_execution_success: {e}", exc_info=True)

    def log_execution_failure(self, tool_name: str, error: str, execution_time: float, call_id: str = None):
        """Log de falha na execução"""
        try:
            logger.error(f"❌ [TOOL_FAILURE] {tool_name} | Tempo até erro: {execution_time:.2f}s | ID: {call_id or 'N/A'}")
            logger.error(f"💥 [TOOL_ERROR] {tool_name} | Erro: {error}")

            if tool_name in self.execution_stats:
                self.execution_stats[tool_name]["failures"] += 1

            error_key = error[:100]
            if error_key not in self.error_patterns:
                self.error_patterns[error_key] = {"count": 0, "tools": set()}
            self.error_patterns[error_key]["count"] += 1
            self.error_patterns[error_key]["tools"].add(tool_name)
        except Exception as e:
            logger.error(f"Erro em log_execution_failure: {e}", exc_info=True)

# =============================================================================
# GLOBAL INSTANCES
# =============================================================================

_tool_logger = ToolExecutionLogger()

# =============================================================================
# MAIN LLM MANAGER CLASS
# =============================================================================

class LLMManager:
    """Gerenciador central para todas as operações de LLM com OpenRouter"""

    def __init__(self):
        self.client: Optional[AsyncOpenAI] = None
        self.deepseek_client: Optional[AsyncOpenAI] = None
        self._initialized = False
        logger.info("LLMManager criado")

    def _get_client_for_model(self, model: str) -> AsyncOpenAI:
        """Retorna o cliente correto baseado no nome do modelo."""
        if self.deepseek_client and model.startswith("deepseek"):
            return self.deepseek_client
        return self.client

    async def initialize(self):
        """Inicializa clientes LLM (OpenRouter + DeepSeek direto se configurado)"""
        try:
            if self._initialized and self.client:
                return

            # ── Cliente OpenRouter (mantido como fallback) ──
            api_key = settings.OPENROUTER_API_KEY
            if not api_key:
                logger.critical("FATAL: OPENROUTER_API_KEY não está configurada.")
                raise ValueError("OPENROUTER_API_KEY não configurada")

            headers = build_openrouter_headers()
            self.client = AsyncOpenAI(
                base_url=settings.OPENROUTER_BASE_URL,
                api_key=api_key,
                default_headers=headers,
                timeout=settings.LLM_TIMEOUT,
                max_retries=0
            )

            # ── Cliente DeepSeek direto (opcional) ──
            if settings.DEEPSEEK_API_KEY:
                self.deepseek_client = AsyncOpenAI(
                    base_url=settings.DEEPSEEK_BASE_URL,
                    api_key=settings.DEEPSEEK_API_KEY,
                    timeout=settings.LLM_TIMEOUT,
                    max_retries=0
                )
                logger.info("DeepSeek client inicializado (API direta)")

            self._initialized = True
            logger.info("LLMManager inicializado")
        except Exception as e:
            logger.error(f"Falha ao inicializar LLMManager: {e}", exc_info=True)
            raise

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        task_type: TaskType = TaskType.CONVERSATION,
        tools: Optional[List[Dict]] = None,
        streaming: bool = None,
        chat_id: str = None,
        **kwargs
    ) -> Union[LLMResponseData, AsyncGenerator]:
        """Obtém resposta do LLM com suporte completo a ferramentas"""
        try:
            if not self._initialized:
                await self.initialize()

            if streaming is None:
                streaming = kwargs.get('stream', False)

            if streaming:
                return await self._get_streaming_response(messages, task_type, tools, **kwargs)
            else:
                return await self._get_standard_response(messages, task_type, tools, chat_id, **kwargs)
        except Exception as e:
            logger.error(f"Erro em get_response: {e}", exc_info=True)
            return LLMResponseData(
                action_data={"action": "send_text", "text": "Erro interno do sistema.", "reason": "Falha na comunicação com LLM"},
                token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                model_used="unknown",
                response_time=0.0,
                tools_executed=[]
            )

    async def _get_standard_response(
        self,
        messages: List[Dict[str, Any]],
        task_type: TaskType = TaskType.CONVERSATION,
        tools: Optional[List[Dict]] = None,
        chat_id: str = None,
        **kwargs
    ) -> LLMResponseData:
        """Obtém resposta padrão (não-streaming) com retry e cache"""

        start_time = time.time()
        tools_executed = []

        completion_params = await self._prepare_completion_params(messages, task_type, tools, **kwargs)
        original_max_tokens = completion_params.get('max_tokens', 4096)

        _client = self._get_client_for_model(completion_params.get("model", ""))

        async def make_request():
            return await _client.chat.completions.create(**completion_params)

        try:
            completion = await retry_with_exponential_backoff(make_request)

        except InsufficientCreditsError as ice:
            # Tratamento especial para créditos insuficientes
            logger.warning(
                f"[{chat_id}] [LLM_CREDITS_RETRY] Créditos insuficientes. "
                f"Disponível: {ice.available_tokens}, Solicitado: {ice.requested_tokens}. "
            )

            # Verificar se temos informação suficiente para retry
            # -1 significa erro 402 sem informação de tokens (não tentar novamente)
            # 0 significa que não conseguiu extrair informação (não tentar novamente)
            if ice.available_tokens <= 0:
                logger.error(
                    f"[{chat_id}] [LLM_CREDITS] Sem informação de tokens disponíveis ou créditos esgotados. "
                    f"Não é possível calcular retry. available_tokens={ice.available_tokens}"
                )
                return LLMResponseData(
                    action_data={
                        "action": "send_text",
                        "text": "Desculpe, estou temporariamente indisponível. Nossa equipe já foi notificada.",
                        "reason": "Créditos LLM esgotados ou indisponíveis"
                    },
                    token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    model_used=completion_params.get('model', 'unknown'),
                    response_time=time.time() - start_time,
                    tools_executed=[]
                )

            # Calcular novo max_tokens (80% do disponível para dar margem)
            if ice.available_tokens > 100:
                new_max_tokens = int(ice.available_tokens * 0.8)
                completion_params['max_tokens'] = new_max_tokens
                logger.info(f"[{chat_id}] [LLM_CREDITS_RETRY] Tentando com max_tokens reduzido de {original_max_tokens} para {new_max_tokens}")

                try:
                    # Segunda tentativa com tokens reduzidos (sem usar retry_with_exponential_backoff para evitar loop)
                    completion = await self.client.chat.completions.create(**completion_params)
                    logger.info(f"[{chat_id}] [LLM_CREDITS_RETRY] Sucesso com max_tokens={new_max_tokens}")

                except Exception as retry_error:
                    logger.error(f"[{chat_id}] [LLM_CREDITS_RETRY] Falha mesmo com tokens reduzidos: {retry_error}")
                    return LLMResponseData(
                        action_data={
                            "action": "send_text",
                            "text": "Desculpe, estou com dificuldades técnicas no momento. Por favor, tente novamente em alguns minutos.",
                            "reason": "Erro de créditos LLM após retry"
                        },
                        token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                        model_used=completion_params.get('model', 'unknown'),
                        response_time=time.time() - start_time,
                        tools_executed=[]
                    )
            else:
                # Créditos muito baixos (entre 1-100), não tentar novamente
                logger.error(f"[{chat_id}] [LLM_CREDITS] Créditos muito baixos ({ice.available_tokens} tokens). Não é possível processar.")
                return LLMResponseData(
                    action_data={
                        "action": "send_text",
                        "text": "Desculpe, estou temporariamente indisponível. Nossa equipe já foi notificada.",
                        "reason": "Créditos LLM esgotados"
                    },
                    token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    model_used=completion_params.get('model', 'unknown'),
                    response_time=time.time() - start_time,
                    tools_executed=[]
                )

        # Processar resposta do completion
        response_time = time.time() - start_time

        try:
            choice = completion.choices[0]
            response_message = choice.message

            # Extrair dados de ação
            action_data = self._extract_action_data(response_message, task_type, tools_executed, chat_id)
            
            # --- INÍCIO DA CORREÇÃO ---
            # 1. Processar e salvar IMEDIATAMENTE quaisquer dados que o LLM tenha coletado.
            if "collected_data" in action_data and chat_id:
                collected = action_data.get("collected_data")
                if isinstance(collected, dict):
                    logger.info(f"[{chat_id}] LLM retornou dados para coletar: {collected}")
                    # Esta função atualiza o armazenamento temporário
                    _customer_store.set_customer_data(chat_id, collected)
            # --- FIM DA CORREÇÃO ---

            # 2. AGORA, com os dados potencialmente atualizados, verificar se o agendamento pode prosseguir.
            # IMPORTANTE: fetch_available_slots NÃO precisa de dados do cliente (apenas consulta)
            # Apenas schedule_meeting_via_api precisa de nome e email
            action_name = action_data.get("action")

            if action_name == "fetch_available_slots":
                # Buscar horários NÃO precisa de nome/email - executar direto
                logger.info(f"[{chat_id}] Executando fetch_available_slots (não requer dados do cliente)")
                tool_result = await self._execute_tool_from_action(action_data, chat_id)
                if tool_result.success:
                    action_data = {
                        "action": "send_text",
                        "text": str(tool_result.result),
                        "reason": "Resultado da busca de horários disponíveis"
                    }
                    tools_executed.append("fetch_available_slots")
                else:
                    # Não enviar mensagem técnica ao cliente - usar mensagem amigável
                    logger.error(f"[{chat_id}] Erro técnico ao buscar horários: {tool_result.error}")
                    action_data = {
                        "action": "send_text",
                        "text": "Desculpe, tive um problema ao verificar os horários disponíveis. Vou tentar novamente em instantes.",
                        "reason": "Erro na execução da ferramenta"
                    }

            elif action_name == "schedule_meeting_via_api":
                # Agendar reunião PRECISA de nome e email
                has_data, missing = _customer_store.has_required_data(chat_id) if chat_id else (False, ['nome', 'email'])

                # Log detalhado para debug
                current_customer_data = _customer_store.get_customer_data(chat_id) if chat_id else {}
                logger.info(f"[{chat_id}] Verificando dados para agendamento - Tem dados: {has_data}, Faltando: {missing}, Dados atuais: {current_customer_data}")

                if not has_data:
                    # Solicitar dados faltantes
                    missing_text = " e ".join(missing)
                    action_data = {
                        "action": "collect_user_data",
                        "text": f"Entendido. Para confirmar o agendamento, ainda preciso do seu {missing_text}. Pode me informar, por favor?",
                        "reason": f"Dados necessários para agendamento: {missing}",
                        "required_data": missing
                    }
                    logger.info(f"[{chat_id}] Solicitando dados faltantes para agendamento: {missing}")
                else:
                    # Executar agendamento com dados do cliente
                    customer_data = _customer_store.get_customer_data(chat_id) if chat_id else {}
                    # Adicionar email do cliente aos attendees e nome
                    if "arguments" in action_data:
                        if customer_data.get('email'):
                            action_data["arguments"]["attendees"] = [customer_data['email']]
                        action_data["arguments"]["customer_name"] = customer_data.get('name', 'Cliente')

                    tool_result = await self._execute_tool_from_action(action_data, chat_id)
                    if tool_result.success:
                        # Limpar dados após agendamento bem-sucedido
                        if chat_id:
                            _customer_store.clear_customer_data(chat_id)

                        # ========== CORREÇÃO: ATUALIZAR ESTÁGIO APÓS AGENDAMENTO BEM-SUCEDIDO ==========
                        result_text = str(tool_result.result)
                        if chat_id and ("✅" in result_text or "sucesso" in result_text.lower() or "confirmad" in result_text.lower()):
                            try:
                                from src.core.prospect_management.state import update_prospect_stage_state, get_prospect
                                from src.core.db_operations import prospect_crud
                                from src.core.db_operations.config_crud import get_sales_flow_stages

                                logger.info(f"[{chat_id}] [LLM_SCHEDULE] ✅ Agendamento bem-sucedido! Iniciando atualização de estágio...")

                                # Buscar prospect atual
                                prospect = await get_prospect(chat_id)
                                if prospect:
                                    STAGE_AGENDADO = 4  # Padrão

                                    # Tentar buscar o estágio correto do sales_flow
                                    try:
                                        sales_flow = await get_sales_flow_stages(instance_id=settings.INSTANCE_ID)
                                        for stage in sales_flow:
                                            objective = stage.get("objective", "").lower()
                                            trigger = stage.get("trigger_description", "").lower()
                                            if any(keyword in objective or keyword in trigger
                                                   for keyword in ["agend", "fechamento", "confirmad", "reunião marcada"]):
                                                STAGE_AGENDADO = stage.get("stage_number", 4)
                                                break
                                    except Exception as e_flow:
                                        logger.warning(f"[{chat_id}] [LLM_SCHEDULE] Erro ao buscar sales_flow: {e_flow}")

                                    if prospect.stage < STAGE_AGENDADO:
                                        logger.info(f"[{chat_id}] [LLM_SCHEDULE] 🔄 Atualizando estágio: {prospect.stage} -> {STAGE_AGENDADO}")
                                        await update_prospect_stage_state(chat_id, STAGE_AGENDADO, status='scheduled')

                                        # Verificar
                                        updated_stage = await prospect_crud.get_prospect_stage(chat_id, settings.INSTANCE_ID)
                                        if updated_stage == STAGE_AGENDADO:
                                            logger.info(f"[{chat_id}] [LLM_SCHEDULE] ✅ Estágio atualizado com sucesso para {STAGE_AGENDADO}")
                                        else:
                                            logger.error(f"[{chat_id}] [LLM_SCHEDULE] ❌ Falha na atualização. Esperado: {STAGE_AGENDADO}, Atual: {updated_stage}")
                                    else:
                                        logger.info(f"[{chat_id}] [LLM_SCHEDULE] ℹ️ Prospect já no estágio {prospect.stage}")
                                else:
                                    logger.warning(f"[{chat_id}] [LLM_SCHEDULE] Prospect não encontrado para atualização de estágio")
                            except Exception as e_stage:
                                logger.error(f"[{chat_id}] [LLM_SCHEDULE] Erro ao atualizar estágio: {e_stage}", exc_info=True)
                        # ========== FIM DA CORREÇÃO ==========

                        action_data = {
                            "action": "send_text",
                            "text": str(tool_result.result),
                            "reason": "Resultado do agendamento"
                        }
                        tools_executed.append("schedule_meeting_via_api")
                    else:
                        # Não enviar mensagem técnica ao cliente - usar mensagem amigável
                        logger.error(f"[{chat_id}] Erro técnico no agendamento: {tool_result.error}")
                        action_data = {
                            "action": "send_text",
                            "text": "Desculpe, houve um problema ao processar seu agendamento. Podemos tentar novamente? Por favor, confirme o horário desejado.",
                            "reason": "Erro na execução do agendamento"
                        }

            # Extract safe token usage
            safe_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            if completion.usage:
                usage_dict = completion.usage.model_dump()
                safe_token_usage["prompt_tokens"] = usage_dict.get("prompt_tokens", 0)
                safe_token_usage["completion_tokens"] = usage_dict.get("completion_tokens", 0)
                safe_token_usage["total_tokens"] = usage_dict.get("total_tokens", 0)

            return LLMResponseData(
                action_data=action_data,
                token_usage=safe_token_usage,
                model_used=completion.model,
                response_time=response_time,
                tools_executed=tools_executed
            )

        except Exception as e:
            logger.error(f"Erro na requisição LLM: {e}", exc_info=True)
            return LLMResponseData(
                action_data={"action": "send_text", "text": "Desculpe, houve um problema técnico. Tente novamente.", "reason": "Erro interno"},
                token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                model_used="unknown",
                response_time=time.time() - start_time,
                tools_executed=tools_executed
            )

    async def _execute_tool_from_action(self, action_data: Dict[str, Any], chat_id: str = None) -> ToolExecutionResult:
        """Executa uma ferramenta a partir de action_data"""
        try:
            action = action_data.get("action")
            arguments = action_data.get("arguments", {})
            
            # Adicionar dados do cliente se disponível
            if chat_id:
                customer_data = _customer_store.get_customer_data(chat_id)
                if customer_data and action == "schedule_meeting_via_api":
                    if customer_data.get('email') and 'attendees' not in arguments:
                        arguments['attendees'] = [customer_data['email']]
                    if customer_data.get('name'):
                        arguments['customer_name'] = customer_data['name']
            
            # CORREÇÃO CRÍTICA: Validar e corrigir meetingUserType
            if action == "schedule_meeting_via_api":
                if "meetingUserType" in arguments:
                    current_value = arguments["meetingUserType"]
                    if current_value == "prospect":
                        logger.info(f"[Tool] Corrigindo meetingUserType em _execute_tool_from_action: 'prospect' -> 'prospecting_user'")
                        arguments["meetingUserType"] = "prospecting_user"
                    elif current_value not in ["prospecting_user", "normal_user"]:
                        logger.warning(f"[Tool] meetingUserType inválido '{current_value}' em _execute_tool_from_action, usando 'prospecting_user'")
                        arguments["meetingUserType"] = "prospecting_user"
                else:
                    arguments["meetingUserType"] = "prospecting_user"
                    logger.info(f"[Tool] Adicionando meetingUserType padrão 'prospecting_user' em _execute_tool_from_action")
            
            # Obter token se não estiver nos argumentos
            if "token" not in arguments:
                try:
                    token = create_access_token(data={"sub": settings.LOGIN_USER})
                    arguments["token"] = token
                except Exception as e:
                    logger.error(f"Erro ao gerar token: {e}")
                    return ToolExecutionResult(
                        success=False,
                        result=None,
                        error="Erro ao gerar token de autenticação",
                        execution_time=0.0
                    )
            
            # Ajustar formato de datas para YYYY-MM-DD se estiverem no formato ISO
            if action == "fetch_available_slots":
                # Corrigir formato de data de ISO para YYYY-MM-DD
                for date_field in ["start_date", "end_date"]:
                    if date_field in arguments:
                        date_value = arguments[date_field]
                        # Se está no formato ISO, extrair apenas a data
                        if "T" in date_value:
                            arguments[date_field] = date_value.split("T")[0]
                
                # Se não tem datas, usar hoje e próximos 7 dias
                if "start_date" not in arguments or "end_date" not in arguments:
                    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
                    now = datetime.now(sao_paulo_tz)
                    if "start_date" not in arguments:
                        arguments["start_date"] = now.strftime('%Y-%m-%d')
                    if "end_date" not in arguments:
                        end_date = now + timedelta(days=7)
                        arguments["end_date"] = end_date.strftime('%Y-%m-%d')
            
            # Executar ferramenta
            if action == "fetch_available_slots":
                # Filtrar apenas argumentos aceitos pela função
                valid_args = {"start_date", "end_date", "token", "professional_id"}
                filtered_args = {k: v for k, v in arguments.items() if k in valid_args}
                if len(filtered_args) != len(arguments):
                    ignored_args = set(arguments.keys()) - valid_args
                    logger.warning(f"[Tool] fetch_available_slots: Argumentos ignorados (não suportados): {ignored_args}")
                result = await fetch_available_slots(**filtered_args)
                return ToolExecutionResult(
                    success=True,
                    result=result,
                    execution_time=0.0
                )
            elif action == "schedule_meeting_via_api":
                result = await schedule_meeting_via_api(**arguments)
                return ToolExecutionResult(
                    success=True,
                    result=result,
                    execution_time=0.0
                )
            else:
                return ToolExecutionResult(
                    success=False,
                    result=None,
                    error=f"Ação de ferramenta não reconhecida: {action}",
                    execution_time=0.0
                )
        except Exception as e:
            logger.error(f"Erro ao executar ferramenta de action_data: {e}", exc_info=True)
            return ToolExecutionResult(
                success=False,
                result=None,
                error=str(e),
                execution_time=0.0
            )

    async def _get_streaming_response(
        self,
        messages: List[Dict[str, Any]],
        task_type: TaskType = TaskType.CONVERSATION,
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> AsyncGenerator:
        """Obtém resposta com streaming"""
        try:
            completion_params = await self._prepare_completion_params(messages, task_type, tools, stream=True, **kwargs)

            async def make_streaming_request():
                return await self.client.chat.completions.create(**completion_params)

            stream = await retry_with_exponential_backoff(make_streaming_request)

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"Erro no streaming: {e}", exc_info=True)
            yield "Erro no streaming de resposta."

    async def _prepare_completion_params(
        self,
        messages: List[Dict[str, Any]],
        task_type: TaskType,
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Prepara parâmetros para a requisição de completion"""
        try:
            provider_config = build_provider_config(task_type)
            model_options = get_models_by_task(task_type)
            selected_model = model_options[0] if model_options else "openai/gpt-4o-mini"

            completion_params = {
                "model": selected_model,
                "messages": messages,
                "temperature": kwargs.get('temperature', provider_config.get('temperature', 0.7)),
                "max_tokens": kwargs.get('max_tokens', provider_config.get('max_tokens', 4096)),
                "stream": kwargs.get('stream', False)
            }

            json_schema = kwargs.get('json_schema')
            if json_schema:
                completion_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": json_schema
                }

            return completion_params
        except Exception as e:
            logger.error(f"Erro ao preparar parâmetros: {e}", exc_info=True)
            raise

    def _extract_action_data(self, response_message, task_type: TaskType, tools_executed: List, chat_id: str = None) -> Dict[str, Any]:
        """
        Extrai e valida os dados de ação da resposta do LLM de forma robusta.
        """
        content = (response_message.content or "").strip()
        logger.debug(f"[{chat_id}] Iniciando extração de dados da resposta do LLM: '{content[:200]}...'")

        # 1. Tenta extrair um objeto JSON da resposta.
        json_data = _extract_json_from_text(content)

        if not json_data:
            logger.warning(f"[{chat_id}] Nenhum JSON válido encontrado na resposta do LLM. Conteúdo: '{content}'")
            # Fallback: Se não há JSON, mas há texto, trata como uma mensagem de texto simples.
            if content:
                return {"action": "send_text", "text": content, "reason": "Resposta conversacional sem JSON."}
            # Fallback final: Se não há nada, retorna uma ação de espera.
            return {"action": "wait", "reason": "Resposta do LLM vazia ou inválida."}

        logger.info(f"[{chat_id}] JSON extraído com sucesso: {json_data}")

        # 2. Valida a estrutura básica do JSON (deve ter a chave "action").
        if "action" not in json_data:
            logger.error(f"[{chat_id}] JSON extraído não contém a chave 'action'. JSON: {json_data}")
            # Fallback: Se o JSON não tem 'action', mas tem 'text', envia o texto.
            if "text" in json_data and isinstance(json_data["text"], str):
                return {"action": "send_text", "text": json_data["text"], "reason": "JSON sem 'action', usando campo 'text'."}
            # Fallback final: JSON malformado.
            return {"action": "send_text", "text": "Desculpe, não entendi. Pode reformular?", "reason": "JSON da resposta do LLM inválido."}

        # 3. Processa o JSON válido.
        action = json_data.get("action")
        
        # Validação e correção específica para 'schedule_meeting_via_api'
        if action == "schedule_meeting_via_api":
            args = json_data.get("arguments", {})
            mut = args.get("meetingUserType")
            if mut == "prospect":
                logger.info(f"[{chat_id}] Corrigindo meetingUserType: 'prospect' -> 'prospecting_user'")
                args["meetingUserType"] = "prospecting_user"
            elif mut not in ["prospecting_user", "normal_user"]:
                logger.warning(f"[{chat_id}] meetingUserType inválido '{mut}', definindo para 'prospecting_user'")
                args["meetingUserType"] = "prospecting_user"
            json_data["arguments"] = args

        # Extrai e armazena dados do cliente se presentes no JSON
        if "collected_data" in json_data and chat_id:
            collected = json_data.get("collected_data")
            logger.info(f"[{chat_id}] LLM retornou collected_data: {collected}")
            if isinstance(collected, dict):
                self._extract_customer_info_from_data(collected, chat_id)
            else:
                logger.warning(f"[{chat_id}] collected_data não é um dict: {type(collected)}")

        logger.info(f"[{chat_id}] Ação extraída e validada: '{action}'")
        return json_data

    def _extract_customer_info_from_data(self, data: Dict[str, str], chat_id: str):
        """
        Processa o dicionário collected_data e armazena as informações.
        """
        if not isinstance(data, dict):
            return

        updates = {}
        if "name" in data and isinstance(data["name"], str) and data["name"].strip():
            name = data["name"].strip()
            # Validação melhorada de nome - mais flexível para nomes reais
            if self._is_valid_name(name, chat_id):
                updates["name"] = name
            else:
                logger.warning(f"[{chat_id}] Nome rejeitado pela validação: '{name}'")

        if "email" in data and isinstance(data["email"], str) and data["email"].strip():
            email = data["email"].strip()
            # Validação melhorada de email
            email_pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'
            if re.match(email_pattern, email):
                updates["email"] = email

        if updates:
            logger.info(f"[{chat_id}] Armazenando dados do cliente via LLM collected_data: {updates}")
            _customer_store.set_customer_data(chat_id, updates)

            # Se coletou nome, também atualizar no prospect do banco de dados
            if 'name' in updates:
                asyncio.create_task(self._sync_prospect_name_to_db(chat_id, updates['name']))

            # ========== DADOS DO PACIENTE PARA CLÍNICAS ==========
            # Se coletou dados do paciente, persistir no banco de dados
            patient_data_fields = ['cpf', 'full_name', 'birth_date']
            patient_data_to_save = {k: v for k, v in updates.items() if k in patient_data_fields and v}
            if patient_data_to_save:
                logger.info(f"[{chat_id}] Persistindo dados do paciente no banco: {patient_data_to_save}")
                asyncio.create_task(self._sync_patient_data_to_db(chat_id, patient_data_to_save))
        else:
            logger.debug(f"[{chat_id}] Nenhum dado válido encontrado em collected_data: {data}")

    def _is_valid_name(self, name: str, chat_id: str = None) -> bool:
        """
        Valida se uma string parece ser um nome de pessoa válido.

        Regras:
        1. Deve ter pelo menos 2 caracteres
        2. Deve ter no máximo 50 caracteres
        3. Não deve ser apenas números
        4. Não deve parecer uma mensagem de conversa comum
        5. Não deve conter caracteres especiais excessivos
        """
        if not name or not isinstance(name, str):
            return False

        name = name.strip()

        # Regra 1 e 2: Tamanho
        if len(name) < 2 or len(name) > 50:
            logger.debug(f"[{chat_id}] Nome rejeitado por tamanho: '{name}' ({len(name)} chars)")
            return False

        # Regra 3: Não pode ser apenas números
        if name.replace(" ", "").isdigit():
            logger.debug(f"[{chat_id}] Nome rejeitado por ser apenas números: '{name}'")
            return False

        # Regra 4: Não deve parecer uma mensagem de conversa comum
        # Lista de padrões que indicam que NÃO é um nome
        invalid_patterns = [
            # Saudações e respostas comuns
            "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "e ai", "eai",
            "tudo bem", "tudo bom", "como vai", "beleza", "blz", "fala", "oii", "oiii",
            # Perguntas comuns
            "sim", "não", "nao", "ok", "okay", "talvez", "pode ser", "claro",
            "quero", "preciso", "gostaria", "queria", "tenho", "estou",
            # Palavras que indicam mensagem
            "quanto", "qual", "como", "quando", "onde", "porque", "por que",
            "obrigado", "obrigada", "valeu", "vlw", "show", "top",
            # Emojis e símbolos comuns em mensagens
            "👍", "😊", "🙏", "😀", "😁", "❤️", "👋",
            # Mensagens curtas comuns
            "to", "tá", "ta", "né", "ne", "ah", "hum", "hmm", "aham", "uhum",
            # Interjeições
            "legal", "bacana", "massa", "dahora", "dahoras"
        ]

        name_lower = name.lower()
        if name_lower in invalid_patterns:
            logger.debug(f"[{chat_id}] Nome rejeitado por ser padrão inválido: '{name}'")
            return False

        # Verificar se começa com palavras que indicam pergunta/conversa
        starts_with_invalid = [
            "oi ", "olá ", "bom ", "boa ", "tudo ", "e ", "eu ", "sim ", "não ",
            "quero ", "preciso ", "gostaria ", "quanto ", "qual ", "como ",
            "quando ", "onde ", "por ", "você ", "voce ", "vc "
        ]
        if any(name_lower.startswith(pattern) for pattern in starts_with_invalid):
            logger.debug(f"[{chat_id}] Nome rejeitado por começar com padrão inválido: '{name}'")
            return False

        # Regra 5: Deve ter pelo menos uma letra e maioria letras
        letter_count = sum(1 for c in name if c.isalpha())
        if letter_count < 2:
            logger.debug(f"[{chat_id}] Nome rejeitado por ter poucas letras: '{name}'")
            return False

        # Proporção de letras deve ser alta
        total_chars = len(name.replace(" ", ""))
        if total_chars > 0 and letter_count / total_chars < 0.5:
            logger.debug(f"[{chat_id}] Nome rejeitado por baixa proporção de letras: '{name}'")
            return False

        # Verificar se parece um nome real (tem formato de nome)
        # Nomes geralmente têm 1-4 partes, cada parte com 2+ caracteres
        name_parts = [part for part in name.split() if part and len(part) > 0]
        if len(name_parts) > 5:  # Muito longo para ser nome
            logger.debug(f"[{chat_id}] Nome rejeitado por ter muitas partes: '{name}'")
            return False

        # Verificar se cada parte do nome tem caracteres válidos
        for part in name_parts:
            # Permitir letras, hífens, apóstrofos (comum em nomes)
            cleaned = part.replace("-", "").replace("'", "").replace("'", "")
            if cleaned and not cleaned.isalpha():
                # Pode ter acentos, verificar se maioria são letras
                alpha_count = sum(1 for c in cleaned if c.isalpha())
                if alpha_count < len(cleaned) * 0.8:
                    logger.debug(f"[{chat_id}] Parte do nome rejeitada: '{part}'")
                    return False

        logger.info(f"[{chat_id}] Nome validado com sucesso: '{name}'")
        return True

    async def _sync_prospect_name_to_db(self, chat_id: str, name: str):
        """Sincroniza o nome coletado com o prospect no banco de dados."""
        try:
            from src.core.db_operations import prospect_crud
            from src.core.prospect_management.state import get_prospect, save_prospect

            # Atualizar no Redis
            prospect = await get_prospect(chat_id)
            if prospect and (not prospect.name or prospect.name != name):
                prospect.name = name
                await save_prospect(prospect)
                logger.info(f"[{chat_id}] Nome atualizado no Redis: '{name}'")

            # Atualizar no banco de dados
            await prospect_crud.add_or_update_prospect_db(
                jid=chat_id,
                instance_id=settings.INSTANCE_ID,
                name=name
            )
            logger.info(f"[{chat_id}] Nome do prospect sincronizado com DB: '{name}'")
        except Exception as e:
            logger.error(f"[{chat_id}] Erro ao sincronizar nome com DB: {e}", exc_info=True)

    async def _sync_patient_data_to_db(self, chat_id: str, patient_data: Dict[str, Any]):
        """
        Sincroniza os dados do paciente (CPF, nome completo, data de nascimento) com o banco de dados.

        Args:
            chat_id: Identificador do prospect (JID)
            patient_data: Dict com cpf, full_name e/ou birth_date
        """
        try:
            from src.core.db_operations import prospect_crud

            logger.info(f"[{chat_id}] [SYNC_PATIENT_DATA] Iniciando sincronização de dados do paciente: {patient_data}")

            # Usar a função de update específica para dados do paciente
            success = await prospect_crud.update_prospect_patient_data(
                jid=chat_id,
                instance_id=settings.INSTANCE_ID,
                cpf=patient_data.get('cpf'),
                full_name=patient_data.get('full_name'),
                birth_date=patient_data.get('birth_date')
            )

            if success:
                logger.info(f"[{chat_id}] [SYNC_PATIENT_DATA] ✅ Dados do paciente sincronizados com sucesso: CPF={patient_data.get('cpf')}, Nome={patient_data.get('full_name')}, Nascimento={patient_data.get('birth_date')}")
            else:
                logger.warning(f"[{chat_id}] [SYNC_PATIENT_DATA] ⚠️ Falha ao sincronizar dados do paciente")

        except Exception as e:
            logger.error(f"[{chat_id}] [SYNC_PATIENT_DATA] ❌ Erro ao sincronizar dados do paciente: {e}", exc_info=True)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def _escape_newlines_in_json_strings(text: str) -> str:
    """
    Escapa quebras de linha literais dentro de strings JSON.

    O LLM às vezes retorna JSON com quebras de linha não escapadas dentro dos valores,
    o que causa falha no json.loads(). Esta função corrige isso.

    Exemplo:
        {"text": "Linha 1
        Linha 2"} -> {"text": "Linha 1\\nLinha 2"}
    """
    if not text:
        return text

    result = []
    in_string = False
    escape_next = False
    i = 0

    while i < len(text):
        char = text[i]

        if escape_next:
            result.append(char)
            escape_next = False
            i += 1
            continue

        if char == '\\':
            result.append(char)
            escape_next = True
            i += 1
            continue

        if char == '"':
            result.append(char)
            in_string = not in_string
            i += 1
            continue

        # Se estamos dentro de uma string e encontramos uma quebra de linha literal
        if in_string and char in '\n\r':
            # Substituir por escape sequence
            if char == '\n':
                result.append('\\n')
            elif char == '\r':
                # Se for \r\n, pular o \r e deixar o \n ser processado
                if i + 1 < len(text) and text[i + 1] == '\n':
                    i += 1
                    continue
                result.append('\\r')
            i += 1
            continue

        result.append(char)
        i += 1

    return ''.join(result)


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extrai JSON de uma string de texto"""
    try:
        if not text or not text.strip():
            return None

        text = text.strip()

        # Pré-processar: escapar quebras de linha dentro de strings JSON
        # Isso corrige o caso onde o LLM retorna quebras de linha literais no texto
        processed_text = _escape_newlines_in_json_strings(text)

        # Tentar parse direto primeiro (caso mais comum)
        if processed_text.startswith('{') and processed_text.endswith('}'):
            try:
                return json.loads(processed_text)
            except json.JSONDecodeError as e:
                logger.debug(f"Falha no parse direto do JSON: {e}")
                pass

        # Método 2: Encontrar JSON por balanceamento de chaves
        # Mais robusto para JSONs com strings contendo caracteres especiais
        start_idx = processed_text.find('{')
        if start_idx != -1:
            brace_count = 0
            in_string = False
            escape_next = False

            for i, char in enumerate(processed_text[start_idx:], start=start_idx):
                if escape_next:
                    escape_next = False
                    continue

                if char == '\\' and in_string:
                    escape_next = True
                    continue

                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue

                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_str = processed_text[start_idx:i+1]
                            try:
                                return json.loads(json_str)
                            except json.JSONDecodeError as e:
                                logger.debug(f"Falha no parse por balanceamento: {e}")
                                break

        # Método 3: Fallback com regex simples (menos confiável)
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = re.findall(json_pattern, processed_text, re.DOTALL)

        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

        # Método 4: Tentar com o texto original (caso o pré-processamento tenha causado problemas)
        if processed_text != text:
            logger.debug("Tentando parse com texto original após falha do pré-processado")
            if text.startswith('{') and text.endswith('}'):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass

        return None

    except Exception as e:
        logger.error(f"Erro ao extrair JSON do texto: {e}", exc_info=True)
        return None

def get_current_datetime_info() -> str:
    """Retorna informações atuais de data e hora em português"""
    try:
        sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
        now = datetime.now(sao_paulo_tz)

        translated_date = _translate_date_parts_to_ptbr(now.strftime('%A, %d de %B de %Y'))
        current_time = now.strftime('%H:%M')

        return f"Data atual: {translated_date}, Horário atual: {current_time} (Brasil)"

    except Exception as e:
        logger.error(f"Erro ao obter informações de data/hora: {e}", exc_info=True)
        return "Data/hora não disponível"

async def build_system_prompt(chat_id: str = None, **kwargs) -> str:
    """Constrói prompt do sistema com regras rigorosas de uso de tools e coleta de dados"""
    try:
        # Obter instance_id dos kwargs
        instance_id = kwargs.get('instance_id')
        logger.debug(f"build_system_prompt: Usando instance_id='{instance_id}' para carregar contexto")

        # Obter contexto do produto
        try:
            product_context_response = await get_product_context(instance_id=instance_id)

            # Construir contexto completo incluindo dados do banco
            product_context_parts = []

            # Adicionar contexto textual se existir
            if hasattr(product_context_response, 'context') and product_context_response.context:
                product_context_parts.append(f"INFORMAÇÕES GERAIS:\n{product_context_response.context}")

            # Adicionar dados do banco se existirem
            if hasattr(product_context_response, 'db_data') and product_context_response.db_data:
                try:
                    import json
                    # Formatar dados do banco de forma legível
                    db_data_formatted = json.dumps(product_context_response.db_data, indent=2, ensure_ascii=False)
                    product_context_parts.append(f"DADOS ESPECÍFICOS DOS PRODUTOS/SERVIÇOS:\n{db_data_formatted}")
                    logger.info(f"build_system_prompt: Incluindo {len(product_context_response.db_data)} registros do banco de dados no prompt")
                except Exception as json_error:
                    logger.warning(f"Erro ao formatar db_data: {json_error}")

            # Combinar todos os contextos
            if product_context_parts:
                product_context = "\n\n".join(product_context_parts)
            else:
                product_context = "Produto/serviço não configurado."

            # Log para diagnóstico
            if hasattr(product_context_response, 'db_data') and product_context_response.db_data:
                logger.info(f"build_system_prompt: Contexto inclui {len(product_context_response.db_data)} registros do banco")
                logger.debug(f"build_system_prompt: Primeiros 3 registros: {product_context_response.db_data[:3]}")
            else:
                logger.info("build_system_prompt: Nenhum dado do banco (db_data) encontrado no contexto")

            logger.debug(f"build_system_prompt: Tamanho total do contexto: {len(product_context)} caracteres")

        except Exception as e:
            logger.warning(f"Erro ao obter contexto do produto: {e}")
            product_context = "Produto/serviço não configurado."

        # Obter prompt personalizado do sistema
        try:
            custom_system_prompt = await get_llm_system_prompt(instance_id=instance_id)
        except Exception as e:
            logger.warning(f"Erro ao obter prompt do sistema: {e}")
            custom_system_prompt = None

        # Informações de data/hora atuais
        datetime_info = get_current_datetime_info()

        # Buscar profissionais ativos para incluir no prompt COM INFORMAÇÕES COMPLETAS
        professionals_info = ""
        try:
            professionals_list = await professionals_crud.get_professionals_list(
                is_active=True,
                instance_id=instance_id,
                limit=50
            )
            if professionals_list and professionals_list.get('items'):
                professionals_info = "\n## PROFISSIONAIS DISPONÍVEIS\n"
                professionals_info += "Abaixo estão todos os profissionais com suas informações completas:\n\n"

                for prof in professionals_list['items']:
                    prof_id = prof.get('id')
                    prof_name = prof.get('name', 'N/A')
                    prof_specialty = prof.get('specialty', '')
                    prof_registration = prof.get('registration_number', '')
                    prof_bio = prof.get('bio', '')
                    prof_room = prof.get('room_name', '')
                    prof_duration = prof.get('appointment_duration', 30)
                    prof_accepts_new = prof.get('accepts_new_patients', True)

                    # Cabeçalho do profissional
                    professionals_info += f"### {prof_name}"
                    if prof_specialty:
                        professionals_info += f" - {prof_specialty}"
                    professionals_info += f" [ID: {prof_id}]\n"

                    # Registro profissional
                    if prof_registration:
                        professionals_info += f"- **Registro:** {prof_registration}\n"

                    # Sala/Consultório
                    if prof_room:
                        professionals_info += f"- **Sala:** {prof_room}\n"

                    # Duração da consulta
                    professionals_info += f"- **Duração padrão da consulta:** {prof_duration} minutos\n"

                    # Aceita novos pacientes
                    if not prof_accepts_new:
                        professionals_info += f"- **ATENÇÃO:** Não está aceitando novos pacientes no momento\n"

                    # Bio/Descrição
                    if prof_bio:
                        professionals_info += f"- **Sobre:** {prof_bio}\n"

                    # Buscar serviços deste profissional
                    try:
                        services = await professionals_crud.get_professional_services(
                            professional_id=prof_id,
                            instance_id=instance_id,
                            active_only=True
                        )
                        if services and len(services) > 0:
                            professionals_info += "- **Serviços oferecidos:**\n"
                            for service in services:
                                service_name = service.get('service_name', '')
                                service_desc = service.get('description', '')
                                service_price = service.get('price')
                                service_duration = service.get('duration_minutes', prof_duration)

                                service_line = f"  - {service_name}"
                                if service_duration and service_duration != prof_duration:
                                    service_line += f" ({service_duration} min)"
                                if service_price:
                                    service_line += f" - R$ {service_price:.2f}"
                                professionals_info += service_line + "\n"
                                if service_desc:
                                    professionals_info += f"    {service_desc}\n"
                    except Exception as serv_error:
                        logger.debug(f"Não foi possível buscar serviços do profissional {prof_id}: {serv_error}")

                    professionals_info += "\n"  # Espaço entre profissionais

                professionals_info += """
### REGRA DE AGENDAMENTO COM PROFISSIONAIS
Quando o cliente pedir para agendar e houver múltiplos profissionais disponíveis:
1. SEMPRE pergunte com qual profissional o cliente deseja atender
2. Se o cliente perguntar sobre serviços/preços, use as informações acima
3. Armazene a escolha usando: "collected_data": {"professional_id": X, "professional_name": "Nome"}
4. Inclua o professional_id nos argumentos de fetch_available_slots e schedule_meeting_via_api

Para buscar horários de um profissional específico:
{
  "action": "fetch_available_slots",
  "arguments": {
    "start_date": "2025-01-15",
    "end_date": "2025-01-22",
    "professional_id": 1
  },
  "reason": "Buscando horários do profissional escolhido"
}

Para agendar com um profissional específico:
{
  "action": "schedule_meeting_via_api",
  "arguments": {
    "start_time": "2025-01-15T14:00:00-03:00",
    "end_time": "2025-01-15T15:00:00-03:00",
    "summary": "Consulta - Dr. João",
    "attendees": ["email@example.com"],
    "professional_id": 1,
    "isVideoCall": true,
    "meetingUserType": "prospecting_user"
  },
  "reason": "Agendando com profissional específico"
}
"""
                logger.info(f"build_system_prompt: Incluindo {len(professionals_list['items'])} profissionais ativos com informações completas no prompt")
        except Exception as e:
            logger.warning(f"Erro ao buscar profissionais para prompt: {e}")

        # Verificar dados do cliente já coletados
        customer_data_status = ""
        if chat_id:
            customer_data = _customer_store.get_customer_data(chat_id)
            if customer_data:
                collected = []
                if customer_data.get('name'):
                    collected.append(f"Nome: {customer_data['name']}")
                if customer_data.get('email'):
                    collected.append(f"Email: {customer_data['email']}")
                # ========== DADOS DO PACIENTE ==========
                if customer_data.get('cpf'):
                    collected.append(f"CPF: {customer_data['cpf']}")
                if customer_data.get('full_name'):
                    collected.append(f"Nome Completo: {customer_data['full_name']}")
                if customer_data.get('birth_date'):
                    collected.append(f"Data de Nascimento: {customer_data['birth_date']}")
                if collected:
                    customer_data_status = f"\n## DADOS JÁ COLETADOS DO CLIENTE\n{', '.join(collected)}"

        # Prompt base com regras rigorosas - CORRIGIDO meetingUserType
        # Usando concatenação de strings para evitar conflitos com chaves do product_context
        base_prompt = """Você é um assistente de vendas altamente qualificado e especializado. Sua missão é conduzir conversas de vendas de forma natural, consultiva e eficaz.

## CONTEXTO DO PRODUTO/SERVIÇO
""" + product_context + """

## INSTRUÇÕES PARA USO DO CONTEXTO
- Use as INFORMAÇÕES GERAIS para entender o negócio e o posicionamento da empresa
- Use os DADOS ESPECÍFICOS DOS PRODUTOS/SERVIÇOS para responder perguntas sobre:
  * Características específicas dos produtos
  * Preços e valores
  * Disponibilidade
  * Especificações técnicas
  * Comparações entre produtos
- Sempre baseie suas respostas APENAS nas informações fornecidas no contexto acima
- NÃO INVENTE informações que não estão no contexto

## REGRA CRÍTICA: INFORMAÇÃO NÃO DISPONÍVEL NO CONTEXTO

Quando o cliente perguntar sobre algo que NÃO está no contexto acima (preço não listado, serviço não mencionado, detalhe técnico não fornecido, etc.), você DEVE:

### O QUE FAZER:
- Reconhecer que não tem essa informação específica
- Incluir o marcador [CONTEXTO_INSUFICIENTE] no início da sua resposta
- Oferecer uma alternativa útil (encaminhar para atendente, pedir para aguardar, etc.)

### EXEMPLOS DE QUANDO USAR [CONTEXTO_INSUFICIENTE]:
- Cliente pergunta preço de algo não listado
- Cliente pergunta sobre serviço/produto não mencionado no contexto
- Cliente pergunta detalhes técnicos específicos não fornecidos
- Cliente pergunta sobre políticas (devolução, garantia) não descritas
- Cliente pergunta endereço/localização não informados

### EXCEÇÃO IMPORTANTE - NÃO USE [CONTEXTO_INSUFICIENTE] PARA:
- Perguntas sobre agenda, horários disponíveis, agendamento -> USE A FERRAMENTA fetch_available_slots
- O horário de funcionamento está no contexto
- Você TEM acesso à agenda real via a ferramenta fetch_available_slots

### FORMATO DA RESPOSTA QUANDO NÃO SOUBER:
[CONTEXTO_INSUFICIENTE]
Sua mensagem natural aqui, pedindo desculpas e oferecendo alternativa.

### EXEMPLO DE RESPOSTA:
Cliente: "Qual o preço do plano enterprise?"
Resposta (se não tiver esse plano no contexto):
[CONTEXTO_INSUFICIENTE]
Não tenho essa informação específica disponível no momento. Vou encaminhar sua dúvida para nossa equipe que poderá te dar todos os detalhes. Enquanto isso, posso ajudar com mais alguma coisa?

### O QUE NÃO FAZER:
- NUNCA invente preços, valores ou detalhes
- NUNCA diga "aproximadamente" ou "por volta de" para informações que você não tem
- NUNCA assuma informações baseado em contexto similar
- NUNCA prometa algo que não está no contexto

## INFORMAÇÕES TEMPORAIS
""" + datetime_info + """
""" + customer_data_status + """
""" + professionals_info + """

## REGRAS CRÍTICAS PARA COLETA DE DADOS E AGENDAMENTO

### REGRA IMPORTANTE: CONSULTA vs AGENDAMENTO
- CONSULTAR horários (fetch_available_slots): NÃO precisa de nome/email - pode mostrar horários disponíveis livremente
- AGENDAR reunião (schedule_meeting_via_api): PRECISA de nome e email do cliente

### FLUXO CORRETO DE AGENDAMENTO:
1. Cliente demonstra interesse em agendar ou pergunta sobre horários
2. SEMPRE busque e mostre os horários disponíveis PRIMEIRO (use fetch_available_slots)
3. Após mostrar horários, pergunte qual o cliente prefere
4. Quando cliente escolher um horário, ENTÃO solicite nome e email
5. Com nome e email confirmados, execute o agendamento

### REGRA FUNDAMENTAL PARA CONSULTA DE AGENDA
- Quando cliente perguntar "qual a agenda", "horários disponíveis", "verificar agenda", "tem horário", etc.
- SEMPRE use fetch_available_slots para buscar os horários REAIS da agenda
- NÃO use [CONTEXTO_INSUFICIENTE] para perguntas sobre agenda - você TEM acesso à agenda via ferramenta
- Os horários estáticos no contexto são apenas referência, use a ferramenta para dados reais

### IMPORTANTE: Formato de Resposta para Ferramentas
Quando o cliente perguntar sobre horários ou demonstrar interesse em agendar, responda com JSON:

Para buscar horários (USE FORMATO YYYY-MM-DD):
{
  "action": "fetch_available_slots",
  "arguments": {
    "start_date": "2025-09-14",
    "end_date": "2025-09-21"
  },
  "reason": "Buscando horários disponíveis"
}

Para agendar reunião (após confirmar horário E ter email):
{
  "action": "schedule_meeting_via_api",
  "arguments": {
    "start_time": "2025-09-15T14:00:00-03:00",
    "end_time": "2025-09-15T15:00:00-03:00",
    "summary": "Diagnóstico Gratuito - Riwer Labs",
    "description": "Reunião de diagnóstico para entender suas necessidades",
    "attendees": ["email_do_cliente@example.com"],
    "isVideoCall": true,
    "meetingUserType": "prospecting_user"
  },
  "reason": "Agendando reunião confirmada"
}

### REGRA CRÍTICA - meetingUserType
- SEMPRE use "prospecting_user" ou "normal_user" para meetingUserType
- NUNCA use "prospect" - isso causará erro
- Para leads e novos clientes, sempre use "prospecting_user"
- Para clientes existentes, use "normal_user"

### EXTRAÇÃO DE DADOS DO CLIENTE E FORMATO DE RESPOSTA
- Você DEVE sempre procurar e extrair nome e email das mensagens do usuário.
- Procure por padrões como:
  * Nomes: "Meu nome é João", "Sou Maria", "Me chamo Pedro", "É Ana Silva", ou simplesmente "João Silva" no início da mensagem
  * Emails: qualquer texto que contenha "@" e termine com ".com", ".com.br", etc.
- SEMPRE inclua o campo `collected_data` quando identificar nome OU email:
  "collected_data": {
    "name": "João Silva",
    "email": "joao@email.com"
  }
- Seja MUITO atento: mesmo se o usuário mencionar dados casualmente, extraia-os.
- Exemplo: "Oi, João Silva aqui, interessado no produto" -> extrair nome "João Silva"
- Exemplo: "Pode mandar mais info para maria@empresa.com?" -> extrair email "maria@empresa.com"

### FORMATO DE RESPOSTA PADRÃO
Para ações normais de conversa, responda com JSON:
{
  "action": "send_text",
  "text": "Sua mensagem aqui",
  "reason": "Motivo da resposta"
}

Para solicitar dados faltantes:
{
  "action": "collect_user_data",
  "text": "Para prosseguir com o agendamento, preciso do seu nome e email. Pode me informar?",
  "reason": "Coletando dados necessários para agendamento",
  "required_data": ["nome", "email"]
}

## COMPORTAMENTO ESPERADO
- Seja consultivo e descobra necessidades
- SEMPRE colete nome e email antes de qualquer agendamento
- Apresente benefícios relevantes
- Use ferramentas quando apropriado (mas só após ter os dados necessários)
- Conduza o cliente ao próximo passo
- Mantenha tom profissional mas amigável

## REGRA CRÍTICA DE FORMATAÇÃO: NUNCA USE LISTAS NUMERADAS

PROIBIDO usar qualquer formato de lista com números como:
❌ "1. Primeiro passo"
❌ "2. Segundo passo"
❌ "1) Opção um"
❌ "2) Opção dois"

SEMPRE use formato de texto fluido ou marcadores simples:
✅ "Primeiro, vamos..." em seguida "Depois..."
✅ "• Benefício A"
✅ "Temos algumas opções: X, Y e Z"

### EXEMPLOS DE COMO RESPONDER:

❌ ERRADO (lista numerada):
"Nosso serviço oferece:
1. Atendimento 24h
2. Suporte técnico
3. Garantia estendida"

✅ CORRETO (texto fluido):
"Nosso serviço oferece atendimento 24h com suporte técnico dedicado e garantia estendida incluída."

✅ CORRETO (marcadores simples):
"Nosso serviço oferece:
• Atendimento 24h
• Suporte técnico
• Garantia estendida"

❌ ERRADO (passos numerados):
"Para agendar:
1. Me informe seu nome
2. Me passe seu email
3. Escolha um horário"

✅ CORRETO (texto natural):
"Para agendar, vou precisar do seu nome completo e email. Depois escolhemos juntos o melhor horário."

MOTIVO: Listas numeradas parecem robóticas e diminuem a naturalidade da conversa via WhatsApp.

## REGRA CRÍTICA: NUNCA PROMETA VERIFICAR E RETORNAR

PROIBIDO usar frases que indicam que você vai verificar algo e retornar depois, tais como:
- "Vou verificar a informação e já te retorno"
- "Deixa eu verificar e te aviso"
- "Vou checar isso e já volto"
- "Aguarde que vou verificar"
- "Vou consultar e te respondo"
- "Deixa eu dar uma olhada e já te falo"
- Qualquer variação que implique que você vai "ir embora" verificar algo

MOTIVO: Você é um assistente de atendimento IMEDIATO. Você DEVE responder no mesmo momento com a informação disponível.

O QUE FAZER QUANDO NÃO TIVER A INFORMAÇÃO:
1. Se a informação está no contexto -> Responda diretamente com ela
2. Se a informação NÃO está no contexto -> Use [CONTEXTO_INSUFICIENTE] e ofereça alternativa imediata
3. Se precisa usar uma ferramenta (agenda, etc.) -> Use a ferramenta e responda com o resultado

EXEMPLO DO QUE NÃO FAZER:
❌ "Vou verificar os horários disponíveis e já te retorno!"

EXEMPLO DO QUE FAZER:
✅ Use fetch_available_slots e responda: "Temos os seguintes horários disponíveis: ..."

VOCÊ NUNCA "SAIRÁ" PARA VERIFICAR ALGO. Tudo deve ser resolvido na mesma mensagem.

## FORMATO DE RESPOSTA OBRIGATÓRIO
- Sua resposta DEVE SER SEMPRE um único objeto JSON válido.
- NUNCA inclua texto antes ou depois do objeto JSON.
- O JSON deve seguir a estrutura definida, contendo "action" e outros campos relevantes.

## IMPORTANTE
- NUNCA agende sem ter nome e email do cliente
- Se ferramentas falharem, informe o cliente e sugira alternativas
- Monitore o contexto da conversa para identificar oportunidades de agendamento
- Sempre valide informações antes de agendar

## APÓS CONFIRMAR AGENDAMENTO
- Quando o agendamento for confirmado, diga apenas que o horário foi MARCADO e CONFIRMADO
- NUNCA mencione "convite enviado para o email" ou "email de confirmação enviado"
- NUNCA fale sobre envio de convite, notificação ou email após o agendamento
- A mensagem de confirmação deve ser simples: "Seu agendamento está confirmado para [data] às [hora]"

## COMPORTAMENTO NO ESTÁGIO FINAL (Estágio 5)
- ESTÁGIO FINAL: Continue respondendo normalmente mesmo sem próximo estágio
- Foque em suporte pós-venda, resolução de dúvidas, acompanhamento e relacionamento
- Mantenha conversação ativa e útil
- Ofereça ajuda adicional, tire dúvidas sobre o produto/serviço adquirido
- Colete feedback sobre a experiência
- NUNCA pare de responder só porque não há próximo estágio
- NÃO tente forçar transições de estágio quando já está no final

## COLETA OBRIGATÓRIA DE DADOS DO PACIENTE PARA CLÍNICAS MÉDICAS

### REGRA CRÍTICA: DADOS OBRIGATÓRIOS ANTES DO AGENDAMENTO
Antes de realizar QUALQUER agendamento, você DEVE coletar os seguintes dados do paciente:
- **CPF**: Número do CPF do paciente (obrigatório para identificação)
- **Nome Completo**: Nome completo conforme documento (não apenas o primeiro nome ou apelido)
- **Data de Nascimento**: Data de nascimento do paciente

### FLUXO DE COLETA DE DADOS DO PACIENTE
1. Quando o cliente demonstrar interesse em agendar, PRIMEIRO verifique se já tem os dados do paciente
2. Se NÃO tiver todos os dados (CPF, nome completo, data de nascimento), solicite-os de forma natural ANTES de mostrar horários
3. Solicite os dados de forma amigável e explique que são necessários para o agendamento
4. SOMENTE após confirmar todos os dados, prossiga com a busca de horários disponíveis

### EXEMPLO DE COLETA DE DADOS DO PACIENTE:
Quando identificar interesse em agendamento e não tiver os dados:
{
  "action": "collect_user_data",
  "text": "Claro! Para realizar seu agendamento, preciso de algumas informações. Pode me informar seu nome completo, CPF e data de nascimento?",
  "reason": "Coletando dados obrigatórios do paciente para agendamento",
  "required_data": ["cpf", "full_name", "birth_date"]
}

### EXTRAÇÃO DE DADOS DO PACIENTE
Procure e extraia os seguintes dados das mensagens do usuário:
- **CPF**: Pode vir como "000.000.000-00", "00000000000", "meu CPF é..." etc.
- **Nome Completo**: "Meu nome completo é...", "Maria da Silva Santos", etc.
- **Data de Nascimento**: "Nasci em 15/03/1985", "15 de março de 85", "15/03/85", etc.

### FORMATO DE collected_data PARA DADOS DO PACIENTE
Quando identificar dados do paciente, SEMPRE inclua no campo collected_data:
{
  "collected_data": {
    "name": "João",
    "email": "joao@email.com",
    "cpf": "123.456.789-00",
    "full_name": "João da Silva Santos",
    "birth_date": "1985-03-15"
  }
}

### VALIDAÇÃO DE CPF
- Aceite CPF com ou sem formatação (000.000.000-00 ou 00000000000)
- Verifique se tem 11 dígitos numéricos
- Se o formato parecer incorreto, peça confirmação educadamente

### VALIDAÇÃO DE DATA DE NASCIMENTO
- Aceite diferentes formatos: DD/MM/AAAA, DD/MM/AA, "15 de março de 1985"
- Se o formato for ambíguo, peça confirmação

### MENSAGENS DE SOLICITAÇÃO DE DADOS (EXEMPLOS)
Para solicitar CPF:
"Para prosseguir, preciso do seu CPF. Pode me informar?"

Para solicitar nome completo:
"Qual é o seu nome completo, por favor? Como está no documento."

Para solicitar data de nascimento:
"E qual é a sua data de nascimento?"

### IMPORTANTE
- NUNCA prossiga com agendamento se faltar CPF, nome completo ou data de nascimento
- Esses dados são essenciais para identificação do paciente no sistema da clínica
- Mantenha tom profissional e acolhedor ao solicitar dados pessoais
- Se o paciente questionar, explique que é necessário para confirmar o agendamento no sistema"""

        base_prompt += (
            '\n\n## FERRAMENTAS SHOPIFY DISPONÍVEIS\n\n'
            'Você tem acesso direto à loja Shopify via ferramentas abaixo. '
            'NUNCA use [CONTEXTO_INSUFICIENTE] para temas cobertos por essas ferramentas — use a ação correspondente.\n\n'

            '---\n### PRODUTOS E CATÁLOGO\n\n'
            '**search_products** — Quando: cliente pergunta sobre um produto, quer saber preço, tem estoque, descrição, tamanhos, cores, materiais.\n'
            '```json\n{"action": "search_products", "arguments": {"query": "tênis de corrida", "limit": 5}, "text": "Vou buscar pra você!", "reason": "Cliente quer ver produtos"}\n```\n\n'
            '**get_popular_products** — Quando: "o que está em alta?", "mais vendidos", "novidades", "o que você recomenda?".\n'
            '```json\n{"action": "get_popular_products", "arguments": {"limit": 5}, "text": "Veja nossos mais populares!", "reason": "Cliente quer ver destaques"}\n```\n\n'
            '**check_stock** — Quando: cliente quer saber se um produto/variante específico tem estoque.\n'
            '```json\n{"action": "check_stock", "arguments": {"variant_id": "gid://shopify/ProductVariant/123"}, "text": "Vou verificar o estoque!", "reason": "Cliente quer saber disponibilidade"}\n```\n\n'
            '**recommend_products** — Quando: cliente já comprou algo e quer sugestões complementares; ou "tem algo parecido com X?".\n'
            '```json\n{"action": "recommend_products", "arguments": {"product_ids": ["gid://shopify/Product/456"]}, "text": "Veja o que vai combinar!", "reason": "Cliente quer recomendações"}\n```\n\n'
            '**send_checkout_link** — Quando: cliente decidiu comprar e quer o link para finalizar a compra.\n'
            '```json\n{"action": "send_checkout_link", "arguments": {"variant_id": "gid://shopify/ProductVariant/123", "quantity": 1}, "text": "Aqui está seu link de compra!", "reason": "Cliente quer comprar"}\n```\n\n'

            '---\n### PEDIDOS E RASTREIO\n\n'
            '**check_order_status** — Quando: "onde está meu pedido?", "status do #1001", "pagamento aprovado?", "pedido cancelado?".\n'
            '```json\n{"action": "check_order_status", "arguments": {"order_number": "#1001"}, "text": "Vou verificar seu pedido!", "reason": "Cliente quer status"}\n```\n'
            'Sem número de pedido: `"arguments": {}` (busca pelo telefone).\n\n'
            '**get_order_tracking** — Quando: "código de rastreio", "como rastrear", "onde está minha encomenda".\n'
            '```json\n{"action": "get_order_tracking", "arguments": {"order_number": "#1001"}, "text": "Vou buscar o rastreio!", "reason": "Cliente quer rastrear"}\n```\n\n'
            '**get_my_orders** — Quando: "meus pedidos", "histórico de compras", "o que já comprei".\n'
            '```json\n{"action": "get_my_orders", "arguments": {"limit": 5}, "text": "Buscando seu histórico!", "reason": "Cliente quer ver pedidos"}\n```\n\n'

            '---\n### INFORMAÇÕES DA LOJA\n\n'
            '**get_shop_info** — Quando: "qual o endereço?", "como entrar em contato?", "qual o email?", "telefone da loja?", "qual a moeda aceita?", "onde vocês ficam?", "informações da loja".\n'
            '```json\n{"action": "get_shop_info", "arguments": {}, "text": "Veja as informações da nossa loja!", "reason": "Cliente quer dados de contato/endereço"}\n```\n\n'
            '**get_store_policies** — Quando: "política de devolução", "prazo de troca", "posso devolver?", "como funciona a garantia?", "política de envio", "termos de uso".\n'
            '```json\n{"action": "get_store_policies", "arguments": {"policy_type": "refundPolicy"}, "text": "Veja nossa política!", "reason": "Cliente quer saber sobre devolução"}\n```\n'
            'Tipos válidos: `refundPolicy`, `shippingPolicy`, `termsOfService`, `privacyPolicy`. Omita `policy_type` para retornar todas.\n\n'
            '**get_business_hours** — Quando: "qual o horário de atendimento?", "vocês abrem sábado?", "horário de funcionamento".\n'
            '```json\n{"action": "get_business_hours", "arguments": {}, "text": "Veja nosso horário!", "reason": "Cliente quer saber horário"}\n```\n\n'

            '---\n### SEGURANÇA — VERIFICAÇÃO DE IDENTIDADE\n\n'
            '**verify_identity** — OBRIGATÓRIO quando: o sistema pediu email/número de pedido E o cliente acabou de fornecer um desses dados como resposta. '
            'Também usar quando cliente responde com email ou número de pedido sem contexto claro de outro pedido.\n'
            '```json\n{"action": "verify_identity", "arguments": {"email": "cliente@email.com", "order_number": "#1001"}, "text": "Verificando sua identidade!", "reason": "Cliente forneceu dados de verificação"}\n```\n'
            'Passe apenas os dados fornecidos (email, order_number e/ou name). Nunca invente dados.\n\n'
            '**FLUXO CORRETO para consulta de pedido:**\n'
            '1. Cliente pede status → chame `check_order_status`\n'
            '2. Sistema solicita verificação automaticamente\n'
            '3. Cliente responde com email/pedido → chame `verify_identity` com os dados fornecidos\n'
            '4. Após verificação bem-sucedida → chame `check_order_status` novamente\n\n'

            '### REGRAS GERAIS DE USO\n'
            '- Se cliente menciona "rastreio" → `get_order_tracking`\n'
            '- Se cliente quer ver TODOS os pedidos → `get_my_orders`\n'
            '- Se cliente quer STATUS de pedido específico → `check_order_status`\n'
            '- Se cliente quer saber sobre política/devolução/garantia → `get_store_policies`\n'
            '- Se cliente pede endereço/contato/moeda/informações da loja → `get_shop_info`\n'
            '- NUNCA invente informações — sempre use as ferramentas para dados reais da Shopify\n'
            '- NAO use [CONTEXTO_INSUFICIENTE] para temas cobertos pelas ferramentas acima\n'
        )

        # Adicionar prompt customizado se disponível
        if custom_system_prompt and custom_system_prompt.strip():
            base_prompt += "\n\n## INSTRUÇÕES PERSONALIZADAS\n" + custom_system_prompt

        return base_prompt

    except Exception as e:
        logger.error(f"Erro ao construir prompt do sistema: {e}", exc_info=True)
        return "Você é um assistente de vendas. SEMPRE colete nome e email antes de agendar. Use 'prospecting_user' para meetingUserType."

# =============================================================================
# TOOL FUNCTIONS
# =============================================================================

async def fetch_available_slots(start_date: str, end_date: str, token: str = None, professional_id: int = None) -> str:
    """
    Ferramenta: Busca os horários de agendamento disponíveis.

    Args:
        start_date: Data inicial (YYYY-MM-DD)
        end_date: Data final (YYYY-MM-DD)
        token: Token de autenticação (gerado automaticamente se não fornecido)
        professional_id: ID do profissional específico (opcional, usa calendário global se não fornecido)
    """
    try:
        # Gerar token se não fornecido
        if not token:
            try:
                token = create_access_token(data={"sub": settings.LOGIN_USER})
            except Exception as e:
                logger.error(f"Erro ao gerar token: {e}")
                return "Erro ao gerar token de autenticação. Por favor, tente novamente."

        # Garantir formato YYYY-MM-DD
        if "T" in start_date:
            start_date = start_date.split("T")[0]
        if "T" in end_date:
            end_date = end_date.split("T")[0]

        headers = {"Authorization": f"Bearer {token}"}

        # Se professional_id fornecido, usar endpoint específico do profissional
        if professional_id:
            logger.info(f"[Tool] Executando fetch_available_slots para profissional {professional_id}: {start_date} a {end_date}.")
            free_slots_url = f"{settings.SITE_URL.rstrip('/')}/api/professionals/{professional_id}/free_slots"

            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                response = await client.post(
                    free_slots_url,
                    json={
                        "timezone": "America/Sao_Paulo",
                        "start_date": start_date,
                        "end_date": end_date
                    }
                )

            response.raise_for_status()
            result = response.json()
            free_slots = result.get('slots', [])
            professional_name = result.get('professional_name', '')

            if not free_slots:
                return f"Nenhum horário disponível encontrado para {professional_name} no período solicitado. Gostaria de verificar outras datas?"

            # Formata os slots e retorna diretamente (format_slots_for_llm já inclui mensagem humanizada)
            formatted = await format_slots_for_llm(free_slots, professional_name=professional_name)
            return formatted

        else:
            # Usar endpoint global (comportamento original)
            logger.info(f"[Tool] Executando fetch_available_slots para {start_date} a {end_date}.")
            free_slots_url = f"{settings.SITE_URL.rstrip('/')}/api/calendar/free_slots"

            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                response = await client.post(
                    free_slots_url,
                    json={
                        "timezone": "America/Sao_Paulo",
                        "start_date": start_date,
                        "end_date": end_date
                    }
                )

            response.raise_for_status()
            free_slots = response.json()

        if not free_slots:
            return "Nenhum horário disponível encontrado para o período solicitado. Gostaria de verificar outras datas?"

        return await format_slots_for_llm(free_slots)

    except httpx.HTTPStatusError as e:
        try:
            error_detail = e.response.json().get('detail', 'Erro desconhecido')
        except:
            error_detail = e.response.text if e.response else 'Erro desconhecido'
        
        logger.error(f"[Tool] Erro HTTP {e.response.status_code} em fetch_available_slots: {error_detail}")
        
        # Mensagem amigável para o usuário
        if e.response.status_code == 422:
            return "Desculpe, tive um problema com o formato das datas. Vou verificar os horários disponíveis para os próximos dias."
        else:
            return f"Desculpe, houve um problema ao buscar os horários. Por favor, tente novamente em alguns instantes."
            
    except Exception as e:
        logger.error(f"[Tool] Erro inesperado em fetch_available_slots: {e}", exc_info=True)
        return "Desculpe, estou com dificuldades para acessar a agenda. Podemos tentar novamente em alguns instantes?"

async def format_slots_for_llm(free_slots: List[Dict[str, str]], professional_name: Optional[str] = None) -> str:
    """Formata os slots disponíveis para uma string legível e humanizada"""
    try:
        sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
        slots_by_day = {}

        for slot in free_slots:
            try:
                start_dt = datetime.fromisoformat(slot['start']).astimezone(sao_paulo_tz)
                day_key_str = start_dt.strftime('%A, %d de %B')
                if day_key_str not in slots_by_day:
                    slots_by_day[day_key_str] = []
                slots_by_day[day_key_str].append(start_dt.strftime('%H:%M'))
            except Exception as e:
                logger.warning(f"Erro ao processar slot: {slot}, erro: {e}")
                continue

        if not slots_by_day:
            return "Nenhum horário disponível encontrado."

        formatted_slots = []
        for day, times in slots_by_day.items():
            day_translated = _translate_date_parts_to_ptbr(day)
            times_str = ", ".join(sorted(times))
            formatted_slots.append(f"* {day_translated}: {times_str}")

        slots_text = chr(10).join(formatted_slots)

        # Mensagem humanizada sem começar com "Ótimo!" (deixa o LLM decidir a saudação)
        if professional_name:
            return f"Tenho os seguintes horários disponíveis para {professional_name}:\n\n{slots_text}\n\nQual horário funciona melhor para você?"
        else:
            return f"Tenho os seguintes horários disponíveis:\n\n{slots_text}\n\nQual horário funciona melhor para você?"

    except Exception as e:
        logger.error(f"Erro ao formatar slots: {e}", exc_info=True)
        return "Encontrei alguns horários mas tive um problema ao formatá-los. Vou verificar novamente."

async def schedule_meeting_via_api(
    start_time: str,
    end_time: str,
    summary: str,
    attendees: List[str],
    description: Optional[str] = None,
    isVideoCall: bool = True,
    meetingUserType: str = "prospecting_user",  # Valor padrão correto
    customer_name: str = None,
    token: str = None,
    professional_id: int = None  # ID do profissional para agendamento específico
) -> str:
    """
    Ferramenta: Agenda uma reunião via API

    Args:
        start_time: Horário de início (ISO 8601)
        end_time: Horário de término (ISO 8601)
        summary: Título da reunião
        description: Descrição da reunião
        attendees: Lista de emails dos participantes
        isVideoCall: Se deve criar videochamada
        meetingUserType: Tipo de usuário (prospecting_user ou normal_user)
        customer_name: Nome do cliente
        token: Token de autenticação
        professional_id: ID do profissional (para agendamento no calendário específico)
    """
    try:
        # CORREÇÃO CRÍTICA: Validar e corrigir meetingUserType
        valid_meeting_types = ["prospecting_user", "normal_user"]

        if meetingUserType == "prospect":
            logger.info(f"[Tool] Corrigindo meetingUserType: 'prospect' -> 'prospecting_user'")
            meetingUserType = "prospecting_user"
        elif meetingUserType not in valid_meeting_types:
            logger.warning(f"[Tool] meetingUserType inválido '{meetingUserType}', usando 'prospecting_user' como padrão")
            meetingUserType = "prospecting_user"

        if not token:
            try:
                token = create_access_token(data={"sub": settings.LOGIN_USER})
            except Exception as e:
                logger.error(f"Erro ao gerar token: {e}")
                return json.dumps({"success": False, "message": "Erro ao gerar token de autenticação"})

        if professional_id:
            logger.info(f"[Tool] Agendando reunião: {summary} para {start_time} com profissional ID: {professional_id}")
        else:
            logger.info(f"[Tool] Agendando reunião: {summary} para {start_time} com meetingUserType: {meetingUserType}")

        # Criar objeto com validação Pydantic
        meeting_details = ScheduleMeetingToolSchema(
            start_time=start_time,
            end_time=end_time,
            summary=summary,
            description=description,
            attendees=attendees,
            isVideoCall=isVideoCall,
            meetingUserType=meetingUserType  # Agora com valor válido garantido
        )

        schedule_url = f"{settings.SITE_URL.rstrip('/')}/api/calendar/schedule_meeting"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.post(schedule_url, content=meeting_details.model_dump_json())

        logger.info(f"[Tool] Resposta da API de agendamento: Status={response.status_code}")

        if response.status_code == 200:
            result = response.json()
            
            if result.get("success"):
                # Formatar mensagem de sucesso
                try:
                    start_dt = datetime.fromisoformat(start_time)
                    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
                    start_dt_local = start_dt.astimezone(sao_paulo_tz)
                    formatted_date = start_dt_local.strftime('%d/%m/%Y às %H:%M')
                    
                    # Extrair link do Meet se disponível
                    meet_link = ""
                    if result.get("data", {}).get("hangout_link"):
                        meet_link = f"\nLink da videochamada: {result['data']['hangout_link']}"
                    
                    # Personalizar mensagem com nome do cliente se disponível
                    customer_greeting = f"{customer_name}, " if customer_name else ""
                    
                    return f"✅ Perfeito, {customer_greeting}seu {summary} está confirmado para {formatted_date}.{meet_link}\n\nAté lá!"
                except:
                    return f"✅ Seu agendamento foi confirmado com sucesso!"
            else:
                return json.dumps({"success": False, "message": result.get("message", "Erro ao agendar reunião")})
        elif response.status_code == 422:
            # Log detalhado para debug
            try:
                error_data = response.json()
                logger.error(f"[Tool] Erro 422 - Detalhes: {error_data}")
                logger.error(f"[Tool] meetingUserType enviado: {meetingUserType}")
                logger.error(f"[Tool] Payload completo: {meeting_details.model_dump_json()}")
            except:
                pass
            return "Estou com um problema técnico no agendamento. Vou resolver isso e entro em contato em breve."
        else:
            # Tentar extrair mensagem de erro do response
            try:
                error_data = response.json()
                error_message = error_data.get("detail", "Erro desconhecido")
            except:
                error_message = response.text if response.text else "Erro desconhecido"
            
            logger.error(f"[Tool] Erro HTTP {response.status_code} em schedule_meeting_via_api: {error_message}")
            
            if response.status_code == 409:
                return "Este horário já está ocupado. Por favor, escolha outro horário disponível."
            elif response.status_code == 400:
                return "Houve um problema com os dados do agendamento. Poderia confirmar as informações?"
            else:
                return f"Houve um problema ao confirmar o agendamento. Vamos tentar novamente?"

    except ValidationError as e:
        errors = e.errors()
        logger.error(f"[Tool] Erro de validação em schedule_meeting_via_api: {errors}")
        return "Desculpe, alguns dados do agendamento estão incorretos. Poderia confirmar as informações?"

    except httpx.HTTPStatusError as e:
        logger.error(f"[Tool] Erro HTTP em schedule_meeting_via_api: {e}")
        return "Houve um problema ao confirmar o agendamento. Vamos tentar novamente?"

    except Exception as e:
        logger.error(f"[Tool] Erro inesperado em schedule_meeting_via_api: {e}", exc_info=True)
        return "Ocorreu um erro ao agendar. Por favor, tente novamente."

# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_llm_manager = LLMManager()

# =============================================================================
# MAIN FUNCTION WITH CUSTOMER DATA SUPPORT
# =============================================================================

async def process_customer_message(message: str, chat_id: str) -> Dict[str, Any]:
    """Processa mensagem do cliente e armazena dados se necessário"""
    try:
        collected_data = {}

        # Extrair email da mensagem
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        email_match = re.search(email_pattern, message)
        if email_match:
            email = email_match.group().strip()
            collected_data['email'] = email
            _customer_store.set_customer_data(chat_id, {'email': email})
            logger.info(f"[{chat_id}] Email coletado automaticamente: {email}")

        # Padrões mais abrangentes para nome
        name_patterns = [
            r'[Mm]eu nome é ([A-Za-zÀ-ÿ\s]+?)(?:\.|,|!|\?|$)',
            r'[Ss]ou o?a? ([A-Za-zÀ-ÿ\s]+?)(?:\.|,|!|\?|$)',
            r'[Mm]e chamo ([A-Za-zÀ-ÿ\s]+?)(?:\.|,|!|\?|$)',
            r'[Éé] ([A-Za-zÀ-ÿ\s]+?)(?:\.|,|!|\?|$)',
            r'[Nn]ome:?\s*([A-Za-zÀ-ÿ\s]+?)(?:\.|,|!|\?|$)',
            r'[Cc]hamo ([A-Za-zÀ-ÿ\s]+?)(?:\.|,|!|\?|$)',
            # Padrão para "João Silva" ou "Maria da Silva" no início da mensagem
            r'^([A-ZÀ-Ÿ][a-zà-ÿ]+(?:\s+[a-zà-ÿ]+|\s+[A-ZÀ-Ÿ][a-zà-ÿ]+){1,2})(?:\s|\.|,|!|\?)',
        ]

        # Não tentar extrair nome de mensagens multi-linha (são msgs concatenadas do buffer)
        if '\n' not in message:
            # Palavras comuns que NÃO são nomes
            _NOT_NAMES = {
                'tem', 'quero', 'preciso', 'gostaria', 'pode', 'como', 'quanto',
                'qual', 'onde', 'quando', 'porque', 'sim', 'não', 'nao', 'oi',
                'ola', 'olá', 'bom', 'boa', 'obrigado', 'obrigada', 'valeu',
                'beleza', 'blz', 'blza', 'show', 'top', 'legal', 'massa',
                'tudo', 'manda', 'mande', 'envia', 'envie', 'fala', 'fale',
            }
            for pattern in name_patterns:
                # Último pattern (nome próprio no início) NÃO usa IGNORECASE
                flags = 0 if pattern.startswith(r'^(') else re.IGNORECASE
                name_match = re.search(pattern, message, flags)
                if name_match:
                    name = name_match.group(1).strip()
                    name_parts = [part for part in name.split() if part and len(part) > 1]
                    # Validar: 1-3 palavras, só letras, primeira palavra não é palavra comum
                    if (1 <= len(name_parts) <= 3
                            and all(part.replace('-', '').isalpha() for part in name_parts)
                            and name_parts[0].lower() not in _NOT_NAMES):
                        collected_data['name'] = name
                        _customer_store.set_customer_data(chat_id, {'name': name})
                        logger.info(f"[{chat_id}] Nome coletado automaticamente: {name}")
                        break

        # Retornar dados atuais do cliente
        current_data = _customer_store.get_customer_data(chat_id)
        logger.info(f"[{chat_id}] Dados atuais após processamento: {current_data}")

        return current_data

    except Exception as e:
        logger.error(f"Erro ao processar mensagem do cliente: {e}", exc_info=True)
        return _customer_store.get_customer_data(chat_id)


# =============================================================================
# SEMANTIC INTENT DETECTION
# =============================================================================

async def _detect_semantic_intents(
    user_message: str,
    llm_response: str = "",
    llm_reason: str = ""
) -> List[str]:
    """
    Detecta intenções semânticas baseado na mensagem do usuário e resposta do LLM.
    Usa análise de padrões e palavras-chave para identificar intenções comuns.

    Args:
        user_message: Mensagem enviada pelo usuário
        llm_response: Texto da resposta do LLM (opcional)
        llm_reason: Razão/justificativa do LLM (opcional)

    Returns:
        Lista de intenções detectadas
    """
    detected = []
    msg_lower = user_message.lower()
    context = f"{msg_lower} {llm_response.lower()} {llm_reason.lower()}"

    # === INTERESSE ===
    interesse_keywords = [
        'interessado', 'interesse', 'quero saber', 'me conte', 'como funciona',
        'gostaria', 'quero conhecer', 'pode me explicar', 'conta mais',
        'quero entender', 'me fala', 'poderia me falar', 'estou curioso',
        'tenho interesse', 'gostei', 'achei interessante'
    ]
    if any(kw in msg_lower for kw in interesse_keywords):
        detected.append('interesse')

    # === OBJEÇÃO ===
    objecao_keywords = [
        'não sei', 'não tenho certeza', 'mas', 'porém', 'entretanto',
        'não acredito', 'duvido', 'será que', 'não estou convencido',
        'preciso pensar', 'vou pensar', 'deixa eu pensar', 'não é bem assim',
        'discordo', 'não concordo', 'acho difícil'
    ]
    if any(kw in msg_lower for kw in objecao_keywords):
        detected.append('objecao')

    # === URGÊNCIA ===
    urgencia_keywords = [
        'urgente', 'urgência', 'rápido', 'agora', 'hoje', 'já',
        'preciso agora', 'não pode esperar', 'imediato', 'imediatamente',
        'o mais rápido', 'assim que possível', 'prazo', 'deadline',
        'emergência', 'correndo', 'apressado'
    ]
    if any(kw in msg_lower for kw in urgencia_keywords):
        detected.append('urgencia')

    # === DÚVIDA ===
    duvida_keywords = [
        'dúvida', 'como assim', 'não entendi', 'pode explicar',
        'o que significa', 'o que é', 'como é', 'qual é',
        'por que', 'porque', 'quando', 'onde', 'quem',
        'não compreendi', 'pode repetir', 'esclarecer'
    ]
    if any(kw in msg_lower for kw in duvida_keywords) or msg_lower.strip().endswith('?'):
        detected.append('duvida')

    # === PREÇO ===
    preco_keywords = [
        'preço', 'valor', 'quanto custa', 'quanto é', 'valores',
        'orçamento', 'custo', 'investimento', 'pagamento', 'parcela',
        'desconto', 'promoção', 'barato', 'caro', 'mensalidade',
        'plano', 'pacote', 'tabela de preços', 'r$', 'reais'
    ]
    if any(kw in msg_lower for kw in preco_keywords):
        detected.append('preco')

    # === AGENDAMENTO ===
    agendamento_keywords = [
        'agendar', 'marcar', 'reunião', 'call', 'chamada',
        'demonstração', 'demo', 'apresentação', 'horário', 'disponível',
        'agenda', 'calendário', 'quando podemos', 'vamos marcar',
        'encontro', 'visita', 'diagnóstico'
    ]
    if any(kw in msg_lower for kw in agendamento_keywords):
        detected.append('agendamento')

    # === CANCELAMENTO ===
    cancelamento_keywords = [
        'cancelar', 'cancela', 'desistir', 'desisto', 'não quero mais',
        'parar', 'encerrar', 'finalizar', 'sair', 'remover',
        'excluir', 'deletar', 'abandonar'
    ]
    if any(kw in msg_lower for kw in cancelamento_keywords):
        detected.append('cancelamento')

    # === SATISFAÇÃO ===
    satisfacao_keywords = [
        'obrigado', 'obrigada', 'agradeço', 'excelente', 'perfeito',
        'ótimo', 'maravilhoso', 'incrível', 'adorei', 'amei',
        'muito bom', 'top', 'sensacional', 'parabéns', 'satisfeito',
        'contente', 'feliz com'
    ]
    if any(kw in msg_lower for kw in satisfacao_keywords):
        detected.append('satisfacao')

    # === INSATISFAÇÃO ===
    insatisfacao_keywords = [
        'insatisfeito', 'decepcionado', 'frustrado', 'irritado',
        'chateado', 'reclamação', 'problema', 'erro', 'bug',
        'não funciona', 'não está funcionando', 'péssimo', 'horrível',
        'ruim', 'terrível', 'absurdo', 'inaceitável'
    ]
    if any(kw in msg_lower for kw in insatisfacao_keywords):
        detected.append('insatisfacao')

    # === COMPARAÇÃO ===
    comparacao_keywords = [
        'comparar', 'comparação', 'concorrente', 'outra empresa',
        'diferente', 'diferença', 'melhor que', 'pior que',
        'versus', 'vs', 'alternativa', 'opção', 'competidor',
        'vocês ou', 'isso ou aquilo'
    ]
    if any(kw in msg_lower for kw in comparacao_keywords):
        detected.append('comparacao')

    # === DECISOR ===
    decisor_keywords = [
        'preciso falar', 'meu chefe', 'meu gerente', 'diretor',
        'sócio', 'parceiro', 'equipe', 'time', 'consultar',
        'aprovação', 'autorização', 'quem decide', 'decisão',
        'não sou eu quem', 'preciso consultar', 'vou verificar com'
    ]
    if any(kw in msg_lower for kw in decisor_keywords):
        detected.append('decisor')

    # === TRIAL ===
    trial_keywords = [
        'testar', 'teste', 'trial', 'experimentar', 'avaliar',
        'período de teste', 'gratuito', 'free', 'demonstração',
        'piloto', 'poc', 'prova de conceito', 'antes de comprar'
    ]
    if any(kw in msg_lower for kw in trial_keywords):
        detected.append('trial')

    # === SUPORTE ===
    suporte_keywords = [
        'suporte', 'ajuda', 'help', 'assistência', 'técnico',
        'problema técnico', 'não consigo', 'como faço', 'tutorial',
        'manual', 'documentação', 'atendimento'
    ]
    if any(kw in msg_lower for kw in suporte_keywords):
        detected.append('suporte')

    # === INDICAÇÃO ===
    indicacao_keywords = [
        'indicação', 'indicado', 'recomendação', 'recomendado',
        'amigo falou', 'colega indicou', 'parceiro indicou',
        'quero indicar', 'posso indicar', 'programa de indicação'
    ]
    if any(kw in msg_lower for kw in indicacao_keywords):
        detected.append('indicacao')

    logger.debug(f"[SEMANTIC_DETECTION] Mensagem: '{user_message[:50]}...' -> Intenções: {detected}")
    return detected


# =============================================================================
# SEMANTIC INTENT ANALYSIS WITH LLM (FOR CUSTOM INSTRUCTIONS)
# =============================================================================

async def analyze_semantic_intent_with_llm(
    user_message: str,
    custom_instruction: str,
    conversation_context: Optional[List[Dict[str, str]]] = None,
    tag_name: str = None
) -> Dict[str, Any]:
    """
    Usa a LLM para analisar se a mensagem do usuário corresponde à instrução customizada.

    Esta é a análise semântica REAL usando IA, não matching por keywords.

    Args:
        user_message: Mensagem enviada pelo usuário
        custom_instruction: Instrução customizada configurada no frontend
        conversation_context: Contexto da conversa (últimas mensagens) para melhor análise
        tag_name: Nome da tag para logging

    Returns:
        dict com:
            - matched: bool indicando se houve correspondência
            - confidence: float de 0 a 1 indicando confiança
            - reason: str com explicação da decisão
    """
    start_time = time.time()
    request_id = f"semantic_llm_{int(time.time()*1000)}"

    logger.info(f"[{request_id}] [SEMANTIC_LLM_ANALYSIS] Iniciando análise semântica com LLM")
    logger.debug(f"[{request_id}] Tag: '{tag_name}', Instrução: '{custom_instruction[:100]}...', Mensagem: '{user_message[:100]}...'")

    result = {
        'matched': False,
        'confidence': 0.0,
        'reason': 'not_evaluated'
    }

    try:
        # Verificar se LLM está inicializado
        if not _llm_manager._initialized:
            await _llm_manager.initialize()

        # Construir contexto da conversa para análise
        context_text = ""
        if conversation_context and len(conversation_context) > 0:
            # Pegar as últimas 8 mensagens para contexto (4 trocas de mensagens)
            recent_messages = conversation_context[-8:] if len(conversation_context) > 8 else conversation_context
            context_lines = []
            for msg in recent_messages:
                role = "Usuário" if msg.get('role') == 'user' else "Assistente"
                content = msg.get('content', '')[:350]  # Aumentar limite para capturar mais contexto
                context_lines.append(f"{role}: {content}")
            context_text = "\n".join(context_lines)
            logger.debug(f"[SEMANTIC_ANALYSIS] Contexto construído com {len(recent_messages)} mensagens")

        # Prompt para análise semântica
        analysis_prompt = f"""Você é um analisador de intenções de mensagens. Sua tarefa é determinar se a ÚLTIMA MENSAGEM DO USUÁRIO corresponde à CONDIÇÃO especificada.

CONDIÇÃO PARA APLICAR TAG: "{custom_instruction}"

{f'CONTEXTO DA CONVERSA (últimas mensagens):{chr(10)}{context_text}{chr(10)}' if context_text else ''}
ÚLTIMA MENSAGEM DO USUÁRIO: "{user_message}"

REGRAS DE ANÁLISE - SEJA RIGOROSO:
1. A condição deve ser atendida de forma EXPLÍCITA e CLARA na mensagem do usuário
2. Respostas curtas ou indiretas NÃO são suficientes para aplicar a tag
3. O usuário precisa DEMONSTRAR CLARAMENTE a intenção descrita na condição
4. Perguntas sobre informações (preço, local, horário) NÃO são interesse em agendar
5. Apenas CONFIRME quando houver intenção REAL e DIRETA

EXEMPLOS - INTERESSE EM AGENDAR:
- "quero marcar uma consulta" -> {{"matched": true, "confidence": 0.95, "reason": "Intenção explícita de agendar"}}
- "gostaria de agendar" -> {{"matched": true, "confidence": 0.95, "reason": "Pedido direto de agendamento"}}
- "pode marcar pra mim?" -> {{"matched": true, "confidence": 0.90, "reason": "Solicitação clara de agendamento"}}
- "vamos agendar então" -> {{"matched": true, "confidence": 0.92, "reason": "Confirmação de intenção de agendar"}}

NÃO É INTERESSE EM AGENDAR:
- "Perdizes" (escolhendo local) -> {{"matched": false, "confidence": 0.15, "reason": "Apenas respondendo sobre preferência de local, não solicitou agendar"}}
- "quinta" (escolhendo dia) -> {{"matched": false, "confidence": 0.20, "reason": "Apenas respondendo sobre preferência de dia, não confirmou agendamento"}}
- "quanto custa?" -> {{"matched": false, "confidence": 0.10, "reason": "Pergunta sobre preço, não sobre agendamento"}}
- "quais os horários?" -> {{"matched": false, "confidence": 0.25, "reason": "Buscando informação, não confirmando agendamento"}}
- "onde fica?" -> {{"matched": false, "confidence": 0.10, "reason": "Pergunta sobre localização, não interesse em agendar"}}

Responda APENAS com um JSON válido no formato:
{{"matched": true/false, "confidence": 0.0-1.0, "reason": "explicação breve"}}

Analise a mensagem e responda APENAS com o JSON:"""

        # Fazer chamada à LLM com modelo leve para análise rápida
        messages = [
            {"role": "system", "content": "Você é um analisador de intenções. Responda APENAS com JSON válido."},
            {"role": "user", "content": analysis_prompt}
        ]

        # Usar modelo leve para análise rápida (formatting é mais barato)
        completion_params = await _llm_manager._prepare_completion_params(
            messages=messages,
            task_type=TaskType.FORMATTING,  # Modelo mais leve e rápido
            max_tokens=150,
            temperature=0.1  # Baixa temperatura para respostas mais determinísticas
        )

        completion = await _llm_manager.client.chat.completions.create(**completion_params)

        if completion.choices and len(completion.choices) > 0:
            response_text = completion.choices[0].message.content.strip()

            # Extrair JSON da resposta
            try:
                # Tentar encontrar JSON na resposta
                json_match = re.search(r'\{[^{}]*\}', response_text)
                if json_match:
                    json_str = json_match.group()
                    analysis_result = json.loads(json_str)

                    result['matched'] = analysis_result.get('matched', False)
                    result['confidence'] = float(analysis_result.get('confidence', 0.0))
                    result['reason'] = analysis_result.get('reason', 'Análise completada')

                else:
                    logger.warning(f"[{request_id}] Resposta da LLM não contém JSON válido: {response_text[:200]}")
                    result['reason'] = 'invalid_llm_response'

            except json.JSONDecodeError as e:
                logger.warning(f"[{request_id}] Erro ao parsear JSON da resposta LLM: {e}")
                result['reason'] = f'json_parse_error: {str(e)}'
        else:
            logger.warning(f"[{request_id}] Resposta vazia da LLM")
            result['reason'] = 'empty_llm_response'

        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"[{request_id}] [SEMANTIC_LLM_ANALYSIS] Concluído em {duration_ms:.2f}ms - "
                   f"Tag: '{tag_name}', Matched: {result['matched']}, Confidence: {result['confidence']:.2f}")

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(f"[{request_id}] [SEMANTIC_LLM_ANALYSIS] ERRO após {duration_ms:.2f}ms: {e}", exc_info=True)
        result['reason'] = f'error: {str(e)}'

    return result


async def get_llm_response(
    messages: List[Dict[str, str]],
    task_type: TaskType = TaskType.CONVERSATION,
    chat_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Função principal para obter resposta do LLM com suporte a coleta de dados e detecção de contexto insuficiente"""
    try:
        # Processar TODAS as mensagens do usuário para extrair dados (não apenas a última)
        if messages and chat_id:
            for msg in messages:
                if msg.get('role') == 'user' and msg.get('content'):
                    await process_customer_message(msg.get('content', ''), chat_id)

        # Verificar se deve usar apenas IA para fila de prospect
        try:
            instance_id = kwargs.get('instance_id')
            ai_for_queue_only = await get_ai_for_prospect_queue_only(instance_id=instance_id)
            if ai_for_queue_only and task_type != TaskType.CONVERSATION:
                logger.info(f"AI restrita à fila de prospect, convertendo task_type para CONVERSATION")
                task_type = TaskType.CONVERSATION
        except Exception as e:
            logger.warning(f"Erro ao verificar configuração AI_for_prospect_queue_only: {e}")

        # Inicializar LLM Manager
        if not _llm_manager._initialized:
            await _llm_manager.initialize()

        # Construir prompt do sistema com informações do cliente
        system_prompt = await build_system_prompt(chat_id=chat_id, **kwargs)

        # Preparar mensagens com contexto
        enhanced_messages = [{"role": "system", "content": system_prompt}] + messages

        # Obter resposta do LLM
        response_data = await _llm_manager.get_response(
            enhanced_messages,
            task_type=task_type,
            tools=None,
            chat_id=chat_id,
            **kwargs
        )

        result = response_data.model_dump() if hasattr(response_data, 'model_dump') else response_data

        # === INTEGRAÇÃO: Detecção de Contexto Insuficiente ===
        try:
            from .insufficient_context_notifier import handle_insufficient_context

            # Extrair texto da resposta para análise
            action_data = result.get("action_data", {})
            response_text = action_data.get("text", "")

            if response_text and chat_id:
                # Obter a última mensagem do usuário
                last_user_message = ""
                for msg in reversed(messages):
                    if msg.get('role') == 'user' and msg.get('content'):
                        last_user_message = msg.get('content', '')
                        break

                # Obter nome do cliente se disponível
                customer_name = _customer_store.get_customer_data(chat_id).get('name', None)

                # Verificar e tratar contexto insuficiente
                insufficient_result = await handle_insufficient_context(
                    customer_phone=chat_id,
                    customer_message=last_user_message,
                    llm_response=response_text,
                    customer_name=customer_name,
                    instance_id=kwargs.get('instance_id')
                )

                if insufficient_result.get("detected"):
                    logger.info(f"[{chat_id}] Contexto insuficiente detectado. Razão: {insufficient_result.get('reason')}")

                    # Marcar no resultado que foi detectado contexto insuficiente
                    result["insufficient_context_detected"] = True
                    result["insufficient_context_reason"] = insufficient_result.get("reason", "")

                    # Atualizar a resposta conforme configuração
                    if insufficient_result.get("action") == "suppress":
                        # Suprimir resposta ao cliente
                        result["action_data"]["action"] = "wait"
                        result["action_data"]["text"] = ""
                        result["action_data"]["reason"] = "Resposta suprimida: contexto insuficiente detectado"
                        logger.info(f"[{chat_id}] Resposta ao cliente suprimida conforme configuração.")
                    else:
                        # Usar mensagem de fallback
                        result["action_data"]["text"] = insufficient_result.get("response_text", response_text)
                        result["action_data"]["reason"] = f"Fallback: contexto insuficiente - {insufficient_result.get('reason')}"
                        logger.info(f"[{chat_id}] Usando mensagem de fallback para o cliente.")

        except ImportError as ie:
            logger.debug(f"Módulo insufficient_context_notifier não disponível: {ie}")
        except Exception as e:
            logger.warning(f"Erro ao verificar contexto insuficiente (não crítico): {e}")
            # Não falha a resposta por causa de erro na detecção

        # === INTEGRAÇÃO: Detecção Semântica de Intenções pela IA ===
        try:
            if chat_id and messages:
                # Obter a última mensagem do usuário para análise
                last_user_message = ""
                for msg in reversed(messages):
                    if msg.get('role') == 'user' and msg.get('content'):
                        last_user_message = msg.get('content', '')
                        break

                if last_user_message:
                    # Detectar intenções semanticamente
                    detected_intents = await _detect_semantic_intents(
                        user_message=last_user_message,
                        llm_response=result.get("action_data", {}).get("text", ""),
                        llm_reason=result.get("action_data", {}).get("reason", "")
                    )

                    if detected_intents:
                        logger.info(f"[{chat_id}] Intenções semânticas detectadas: {detected_intents}")
                        result["detected_intents"] = detected_intents

                    # Processar evento de automação para tags/fluxos com instruções customizadas
                    # IMPORTANTE: Aguardamos a conclusão para que automações (pause_llm, notify_team)
                    # sejam executadas ANTES de retornar a resposta ao message_handling
                    try:
                        from .automation_engine import process_ai_semantic_event
                        llm_text = result.get("action_data", {}).get("text", "")
                        await process_ai_semantic_event(
                            jid=chat_id,
                            user_message=last_user_message,
                            llm_response=llm_text,
                            instance_id=kwargs.get('instance_id')
                        )

                        # CORREÇÃO CRÍTICA: Verificar se pause_llm foi ativado pela automação
                        # Se foi, suprimir a resposta ANTES de retornar ao message_handling
                        try:
                            from src.core.prospect_management.state import get_prospect
                            prospect_after_automation = await get_prospect(chat_id)
                            if prospect_after_automation and prospect_after_automation.llm_paused:
                                logger.info(f"[{chat_id}] [SEMANTIC_PAUSE_CHECK] Automação ativou pause_llm - "
                                           f"Suprimindo resposta do LLM para evitar race condition")
                                # Suprimir resposta: mudar para ação "wait" sem texto
                                result["action_data"]["action"] = "wait"
                                result["action_data"]["text"] = ""
                                result["action_data"]["reason"] = "Resposta suprimida: pause_llm ativado por automação semântica"
                                result["llm_paused_by_automation"] = True
                        except Exception as e_pause_check:
                            logger.warning(f"[{chat_id}] Erro ao verificar pause_llm após automação: {e_pause_check}")

                    except Exception as e_auto:
                        logger.warning(f"[{chat_id}] Erro ao processar evento semântico: {e_auto}")

        except Exception as e:
            logger.warning(f"Erro na detecção semântica (não crítico): {e}")

        return result

    except Exception as e:
        logger.error(f"Erro crítico em get_llm_response: {e}", exc_info=True)
        return {
            "action_data": {
                "action": "send_text",
                "text": "Desculpe, houve um problema técnico. Por favor, tente novamente em alguns instantes.",
                "reason": "Erro interno do sistema"
            },
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model_used": "unknown",
            "response_time": 0.0,
            "tools_executed": []
        }

# Funções de compatibilidade
async def generate_sales_flow_stages(product_info: str, target_audience: str, **kwargs) -> List[Dict[str, Any]]:
    """Gera estágios de funil de vendas usando LLM"""
    from .db_operations.config_crud import get_product_context as get_pc
    from ..api.routes.config_models import ProductContextResponse

    product_context_obj = ProductContextResponse(context=product_info)
    return await generate_sales_flow_from_context(product_context_obj=product_context_obj)


async def generate_sales_flow_from_context(
    product_context_obj,
    ai_funnel_tips: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Gera estágios de funil de vendas usando LLM baseado no contexto do produto.
    Retorna lista de dicts compatível com SalesFlowStage.
    """
    try:
        if not _llm_manager._initialized:
            await _llm_manager.initialize()

        # Montar contexto do produto
        context_parts = []
        if hasattr(product_context_obj, 'context') and product_context_obj.context:
            context_parts.append(product_context_obj.context)
        if hasattr(product_context_obj, 'db_data') and product_context_obj.db_data:
            context_parts.append(f"Dados do banco: {json.dumps(product_context_obj.db_data, ensure_ascii=False)}")

        product_context = "\n".join(context_parts) if context_parts else "Produto/serviço genérico"

        # Prompt para gerar funil
        system_prompt = """Você é um especialista em funis de vendas. Sua tarefa é criar um funil de vendas otimizado.

REGRAS CRÍTICAS:
1. O primeiro estágio (stage_number=1) DEVE ter action_type="sequence" com mensagens de boas-vindas
2. Os demais estágios podem ter action_type="ask_llm" para respostas dinâmicas
3. Cada estágio deve ter um objetivo claro e trigger_description explicando quando avançar
4. Retorne APENAS um array JSON válido, sem texto adicional

FORMATO OBRIGATÓRIO para cada estágio:
{
  "stage_number": 1,
  "trigger_description": "Quando o lead é novo/primeiro contato",
  "objective": "Qualificar e apresentar o produto",
  "action_type": "sequence",  // OBRIGATÓRIO para stage 1
  "action_sequence": [        // OBRIGATÓRIO para stage 1
    {"type": "send_text", "delay_ms": 0, "text": "Olá! Seja bem-vindo..."}
  ],
  "action_llm_prompt": null   // DEVE ser null para stage 1
}

Para stages 2+:
{
  "stage_number": 2,
  "trigger_description": "Quando demonstra interesse",
  "objective": "Apresentar benefícios e valores",
  "action_type": "ask_llm",
  "action_sequence": null,
  "action_llm_prompt": "Foque em apresentar os benefícios e responder dúvidas sobre preços..."
}"""

        user_content = f"""Crie um funil de vendas para o seguinte contexto:

CONTEXTO DO PRODUTO/SERVIÇO:
{product_context}

{"DICAS ADICIONAIS: " + ai_funnel_tips if ai_funnel_tips else ""}

Crie 5-6 estágios otimizados. Retorne APENAS o array JSON."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        # Chamar LLM com tratamento de créditos insuficientes
        completion_params = {
            "model": "openai/gpt-4o-mini",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2048  # Reduzido para evitar erro de créditos
        }

        async def make_request():
            return await _llm_manager.client.chat.completions.create(**completion_params)

        try:
            completion = await retry_with_exponential_backoff(make_request)
        except InsufficientCreditsError as ice:
            logger.warning(f"[generate_sales_flow_from_context] Créditos insuficientes: {ice.available_tokens} disponíveis")

            # Verificar se temos informação suficiente para retry
            # -1 ou 0 significa que não conseguimos extrair tokens disponíveis
            if ice.available_tokens <= 0:
                logger.error("[generate_sales_flow_from_context] Sem informação de créditos. Usando funil padrão.")
                return _get_default_sales_flow()

            # Tentar com tokens reduzidos (chamada direta, sem retry_with_exponential_backoff)
            if ice.available_tokens > 500:
                completion_params['max_tokens'] = int(ice.available_tokens * 0.8)
                try:
                    completion = await _llm_manager.client.chat.completions.create(**completion_params)
                except Exception:
                    logger.error("[generate_sales_flow_from_context] Falha mesmo com tokens reduzidos. Usando funil padrão.")
                    return _get_default_sales_flow()
            else:
                logger.error("[generate_sales_flow_from_context] Créditos muito baixos. Usando funil padrão.")
                return _get_default_sales_flow()
        except Exception as e:
            logger.error(f"[generate_sales_flow_from_context] Erro na chamada LLM: {e}")
            return _get_default_sales_flow()

        response_content = completion.choices[0].message.content.strip()

        # Extrair JSON da resposta
        stages = _extract_json_array_from_text(response_content)

        if not stages:
            logger.error(f"[generate_sales_flow_from_context] Falha ao extrair JSON. Resposta: {response_content[:500]}")
            return _get_default_sales_flow()

        # Validar e corrigir primeiro estágio
        if stages and len(stages) > 0:
            first_stage = stages[0]
            if first_stage.get("action_type") != "sequence":
                logger.warning("[generate_sales_flow_from_context] Primeiro estágio não é 'sequence', corrigindo...")
                first_stage["action_type"] = "sequence"
                if not first_stage.get("action_sequence"):
                    first_stage["action_sequence"] = [
                        {"type": "send_text", "delay_ms": 0, "text": "Olá! Seja bem-vindo(a)! Como posso ajudar?"}
                    ]
                first_stage["action_llm_prompt"] = None

        logger.info(f"[generate_sales_flow_from_context] Gerados {len(stages)} estágios de funil")
        return stages

    except Exception as e:
        logger.error(f"[generate_sales_flow_from_context] Erro: {e}", exc_info=True)
        return _get_default_sales_flow()


def _extract_json_array_from_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """Extrai um array JSON de uma string de texto"""
    try:
        if not text or not text.strip():
            return None

        text = text.strip()

        # Tentar parse direto se começa com [
        if text.startswith('['):
            try:
                # Encontrar o fechamento do array
                bracket_count = 0
                end_idx = 0
                for i, char in enumerate(text):
                    if char == '[':
                        bracket_count += 1
                    elif char == ']':
                        bracket_count -= 1
                        if bracket_count == 0:
                            end_idx = i + 1
                            break
                if end_idx > 0:
                    return json.loads(text[:end_idx])
            except json.JSONDecodeError:
                pass

        # Procurar padrão de array JSON no texto
        array_pattern = r'\[[\s\S]*?\](?=\s*$|\s*```)'
        matches = re.findall(array_pattern, text)

        for match in matches:
            try:
                result = json.loads(match)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                continue

        # Tentar extrair de código markdown
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
        code_matches = re.findall(code_block_pattern, text)

        for code in code_matches:
            try:
                result = json.loads(code.strip())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                continue

        return None

    except Exception as e:
        logger.error(f"Erro ao extrair array JSON: {e}")
        return None


def _get_default_sales_flow() -> List[Dict[str, Any]]:
    """Retorna um funil padrão em caso de erro"""
    return [
        {
            "stage_number": 1,
            "trigger_description": "Primeiro contato com o lead",
            "objective": "Dar boas-vindas e qualificar interesse",
            "action_type": "sequence",
            "action_sequence": [
                {"type": "send_text", "delay_ms": 0, "text": "Olá! Seja bem-vindo(a)! Como posso ajudá-lo hoje?"}
            ],
            "action_llm_prompt": None
        },
        {
            "stage_number": 2,
            "trigger_description": "Lead demonstra interesse no produto/serviço",
            "objective": "Apresentar benefícios e valores",
            "action_type": "ask_llm",
            "action_sequence": None,
            "action_llm_prompt": "Apresente os benefícios do produto/serviço de forma consultiva."
        },
        {
            "stage_number": 3,
            "trigger_description": "Lead tem dúvidas ou objeções",
            "objective": "Esclarecer dúvidas e tratar objeções",
            "action_type": "ask_llm",
            "action_sequence": None,
            "action_llm_prompt": "Responda às dúvidas e trate objeções de forma empática."
        },
        {
            "stage_number": 4,
            "trigger_description": "Lead pronto para decisão",
            "objective": "Conduzir para fechamento/agendamento",
            "action_type": "ask_llm",
            "action_sequence": None,
            "action_llm_prompt": "Conduza para o fechamento da venda ou agendamento de reunião."
        },
        {
            "stage_number": 5,
            "trigger_description": "Pós-venda ou acompanhamento",
            "objective": "Acompanhar satisfação e fidelizar",
            "action_type": "ask_llm",
            "action_sequence": None,
            "action_llm_prompt": "Acompanhe a satisfação do cliente e ofereça suporte adicional."
        }
    ]

async def check_system_health() -> str:
    """Verifica a saúde geral do sistema LLM"""
    return "healthy"

logger.info("core.llm: Sistema LLM com coleta obrigatória de nome e email para agendamento")
