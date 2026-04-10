# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import hashlib
import time
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import httpx

from ..core.config import settings
from .config_loader import get_dynamic_config, get_config_loader

logger = logging.getLogger(__name__)

# --- Enums e Classes de Apoio ---

class TaskType(Enum):
    CONVERSATION = "conversation"
    SCHEDULING = "scheduling"
    FORMATTING = "formatting"
    TRANSCRIPTION = "transcription"
    CONTENT_GENERATION = "content_generation"

class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class LLMMetrics:
    """Métricas de performance do LLM"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_response_time: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    
    def add_request(self, success: bool, tokens: int = 0, cost: float = 0.0, response_time: float = 0.0):
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        self.total_tokens += tokens
        self.total_cost += cost
        # Calcular média simples de tempo de resposta
        if self.total_requests > 1:
            self.avg_response_time = (self.avg_response_time * (self.total_requests - 1) + response_time) / self.total_requests
        else:
            self.avg_response_time = response_time

@dataclass
class CircuitBreaker:
    """Circuit Breaker para resilience do LLM"""
    failure_threshold: int = field(default_factory=lambda: settings.LLM_CIRCUIT_BREAKER_THRESHOLD)
    timeout: int = field(default_factory=lambda: settings.LLM_CIRCUIT_BREAKER_TIMEOUT)
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    
    def should_allow_request(self) -> bool:
        """Verifica se deve permitir a requisição"""
        current_time = time.time()
        
        if self.state == CircuitBreakerState.CLOSED:
            return True
        elif self.state == CircuitBreakerState.OPEN:
            if current_time - (self.last_failure_time or 0) > self.timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                logger.info(f"Circuit breaker transitioning to HALF_OPEN")
                return True
            return False
        elif self.state == CircuitBreakerState.HALF_OPEN:
            return True
        return False
    
    def record_success(self):
        """Registra sucesso"""
        self.failure_count = 0
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            logger.info("Circuit breaker transitioning to CLOSED")
    
    def record_failure(self):
        """Registra falha"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitBreakerState.OPEN:
                self.state = CircuitBreakerState.OPEN
                logger.warning(f"Circuit breaker transitioning to OPEN after {self.failure_count} failures")

class RateLimiter:
    """Rate Limiter simples baseado em token bucket com configuração dinâmica"""
    
    def __init__(self, max_requests: int = None, window_minutes: int = 1):
        self.max_requests = max_requests or settings.LLM_RATE_LIMIT_PER_MINUTE
        self.window_seconds = window_minutes * 60
        self.requests: List[float] = []
    
    def update_from_config(self):
        """Atualiza limites baseado na configuração dinâmica"""
        config = get_dynamic_config()
        if config and config.rate_limiting_enabled:
            self.max_requests = config.requests_per_minute
    
    async def wait_if_needed(self):
        """Espera se necessário para respeitar rate limit"""
        # Atualizar configuração se necessário
        self.update_from_config()
        
        current_time = time.time()
        # Remove requests antigas
        self.requests = [req_time for req_time in self.requests 
                        if current_time - req_time < self.window_seconds]
        
        if len(self.requests) >= self.max_requests:
            # Calcula tempo de espera
            oldest_request = min(self.requests)
            wait_time = self.window_seconds - (current_time - oldest_request)
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                return await self.wait_if_needed()  # Recursão para verificar novamente
        
        self.requests.append(current_time)

class LLMCache:
    """Cache simples para respostas do LLM usando Redis"""
    
    def __init__(self):
        self.ttl = settings.LLM_CACHE_TTL
    
    def _generate_cache_key(self, messages: List[Dict], model: str, **kwargs) -> str:
        """Gera chave única para cache baseada nos parâmetros"""
        # Serializa os dados relevantes para hash
        cache_data = {
            "messages": messages,
            "model": model,
            "temperature": kwargs.get("temperature", settings.LLM_TEMPERATURE),
            "max_tokens": kwargs.get("max_tokens", settings.LLM_MAX_TOKENS)
        }
        cache_string = json.dumps(cache_data, sort_keys=True, separators=(',', ':'))
        return f"llm_cache:{hashlib.md5(cache_string.encode()).hexdigest()}"
    
    async def get(self, messages: List[Dict], model: str, **kwargs) -> Optional[Dict]:
        """Recupera resposta do cache"""
        if not settings.LLM_ENABLE_CACHING or not settings.redis_client:
            return None
        
        try:
            cache_key = self._generate_cache_key(messages, model, **kwargs)
            cached_data = await settings.redis_client.get(cache_key)
            if cached_data:
                logger.debug(f"Cache HIT for key: {cache_key[:16]}...")
                return json.loads(cached_data)
            else:
                logger.debug(f"Cache MISS for key: {cache_key[:16]}...")
                return None
        except Exception as e:
            logger.error(f"Erro ao recuperar do cache: {e}")
            return None
    
    async def set(self, messages: List[Dict], model: str, response: Dict, **kwargs):
        """Armazena resposta no cache"""
        if not settings.LLM_ENABLE_CACHING or not settings.redis_client:
            return
        
        try:
            cache_key = self._generate_cache_key(messages, model, **kwargs)
            cache_data = json.dumps(response, separators=(',', ':'))
            await settings.redis_client.setex(cache_key, self.ttl, cache_data)
            logger.debug(f"Cached response for key: {cache_key[:16]}...")
        except Exception as e:
            logger.error(f"Erro ao armazenar no cache: {e}")

# --- Instâncias Globais ---
_metrics = LLMMetrics()
_circuit_breaker = CircuitBreaker()
_rate_limiter = RateLimiter()
_cache = LLMCache()

def get_metrics() -> LLMMetrics:
    """Retorna métricas atuais"""
    return _metrics

def reset_metrics():
    """Reseta métricas"""
    global _metrics
    _metrics = LLMMetrics()

# --- Funções de Utilitários ---

def get_models_by_task(task_type: TaskType) -> List[str]:
    """Retorna lista de modelos preferenciais por tipo de tarefa usando configuração dinâmica"""
    config = get_dynamic_config()
    
    if config:
        # Usar configuração dinâmica
        model_mapping = {
            TaskType.CONVERSATION: config.conversation_models,
            TaskType.SCHEDULING: config.scheduling_models,
            TaskType.FORMATTING: config.formatting_models,
            TaskType.TRANSCRIPTION: [settings.LLM_MODEL_PREFERENCE],  # Fallback
            TaskType.CONTENT_GENERATION: [settings.LLM_MODEL_PREFERENCE]  # Fallback
        }
        return model_mapping.get(task_type, [settings.LLM_MODEL_PREFERENCE])
    else:
        # Fallback para configuração estática
        model_mapping = {
            TaskType.CONVERSATION: settings.LLM_CONVERSATION_MODELS,
            TaskType.SCHEDULING: settings.LLM_SCHEDULING_MODELS,
            TaskType.FORMATTING: settings.LLM_FORMATTING_MODELS,
            TaskType.TRANSCRIPTION: [settings.LLM_MODEL_PREFERENCE],  # Fallback
            TaskType.CONTENT_GENERATION: [settings.LLM_MODEL_PREFERENCE]  # Fallback
        }
        return model_mapping.get(task_type, [settings.LLM_MODEL_PREFERENCE])

def build_openrouter_headers() -> Dict[str, str]:
    """Constrói headers otimizados para OpenRouter usando configuração dinâmica"""
    config = get_dynamic_config()
    
    if config and config.headers:
        # Usar headers da configuração dinâmica
        headers = config.headers.copy()
        headers['Content-Type'] = 'application/json'  # Sempre necessário
        return headers
    else:
        # Fallback para headers estáticos
        return {
            'HTTP-Referer': settings.SITE_URL,
            'X-Title': settings.SITE_NAME,
            'X-Description': settings.APP_DESCRIPTION,
            'User-Agent': f'InnovaFluxo/{settings.APP_VERSION}',
            'X-App-Version': settings.APP_VERSION,
            'Content-Type': 'application/json'
        }

def build_provider_config(task_type: TaskType = TaskType.CONVERSATION) -> Dict[str, Any]:
    """Constrói configuração de provider routing baseada na tarefa usando configuração dinâmica"""
    config = get_dynamic_config()
    config_loader = get_config_loader()
    
    if config:
        # Usar configuração dinâmica
        provider_config = {
            "order": [],  # Deixar vazio para usar auto routing
            "allow_fallbacks": config.allow_fallbacks,
            "require_parameters": config.require_parameters,
            "data_collection": config.data_collection,
            "sort": config.provider_sort
        }
        
        # Adicionar configurações específicas da tarefa se disponíveis
        task_specific = config_loader.get_provider_config(task_type.value)
        provider_config.update(task_specific)
        # Remover 'ignore_providers' pois não é um parâmetro da API LLM
        provider_config.pop('ignore_providers', None)
        
    else:
        # Fallback para configuração estática
        provider_config = {
            "order": [],  # Deixar vazio para usar auto routing
            "allow_fallbacks": settings.LLM_ALLOW_FALLBACKS,
            "require_parameters": settings.LLM_REQUIRE_PARAMETERS,
            "data_collection": settings.LLM_DATA_COLLECTION,
            "sort": settings.LLM_PROVIDER_SORT
        }
    
    return provider_config

class InsufficientCreditsError(Exception):
    """Erro quando não há créditos suficientes no OpenRouter"""
    def __init__(self, message: str, available_tokens: int = 0, requested_tokens: int = 0):
        super().__init__(message)
        self.available_tokens = available_tokens
        self.requested_tokens = requested_tokens

def extract_available_tokens_from_error(error_message: str) -> tuple[int, int]:
    """
    Extrai os tokens disponíveis e solicitados da mensagem de erro 402.

    Exemplos de mensagens:
    - 'You requested up to 4096 tokens, but can only afford 1097'
    - 'Insufficient credits' (sem números)
    - 'Payment Required'

    Returns:
        tuple[int, int]: (tokens_solicitados, tokens_disponíveis)
        Retorna (-1, -1) se for erro 402 mas sem informação de tokens
        Retorna (0, 0) se não conseguir identificar o erro
    """
    import re

    # Log da mensagem completa para debug
    logger.debug(f"[extract_available_tokens] Analisando mensagem: {error_message[:500]}")

    # Padrão 1: "requested up to X tokens, but can only afford Y"
    pattern1 = r'requested up to (\d+) tokens.*can only afford (\d+)'
    match = re.search(pattern1, error_message, re.IGNORECASE)
    if match:
        requested = int(match.group(1))
        available = int(match.group(2))
        logger.debug(f"[extract_available_tokens] Pattern 1 matched: requested={requested}, available={available}")
        return (requested, available)

    # Padrão 2: "can only afford X tokens" (sem valor de requested)
    pattern2 = r'can only afford (\d+)'
    match = re.search(pattern2, error_message, re.IGNORECASE)
    if match:
        available = int(match.group(1))
        logger.debug(f"[extract_available_tokens] Pattern 2 matched: available={available}")
        return (0, available)  # requested desconhecido

    # Padrão 3: Verificar se é erro 402 genérico (sem informação de tokens)
    if '402' in error_message or 'Payment Required' in error_message.lower() or 'insufficient' in error_message.lower():
        logger.debug(f"[extract_available_tokens] Erro 402 detectado mas sem informação de tokens")
        return (-1, -1)  # Indica erro de créditos mas sem valores específicos

    return (0, 0)

async def retry_with_exponential_backoff(
    func: Callable,
    max_retries: int = None,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0
) -> Any:
    """
    Executa função com retry e backoff exponencial.

    Tratamento especial para erro 402 (Payment Required):
    - Não faz retry pois é um erro de créditos insuficientes
    - Lança InsufficientCreditsError com informações dos tokens
    """
    max_retries = max_retries or settings.LLM_MAX_RETRIES

    for attempt in range(max_retries + 1):
        try:
            # Verificar circuit breaker
            if not _circuit_breaker.should_allow_request():
                raise Exception("Circuit breaker is OPEN")

            # Aplicar rate limiting
            await _rate_limiter.wait_if_needed()

            # Executar função
            start_time = time.time()
            result = await func()
            response_time = time.time() - start_time

            # Registrar sucesso
            _circuit_breaker.record_success()
            _metrics.add_request(True, response_time=response_time)

            return result

        except Exception as e:
            error_str = str(e)

            # Tratamento especial para erro 402 (Payment Required / Insufficient Credits)
            if '402' in error_str or 'Payment Required' in error_str:
                requested, available = extract_available_tokens_from_error(error_str)

                # Log diferenciado baseado no resultado da extração
                if requested == -1 and available == -1:
                    # Erro 402 sem informação específica de tokens
                    logger.warning(
                        f"[LLM_CREDITS] Créditos insuficientes no OpenRouter (sem detalhes de tokens). "
                        f"Mensagem: {error_str[:200]}"
                    )
                else:
                    logger.warning(
                        f"[LLM_CREDITS] Créditos insuficientes no OpenRouter. "
                        f"Solicitado: {requested} tokens, Disponível: {available} tokens"
                    )

                # Não fazer retry para erro de créditos - propagar erro especial
                raise InsufficientCreditsError(
                    message=f"Créditos insuficientes: {available} tokens disponíveis de {requested} solicitados",
                    available_tokens=available,
                    requested_tokens=requested
                )

            _circuit_breaker.record_failure()
            _metrics.add_request(False)

            if attempt == max_retries:
                logger.error(f"Falha após {max_retries + 1} tentativas: {e}")
                raise

            # Calcular delay
            delay = min(base_delay * (backoff_factor ** attempt), max_delay)
            logger.warning(f"Tentativa {attempt + 1} falhou: {e}. Tentando novamente em {delay:.2f}s...")
            await asyncio.sleep(delay)

async def validate_openrouter_connection() -> bool:
    """Valida conectividade com OpenRouter"""
    try:
        headers = build_openrouter_headers()
        headers['Authorization'] = f'Bearer {settings.OPENROUTER_API_KEY}'
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.OPENROUTER_BASE_URL}/models",
                headers=headers
            )
            response.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Falha na validação do OpenRouter: {e}")
        return False

logger.info("llm_utils: Utilitários LLM carregados com circuit breaker, cache e rate limiting")
