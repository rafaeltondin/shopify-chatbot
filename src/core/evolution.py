# -*- coding: utf-8 -*-
"""
Evolution API v2 Client
Compatível com Evolution API v2 (endpoints, autenticação via apikey, payloads camelCase)

Documentação: https://doc.evolution-api.com/v2/api-reference

Changelog v2.1.0 (2025-01-30):
- Adicionado retry automático com backoff exponencial (tenacity)
- Timeouts granulares (connect, read, write, pool)
- Health check antes de operações críticas
- Melhor tratamento de erros de conectividade
"""
import logging
import httpx
import json
from typing import Optional, Dict, Any, List, Tuple
import time
import asyncio
from functools import wraps

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryError
)

from src.core.config import settings
# Importar a função para obter a configuração da Evolution API do banco de dados
from src.core.db_operations.config_crud import get_evolution_config

logger = logging.getLogger(__name__)

# Versão da API suportada
EVOLUTION_API_VERSION = "2.x"
EVOLUTION_CLIENT_VERSION = "2.1.0"  # Versão do cliente com melhorias de resiliência

# --- Configurações de Retry e Timeout ---
RETRY_CONFIG = {
    "max_attempts": 3,          # Número máximo de tentativas
    "min_wait_seconds": 2,      # Espera mínima entre retries (segundos)
    "max_wait_seconds": 10,     # Espera máxima entre retries (segundos)
    "exponential_multiplier": 1  # Multiplicador para backoff exponencial
}

# Timeouts granulares para diferentes tipos de operação
TIMEOUT_CONFIG = {
    "default": httpx.Timeout(
        connect=10.0,   # Timeout para estabelecer conexão TCP
        read=30.0,      # Timeout para ler resposta
        write=10.0,     # Timeout para enviar dados
        pool=10.0       # Timeout para obter conexão do pool
    ),
    "media": httpx.Timeout(
        connect=10.0,
        read=120.0,     # Maior para download de mídia
        write=60.0,     # Maior para upload de mídia
        pool=10.0
    ),
    "health_check": httpx.Timeout(
        connect=5.0,    # Rápido para health check
        read=5.0,
        write=5.0,
        pool=5.0
    )
}

# --- Cache para Configurações da Evolution API ---
_evolution_config_cache: Optional[Dict[str, Any]] = None
_evolution_client_cache: Optional[httpx.AsyncClient] = None
_cache_timestamp: float = 0.0
CACHE_DURATION_SECONDS = 300  # Aumentado de 60s para 300s (5 minutos) para reduzir reconexões

# --- Status de Conectividade ---
_last_successful_connection: float = 0.0
_consecutive_failures: int = 0
_api_health_status: str = "unknown"  # "healthy", "degraded", "unhealthy", "unknown"

def _record_success():
    """Registra uma conexão bem-sucedida para métricas de saúde."""
    global _last_successful_connection, _consecutive_failures, _api_health_status
    _last_successful_connection = time.monotonic()
    _consecutive_failures = 0
    _api_health_status = "healthy"


def _record_failure():
    """Registra uma falha de conexão para métricas de saúde."""
    global _consecutive_failures, _api_health_status
    _consecutive_failures += 1
    if _consecutive_failures >= 5:
        _api_health_status = "unhealthy"
    elif _consecutive_failures >= 2:
        _api_health_status = "degraded"


def get_api_health_metrics() -> Dict[str, Any]:
    """
    Retorna métricas de saúde da conexão com a Evolution API.

    Returns:
        Dict com status, falhas consecutivas e tempo desde última conexão bem-sucedida
    """
    global _last_successful_connection, _consecutive_failures, _api_health_status

    time_since_success = None
    if _last_successful_connection > 0:
        time_since_success = time.monotonic() - _last_successful_connection

    return {
        "status": _api_health_status,
        "consecutive_failures": _consecutive_failures,
        "seconds_since_last_success": time_since_success,
        "client_version": EVOLUTION_CLIENT_VERSION,
        "cache_duration_seconds": CACHE_DURATION_SECONDS
    }


async def close_evolution_client():
    """
    Closes the Evolution API httpx client properly to prevent memory leaks.
    Should be called during application shutdown.
    """
    global _evolution_client_cache
    if _evolution_client_cache is not None:
        try:
            await _evolution_client_cache.aclose()
            logger.info("evolution.py: Evolution API httpx client closed successfully.")
        except Exception as e:
            logger.error(f"evolution.py: Error closing Evolution API client: {e}", exc_info=True)
        finally:
            _evolution_client_cache = None

def clear_evolution_cache():
    """
    Clears the in-memory cache for Evolution API client and configuration.
    This forces the application to re-fetch the configuration from the database
    on the next API call.
    NOTE: This does NOT close the httpx client. Use close_evolution_client() for proper cleanup.
    """
    global _evolution_config_cache, _evolution_client_cache, _cache_timestamp
    logger.info("evolution.py: Clearing Evolution API configuration cache.")
    _evolution_config_cache = None
    _evolution_client_cache = None
    _cache_timestamp = 0.0

async def clear_evolution_cache_async():
    """
    Async version that properly closes the httpx client before clearing the cache.
    Use this when you need to reload configuration and want to prevent memory leaks.
    """
    global _evolution_config_cache, _evolution_client_cache, _cache_timestamp
    logger.info("evolution.py: Clearing Evolution API configuration cache (async with proper cleanup).")

    # Fechar o cliente antes de limpar o cache
    if _evolution_client_cache is not None:
        try:
            await _evolution_client_cache.aclose()
            logger.info("evolution.py: Evolution API httpx client closed during cache clear.")
        except Exception as e:
            logger.error(f"evolution.py: Error closing Evolution API client during cache clear: {e}", exc_info=True)

    _evolution_config_cache = None
    _evolution_client_cache = None
    _cache_timestamp = 0.0

# Flag para evitar múltiplas pausas/alertas em sequência
_critical_error_handled = False
_critical_error_timestamp = 0.0

async def _handle_critical_evolution_error(instance_name: str, error_type: str, jid: str = None):
    """
    Trata erros críticos da Evolution API:
    1. Pausa a fila de processamento automaticamente
    2. Envia alerta para administradores
    3. Limpa cache para forçar reconexão
    """
    global _critical_error_handled, _critical_error_timestamp

    current_time = time.monotonic()

    # Evitar múltiplos tratamentos em sequência (cooldown de 60 segundos)
    if _critical_error_handled and (current_time - _critical_error_timestamp) < 60:
        logger.debug(f"evolution.py: Erro crítico já tratado recentemente. Ignorando tratamento duplicado.")
        return

    _critical_error_handled = True
    _critical_error_timestamp = current_time

    logger.critical(f"evolution.py: [CRITICAL_ERROR_HANDLER] Iniciando tratamento de erro crítico: {error_type}")

    try:
        # 1. Pausar a fila de processamento
        from src.core.prospect_management.queue import pause_queue
        pause_result = await pause_queue()
        if pause_result:
            logger.warning(f"evolution.py: [CRITICAL_ERROR_HANDLER] Fila de processamento PAUSADA automaticamente devido a erro: {error_type}")
        else:
            logger.error(f"evolution.py: [CRITICAL_ERROR_HANDLER] Falha ao pausar fila de processamento")

        # 2. Limpar cache da Evolution API para forçar reconexão
        await clear_evolution_cache_async()
        logger.info(f"evolution.py: [CRITICAL_ERROR_HANDLER] Cache da Evolution API limpo")

        # 3. Enviar alerta
        from src.core.alerts import send_critical_alert
        await send_critical_alert(
            alert_type="EVOLUTION_API_DISCONNECTED",
            title="Evolution API Desconectada",
            message=f"A instância '{instance_name}' perdeu conexão com o WhatsApp. Erro: {error_type}. Fila foi pausada automaticamente.",
            metadata={
                "instance_name": instance_name,
                "error_type": error_type,
                "affected_jid": jid,
                "action_taken": "queue_paused"
            }
        )
        logger.info(f"evolution.py: [CRITICAL_ERROR_HANDLER] Alerta crítico enviado")

    except ImportError as e:
        logger.warning(f"evolution.py: [CRITICAL_ERROR_HANDLER] Módulo de alertas não disponível: {e}")
    except Exception as e:
        logger.error(f"evolution.py: [CRITICAL_ERROR_HANDLER] Erro ao tratar erro crítico: {e}", exc_info=True)


def _get_mimetype(media_type: str, filename: str = "") -> str:
    """Retorna mimetype padrão baseado no tipo de mídia."""
    defaults = {
        "image": "image/png",
        "video": "video/mp4",
        "audio": "audio/mpeg",
        "document": "application/pdf",
    }
    # Tentar inferir do nome do arquivo
    ext_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp",
        ".mp4": "video/mp4", ".avi": "video/avi",
        ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
        ".pdf": "application/pdf", ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    if filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in ext_map:
            return ext_map[ext]
    return defaults.get(media_type, "application/octet-stream")


def _normalize_jid(jid: str) -> str:
    """
    Normalizes a JID (phone number) for the Evolution API.
    If JID contains '@', it's assumed to be in the full format (e.g., 5511999999999@s.whatsapp.net or a group JID) and is returned as is.
    Otherwise, all non-numeric characters are removed, and if the result is purely numeric (likely a phone number),
    '@s.whatsapp.net' is appended.
    """
    if "@" in jid: # Already a full JID (user or group)
        return jid
    
    # Remove non-digits
    cleaned_jid = "".join(filter(str.isdigit, jid))
    
    if cleaned_jid and cleaned_jid.isdigit(): # It's a phone number, append standard WhatsApp domain
        return f"{cleaned_jid}@s.whatsapp.net"
    
    # If after cleaning it's empty or somehow not purely digits (should not happen with phone numbers)
    # or if the original jid was something else not containing '@' and not a clear phone number,
    # return the cleaned version. This case should be rare for valid phone numbers.
    logger.warning(f"evolution.py: JID '{jid}' resulted in unusual cleaned JID '{cleaned_jid}'. Using as is or cleaned.")
    return cleaned_jid # Fallback, though ideally phone numbers will always become {digits}@s.whatsapp.net

async def _get_evolution_client_and_config() -> Optional[Tuple[httpx.AsyncClient, Dict[str, str]]]:
    """
    Fetches Evolution API config from DB (with caching) and returns a configured httpx client and the config dict.
    Returns: A tuple (client, config) or None if config is missing or invalid.

    Melhorias v2.1.0:
    - Timeouts granulares para diferentes operações
    - Keepalive otimizado para conexões persistentes
    - Cache aumentado para 5 minutos
    """
    global _evolution_config_cache, _evolution_client_cache, _cache_timestamp

    current_time = time.monotonic()

    # Verifica se o cache expirou ou não existe
    if _evolution_client_cache is None or (current_time - _cache_timestamp) > CACHE_DURATION_SECONDS:
        logger.info("evolution.py: Cache da Evolution API expirado ou inexistente. Recarregando do DB...")
        try:
            evo_config = await get_evolution_config()  # Busca do DB
            api_url = evo_config.get("url")
            api_key = evo_config.get("api_key")
            instance_name = evo_config.get("instance_name")

            if not api_url or not api_key or not instance_name:
                logger.error("evolution.py: Configuração da Evolution API (URL, Chave ou Instância) ausente no DB. Não é possível criar o cliente.")
                # Limpa o cache em caso de falha para tentar novamente na próxima vez
                _evolution_client_cache = None
                _evolution_config_cache = None
                return None

            # Recria o cliente com timeouts granulares e configurações otimizadas
            _evolution_client_cache = httpx.AsyncClient(
                base_url=api_url.rstrip('/'),
                headers={
                    "apikey": api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                timeout=TIMEOUT_CONFIG["default"],  # Timeouts granulares
                limits=httpx.Limits(
                    max_keepalive_connections=15,  # Aumentado para melhor reuso
                    max_connections=30,            # Aumentado para paralelismo
                    keepalive_expiry=60.0          # Manter conexões por 60s
                ),
                http2=False  # HTTP/1.1 para compatibilidade
            )
            _evolution_config_cache = {
                "base_url": api_url.rstrip('/'),
                "api_key": api_key,
                "instance_name": instance_name
            }
            _cache_timestamp = current_time

            logger.info(f"evolution.py: Cliente Evolution API v{EVOLUTION_CLIENT_VERSION} criado com sucesso. "
                       f"Base URL: {api_url.rstrip('/')}, Instance: {instance_name}")

        except Exception as e:
            logger.error(f"evolution.py: Erro ao criar cliente/configuração da Evolution API: {e}", exc_info=True)
            _evolution_client_cache = None
            _evolution_config_cache = None
            _record_failure()
            return None
    else:
        logger.debug("evolution.py: Usando cliente e configuração da Evolution API do cache.")

    if _evolution_client_cache and _evolution_config_cache:
        return _evolution_client_cache, _evolution_config_cache

    return None


# --- Funções de Request com Retry ---

async def _make_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    endpoint: str,
    timeout_type: str = "default",
    **kwargs
) -> httpx.Response:
    """
    Executa uma requisição HTTP com retry automático e backoff exponencial.

    Args:
        client: Cliente httpx configurado
        method: Método HTTP (GET, POST, etc.)
        endpoint: Endpoint da API
        timeout_type: Tipo de timeout ("default", "media", "health_check")
        **kwargs: Argumentos adicionais para a requisição

    Returns:
        httpx.Response em caso de sucesso

    Raises:
        httpx.RequestError: Após esgotar todas as tentativas
    """
    # Aplicar timeout específico se não fornecido nos kwargs
    if "timeout" not in kwargs:
        kwargs["timeout"] = TIMEOUT_CONFIG.get(timeout_type, TIMEOUT_CONFIG["default"])

    last_exception = None

    for attempt in range(1, RETRY_CONFIG["max_attempts"] + 1):
        try:
            start_time = time.monotonic()
            logger.debug(f"evolution.py: [RETRY] Tentativa {attempt}/{RETRY_CONFIG['max_attempts']} - {method} {endpoint}")

            response = await client.request(method, endpoint, **kwargs)

            elapsed = time.monotonic() - start_time
            logger.debug(f"evolution.py: [RETRY] Sucesso em {elapsed:.2f}s - Status: {response.status_code}")

            _record_success()
            return response

        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            last_exception = e
            _record_failure()
            logger.warning(f"evolution.py: [RETRY] Erro de conexão na tentativa {attempt}: {type(e).__name__}: {e}")

            if attempt < RETRY_CONFIG["max_attempts"]:
                # Calcular tempo de espera com backoff exponencial
                wait_time = min(
                    RETRY_CONFIG["max_wait_seconds"],
                    RETRY_CONFIG["min_wait_seconds"] * (RETRY_CONFIG["exponential_multiplier"] ** (attempt - 1))
                )
                logger.info(f"evolution.py: [RETRY] Aguardando {wait_time:.1f}s antes da próxima tentativa...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"evolution.py: [RETRY] Todas as {RETRY_CONFIG['max_attempts']} tentativas falharam para {method} {endpoint}")

        except httpx.TimeoutException as e:
            last_exception = e
            _record_failure()
            logger.warning(f"evolution.py: [RETRY] Timeout na tentativa {attempt}: {type(e).__name__}: {e}")

            if attempt < RETRY_CONFIG["max_attempts"]:
                wait_time = RETRY_CONFIG["min_wait_seconds"]
                logger.info(f"evolution.py: [RETRY] Aguardando {wait_time:.1f}s antes da próxima tentativa...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"evolution.py: [RETRY] Todas as tentativas de timeout falharam para {method} {endpoint}")

        except httpx.RequestError as e:
            # Outros erros de request (não tentar novamente para esses)
            last_exception = e
            _record_failure()
            logger.error(f"evolution.py: [RETRY] Erro de request não recuperável: {type(e).__name__}: {e}")
            break

    # Se chegou aqui, todas as tentativas falharam
    if last_exception:
        raise last_exception
    raise httpx.RequestError(f"Falha após {RETRY_CONFIG['max_attempts']} tentativas")


async def check_api_health() -> Dict[str, Any]:
    """
    Verifica a saúde da conexão com a Evolution API.

    Faz um health check rápido para verificar se a API está acessível
    antes de operações críticas.

    Returns:
        Dict com status de saúde e detalhes
    """
    logger.debug("evolution.py: [HEALTH_CHECK] Verificando saúde da Evolution API...")

    result = {
        "healthy": False,
        "status_code": None,
        "response_time_ms": None,
        "error": None,
        "api_version": None
    }

    try:
        client_config = await _get_evolution_client_and_config()
        if not client_config:
            result["error"] = "Client/config unavailable"
            return result

        client, config = client_config
        start_time = time.monotonic()

        # Usar endpoint de connection state como health check
        endpoint = f"/instance/connectionState/{config['instance_name']}"
        response = await client.get(endpoint, timeout=TIMEOUT_CONFIG["health_check"])

        elapsed_ms = (time.monotonic() - start_time) * 1000
        result["response_time_ms"] = round(elapsed_ms, 2)
        result["status_code"] = response.status_code

        if response.status_code == 200:
            result["healthy"] = True
            _record_success()
            try:
                data = response.json()
                result["connection_state"] = data.get("state") or data.get("instance", {}).get("state")
            except json.JSONDecodeError:
                pass
            logger.info(f"evolution.py: [HEALTH_CHECK] API saudável - {elapsed_ms:.0f}ms")
        else:
            result["error"] = f"Unexpected status: {response.status_code}"
            _record_failure()
            logger.warning(f"evolution.py: [HEALTH_CHECK] API retornou status {response.status_code}")

    except httpx.ConnectError as e:
        result["error"] = f"Connection failed: {str(e)}"
        _record_failure()
        logger.error(f"evolution.py: [HEALTH_CHECK] Falha de conexão: {e}")
    except httpx.TimeoutException as e:
        result["error"] = f"Timeout: {str(e)}"
        _record_failure()
        logger.error(f"evolution.py: [HEALTH_CHECK] Timeout: {e}")
    except Exception as e:
        result["error"] = f"Unexpected: {str(e)}"
        _record_failure()
        logger.error(f"evolution.py: [HEALTH_CHECK] Erro inesperado: {e}", exc_info=True)

    return result

async def send_text_message(jid: str, text: str, delay_ms: int = 0) -> Optional[Dict[str, Any]]:
    """
    Envia mensagem de texto via Evolution API com retry automático.

    Args:
        jid: Número do destinatário
        text: Texto da mensagem
        delay_ms: Delay antes de enviar (opcional)

    Returns:
        Dict com resposta da API ou None em caso de erro
    """
    logger.debug(f"evolution.py: [{jid}] Preparing to send text message. Delay: {delay_ms}ms.")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error(f"evolution.py: [{jid}] Cannot send text: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    normalized_jid = _normalize_jid(jid)
    logger.debug(f"evolution.py: Original JID: '{jid}', Normalized JID: '{normalized_jid}' for text message.")

    endpoint = f"/message/sendText/{config['instance_name']}"
    payload = {
        "number": normalized_jid,
        "text": text,
        "delay": delay_ms,
        "linkPreview": True,
    }
    truncated_text_for_log = text[:50] + '...' if len(text) > 50 else text
    logger.info(f"evolution.py: [{jid}] Sending text via Evolution API: '{truncated_text_for_log}'")

    try:
        # Usar função com retry automático
        response = await _make_request_with_retry(
            client, "POST", endpoint,
            timeout_type="default",
            json=payload
        )
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"evolution.py: [{jid}] Text message sent successfully (Status: {response.status_code}).")
        return response_data

    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.error(f"evolution.py: [{jid}] Connection failed after retries: {e}")
        # Não acionar alerta crítico para erros de conexão - pode ser temporário
    except httpx.RequestError as e:
        logger.error(f"evolution.py: [{jid}] Network error sending text: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        if "SessionError: No sessions" in e.response.text:
            logger.critical(f"evolution.py: [{jid}] ERRO CRÍTICO: Instância da Evolution API '{config['instance_name']}' não está conectada ou sessão expirou. Detalhes: {e.response.text[:200]}...")
            await _handle_critical_evolution_error(config['instance_name'], "SessionError: No sessions", jid)
        else:
            logger.error(f"evolution.py: [{jid}] HTTP error sending text: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except json.JSONDecodeError as e:
        logger.error(f"evolution.py: [{jid}] Failed to decode JSON response: {e}.")
    except Exception as e:
        logger.error(f"evolution.py: [{jid}] Unexpected error sending text: {e}", exc_info=True)
    return None

async def send_whatsapp_audio(jid: str, audio_base64: str, duration_seconds: int, delay_ms: int = 0) -> Optional[Dict[str, Any]]:
    """
    Envia áudio PTT via Evolution API com retry automático.

    Args:
        jid: Número do destinatário
        audio_base64: Áudio codificado em base64
        duration_seconds: Duração do áudio em segundos
        delay_ms: Delay antes de enviar (opcional)

    Returns:
        Dict com resposta da API ou None em caso de erro
    """
    logger.debug(f"evolution.py: [{jid}] Preparing to send WhatsApp audio (PTT). Duration: {duration_seconds}s, Delay: {delay_ms}ms.")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error(f"evolution.py: [{jid}] Cannot send audio: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    normalized_jid = _normalize_jid(jid)
    logger.debug(f"evolution.py: Original JID: '{jid}', Normalized JID: '{normalized_jid}' for audio message.")

    endpoint = f"/message/sendWhatsAppAudio/{config['instance_name']}"
    payload = {
        "number": normalized_jid,
        "audio": audio_base64,
        "delay": delay_ms,
    }
    logger.info(f"evolution.py: [{jid}] Sending WhatsApp audio (PTT, {duration_seconds}s) via Evolution API...")
    logger.debug(f"evolution.py: [{jid}] Payload size: {len(audio_base64)} chars base64")

    try:
        # Usar timeout de mídia e retry automático
        response = await _make_request_with_retry(
            client, "POST", endpoint,
            timeout_type="media",
            json=payload
        )
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"evolution.py: [{jid}] WhatsApp audio sent successfully (Status: {response.status_code}).")
        return response_data

    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.error(f"evolution.py: [{jid}] Connection failed after retries for audio: {e}")
    except httpx.RequestError as e:
        logger.error(f"evolution.py: [{jid}] Network error sending audio: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        if "SessionError: No sessions" in e.response.text:
            logger.critical(f"evolution.py: [{jid}] ERRO CRÍTICO ao enviar áudio: Instância não conectada")
            await _handle_critical_evolution_error(config['instance_name'], "SessionError: No sessions", jid)
        else:
            logger.error(f"evolution.py: [{jid}] HTTP error sending audio: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except json.JSONDecodeError as e:
        logger.error(f"evolution.py: [{jid}] Failed to decode JSON response from audio API: {e}.")
    except Exception as e:
        logger.error(f"evolution.py: [{jid}] Unexpected error sending audio: {e}", exc_info=True)
    return None

async def set_webhook_url(webhook_target_url: str) -> bool:
    """
    Configura o webhook na Evolution API v2 com retry automático.

    Args:
        webhook_target_url: URL do endpoint que receberá os webhooks

    Returns:
        True se configurado com sucesso, False caso contrário

    Nota: Evolution API v2 usa eventos em UPPERCASE_SNAKE_CASE
    """
    logger.debug(f"evolution.py: Preparing to set webhook URL to: {webhook_target_url}")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error("evolution.py: Cannot set webhook: Evolution client/config unavailable.")
        return False
    client, config = client_config_tuple

    instance_name = config['instance_name']
    endpoint = f"/webhook/set/{instance_name}"

    payload = {
        "webhook": {
            "enabled": True,
            "url": webhook_target_url,
            "webhookByEvents": False,
            "webhookBase64": True,
            "events": [
                "APPLICATION_STARTUP",
                "QRCODE_UPDATED",
                "MESSAGES_UPSERT",
                "MESSAGES_UPDATE",
                "MESSAGES_DELETE",
                "CONNECTION_UPDATE",
                "SEND_MESSAGE"
            ]
        }
    }
    logger.info(f"evolution.py: Setting Evolution API v2 webhook for instance '{instance_name}' to: {webhook_target_url}")
    logger.debug(f"evolution.py: Webhook payload: {json.dumps(payload)}")

    try:
        # Usar retry automático para configuração de webhook
        response = await _make_request_with_retry(
            client, "POST", endpoint,
            timeout_type="default",
            json=payload
        )
        if response.status_code in (200, 201):
            logger.info(f"evolution.py: Webhook set successfully for instance '{instance_name}'. Response: {response.json()}")
            return True
        else:
            logger.error(f"evolution.py: Failed to set webhook. Status: {response.status_code}, Response: {response.text[:500]}...")
            return False

    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.error(f"evolution.py: Connection failed after retries setting webhook: {e}")
        logger.warning("evolution.py: Webhook não configurado - verifique conectividade de rede do container com a Evolution API")
    except httpx.RequestError as e:
        logger.error(f"evolution.py: Network error setting webhook: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        logger.error(f"evolution.py: HTTP error setting webhook: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except json.JSONDecodeError as e:
        logger.error(f"evolution.py: Failed to decode JSON response from webhook API: {e}.")
    except Exception as e:
        logger.error(f"evolution.py: Unexpected error setting webhook: {e}", exc_info=True)
    return False

async def get_connection_state() -> Optional[str]:
    """
    Obtém o estado de conexão da instância na Evolution API v2 com retry automático.

    Returns:
        String com o estado ('open', 'close', 'connecting', etc.) ou None em caso de erro

    Nota: A resposta v2 pode ter estrutura diferente da v1
    """
    logger.debug("evolution.py: Preparing to get connection state...")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error("evolution.py: Cannot get connection state: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    endpoint = f"/instance/connectionState/{config['instance_name']}"
    logger.info(f"evolution.py: Fetching connection state for instance '{config['instance_name']}'...")

    try:
        response = await _make_request_with_retry(
            client, "GET", endpoint,
            timeout_type="health_check"
        )
        response.raise_for_status()
        response_data = response.json()

        # Tentar extrair estado - compatível com v1 e v2
        state = None
        if "state" in response_data:
            state = response_data.get("state")
        elif "instance" in response_data:
            state = response_data.get("instance", {}).get("state")

        logger.info(f"evolution.py: Current connection state for '{config['instance_name']}': {state}")
        return state

    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.error(f"evolution.py: Connection failed getting state: {e}")
    except httpx.RequestError as e:
        logger.error(f"evolution.py: Network error getting connection state: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        logger.error(f"evolution.py: HTTP error getting connection state: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except json.JSONDecodeError as e:
        logger.error(f"evolution.py: Failed to decode JSON response from state API: {e}.")
    except Exception as e:
        logger.error(f"evolution.py: Unexpected error getting connection state: {e}", exc_info=True)
    return None

async def check_whatsapp_numbers(numbers: List[str]) -> List[str]:
    """
    Checks a list of phone numbers against the Evolution API to see if they have WhatsApp.
    Args:
        numbers: A list of phone numbers to check. The API expects numbers without formatting, e.g., "5511999999999".
    Returns:
        A list of numbers that were confirmed to have WhatsApp.
    """
    if not numbers:
        return []
        
    # Pré-validação: filtrar números obviamente inválidos
    valid_format_numbers = []
    for number in numbers:
        cleaned = "".join(filter(str.isdigit, number))
        # Validação básica de formato brasileiro
        if len(cleaned) >= 10 and len(cleaned) <= 15:  # Faixa válida para números BR
            valid_format_numbers.append(cleaned)
        else:
            logger.warning(f"evolution.py: Número com formato inválido ignorado: {number} (limpo: {cleaned})")
    
    if not valid_format_numbers:
        logger.warning("evolution.py: Nenhum número com formato válido para verificação")
        return []
        
    logger.info(f"evolution.py: Preparando verificação WhatsApp para {len(valid_format_numbers)} números (de {len(numbers)} originais).")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error("evolution.py: Cannot check WhatsApp numbers: Evolution client/config unavailable.")
        return []
    client, config = client_config_tuple

    # A API espera uma lista de strings de números, ex: ["5511999999999", "5512888888888"]
    endpoint = f"/chat/whatsappNumbers/{config['instance_name']}"
    payload = {"numbers": valid_format_numbers}
    logger.info(f"evolution.py: Checking WhatsApp status for {len(valid_format_numbers)} numbers via Evolution API...")

    try:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        response_data = response.json()

        if not isinstance(response_data, list):
            logger.error(f"evolution.py: WhatsApp check API retornou tipo inesperado. Esperado: list, recebido: {type(response_data)}.")
            return []

        # Filtrar apenas números que existem E têm WhatsApp
        valid_numbers = []
        for item in response_data:
            exists = item.get("exists", False)
            number = item.get("number")
            
            if exists and number:
                valid_numbers.append(number)
                logger.debug(f"evolution.py: ✅ Número válido: {number}")
            else:
                logger.warning(f"evolution.py: ❌ Número rejeitado: {number} (exists: {exists})")
        
        logger.info(f"evolution.py: Verificação WhatsApp concluída. {len(valid_numbers)} números válidos de {len(valid_format_numbers)} verificados.")
        return valid_numbers
        
    except httpx.RequestError as e: 
        logger.error(f"evolution.py: Network error checking WhatsApp numbers: {e}", exc_info=True)
        return []  # Em caso de erro de rede, retornar lista vazia para evitar processamento de números inválidos
    except httpx.HTTPStatusError as e: 
        logger.error(f"evolution.py: HTTP error checking WhatsApp numbers: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
        return []  # Em caso de erro HTTP, retornar lista vazia para evitar processamento de números inválidos
    except json.JSONDecodeError as e: 
        logger.error(f"evolution.py: Failed to decode JSON response from WhatsApp check API: {e}. Raw: {response.text[:500]}...")
        return []
    except Exception as e: 
        logger.error(f"evolution.py: Unexpected error checking WhatsApp numbers: {e}", exc_info=True)
        return []

async def get_instance_info() -> Optional[Dict[str, Any]]:
    """
    Obtém informações detalhadas da instância na Evolution API v2.

    Returns:
        Dict com informações da instância ou None em caso de erro
    """
    logger.debug("evolution.py: Getting instance info...")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error("evolution.py: Cannot get instance info: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    endpoint = f"/instance/fetchInstances"
    logger.info(f"evolution.py: Fetching instance info for '{config['instance_name']}'...")

    try:
        response = await client.get(endpoint, params={"instanceName": config['instance_name']})
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"evolution.py: Instance info retrieved successfully.")
        return response_data
    except httpx.RequestError as e:
        logger.error(f"evolution.py: Network error getting instance info: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        logger.error(f"evolution.py: HTTP error getting instance info: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except Exception as e:
        logger.error(f"evolution.py: Unexpected error getting instance info: {e}", exc_info=True)
    return None


async def get_qrcode() -> Optional[Dict[str, Any]]:
    """
    Obtém o QR code para conexão da instância na Evolution API v2.

    Returns:
        Dict com dados do QR code (base64, pairingCode) ou None em caso de erro
    """
    logger.debug("evolution.py: Getting QR code...")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error("evolution.py: Cannot get QR code: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    endpoint = f"/instance/connect/{config['instance_name']}"
    logger.info(f"evolution.py: Fetching QR code for instance '{config['instance_name']}'...")

    try:
        response = await client.get(endpoint)
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"evolution.py: QR code retrieved successfully.")
        return response_data
    except httpx.RequestError as e:
        logger.error(f"evolution.py: Network error getting QR code: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        logger.error(f"evolution.py: HTTP error getting QR code: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except Exception as e:
        logger.error(f"evolution.py: Unexpected error getting QR code: {e}", exc_info=True)
    return None


async def send_media_message(
    jid: str,
    media_url: str,
    media_type: str = "image",
    caption: str = "",
    filename: str = "",
    delay_ms: int = 0
) -> Optional[Dict[str, Any]]:
    """
    Envia uma mensagem de mídia via Evolution API v2.

    Args:
        jid: Número do destinatário (com ou sem @s.whatsapp.net)
        media_url: URL da mídia a ser enviada
        media_type: Tipo da mídia ('image', 'video', 'audio', 'document')
        caption: Legenda para imagem/vídeo
        filename: Nome do arquivo para documentos
        delay_ms: Delay em milissegundos antes de enviar

    Returns:
        Dict com resposta da API ou None em caso de erro
    """
    logger.debug(f"evolution.py: [{jid}] Preparing to send {media_type} message.")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error(f"evolution.py: [{jid}] Cannot send media: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    normalized_jid = _normalize_jid(jid)

    endpoint = f"/message/sendMedia/{config['instance_name']}"
    payload = {
        "number": normalized_jid,
        "mediatype": media_type,
        "mimetype": _get_mimetype(media_type, filename),
        "media": media_url,
        "caption": caption,
        "fileName": filename,
        "delay": delay_ms,
    }

    logger.info(f"evolution.py: [{jid}] Sending {media_type} via Evolution API v2...")

    try:
        response = await client.post(endpoint, json=payload, timeout=120.0)
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"evolution.py: [{jid}] Media message sent successfully (Status: {response.status_code}).")
        return response_data
    except httpx.RequestError as e:
        logger.error(f"evolution.py: [{jid}] Network error sending media: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        logger.error(f"evolution.py: [{jid}] HTTP error sending media: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except Exception as e:
        logger.error(f"evolution.py: [{jid}] Unexpected error sending media: {e}", exc_info=True)
    return None


async def send_reaction(jid: str, message_id: str, reaction: str) -> Optional[Dict[str, Any]]:
    """
    Envia uma reação a uma mensagem via Evolution API v2.

    Args:
        jid: Número do destinatário
        message_id: ID da mensagem a reagir
        reaction: Emoji da reação (ex: "👍", "❤️", "")

    Returns:
        Dict com resposta da API ou None em caso de erro

    Nota: Para remover reação, envie reaction=""
    """
    logger.debug(f"evolution.py: [{jid}] Preparing to send reaction '{reaction}' to message {message_id}.")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error(f"evolution.py: [{jid}] Cannot send reaction: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    normalized_jid = _normalize_jid(jid)

    endpoint = f"/message/sendReaction/{config['instance_name']}"
    payload = {
        "key": {
            "remoteJid": normalized_jid,
            "fromMe": False,
            "id": message_id
        },
        "reaction": reaction
    }

    logger.info(f"evolution.py: [{jid}] Sending reaction via Evolution API v2...")

    try:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"evolution.py: [{jid}] Reaction sent successfully.")
        return response_data
    except httpx.RequestError as e:
        logger.error(f"evolution.py: [{jid}] Network error sending reaction: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        logger.error(f"evolution.py: [{jid}] HTTP error sending reaction: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except Exception as e:
        logger.error(f"evolution.py: [{jid}] Unexpected error sending reaction: {e}", exc_info=True)
    return None


async def mark_message_as_read(jid: str, message_ids: List[str]) -> bool:
    """
    Marca mensagens como lidas via Evolution API v2.

    Args:
        jid: Número do remetente das mensagens
        message_ids: Lista de IDs das mensagens a marcar como lidas

    Returns:
        True se marcadas com sucesso, False caso contrário
    """
    logger.debug(f"evolution.py: [{jid}] Marking {len(message_ids)} messages as read.")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error(f"evolution.py: [{jid}] Cannot mark as read: Evolution client/config unavailable.")
        return False
    client, config = client_config_tuple

    normalized_jid = _normalize_jid(jid)

    endpoint = f"/chat/markMessageAsRead/{config['instance_name']}"
    payload = {
        "readMessages": [
            {"remoteJid": normalized_jid, "id": msg_id}
            for msg_id in message_ids
        ]
    }

    logger.info(f"evolution.py: [{jid}] Marking messages as read via Evolution API v2...")

    try:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        logger.info(f"evolution.py: [{jid}] Messages marked as read successfully.")
        return True
    except httpx.RequestError as e:
        logger.error(f"evolution.py: [{jid}] Network error marking as read: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        logger.error(f"evolution.py: [{jid}] HTTP error marking as read: Status={e.response.status_code}, Response='{e.response.text[:200]}...'")
    except Exception as e:
        logger.error(f"evolution.py: [{jid}] Unexpected error marking as read: {e}", exc_info=True)
    return False


async def fetch_profile_picture_url(jid: str) -> Optional[str]:
    """
    Busca a URL da foto de perfil do WhatsApp via Evolution API v2.

    Args:
        jid: Número do contato (com ou sem @s.whatsapp.net)

    Returns:
        URL da foto de perfil ou None se não disponível/erro
    """
    logger.debug(f"evolution.py: [{jid}] Fetching profile picture URL.")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error(f"evolution.py: [{jid}] Cannot fetch profile picture: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    normalized_jid = _normalize_jid(jid)

    endpoint = f"/chat/fetchProfilePictureUrl/{config['instance_name']}"
    payload = {"number": normalized_jid}

    try:
        response = await client.post(endpoint, json=payload, timeout=10.0)
        response.raise_for_status()
        response_data = response.json()

        # A resposta contém: {"wuid": "...", "profilePictureUrl": "https://..."}
        profile_url = response_data.get("profilePictureUrl")

        if profile_url:
            logger.info(f"evolution.py: [{jid}] Profile picture URL retrieved successfully.")
            return profile_url
        else:
            logger.debug(f"evolution.py: [{jid}] No profile picture available for this contact.")
            return None

    except httpx.RequestError as e:
        logger.error(f"evolution.py: [{jid}] Network error fetching profile picture: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        # 404 é comum quando o usuário não tem foto de perfil
        if e.response.status_code == 404:
            logger.debug(f"evolution.py: [{jid}] No profile picture found (404).")
        else:
            logger.error(f"evolution.py: [{jid}] HTTP error fetching profile picture: Status={e.response.status_code}")
    except json.JSONDecodeError as e:
        logger.error(f"evolution.py: [{jid}] Failed to decode JSON response: {e}")
    except Exception as e:
        logger.error(f"evolution.py: [{jid}] Unexpected error fetching profile picture: {e}", exc_info=True)
    return None


async def send_presence(jid: str = None, presence: str = "available") -> bool:
    """
    Define presença da instância via Evolution API v2.

    Na v2, presença é definida a nível de instância (não por contato).
    Endpoint: POST /instance/setPresence/{instance}

    Args:
        jid: Ignorado na v2 (mantido para compatibilidade)
        presence: 'available' ou 'unavailable'

    Returns:
        True se enviado com sucesso, False caso contrário
    """
    # Na v2 só aceita available/unavailable
    if presence not in ("available", "unavailable"):
        presence = "available"

    logger.debug(f"evolution.py: Setting instance presence to '{presence}'.")
    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        return False
    client, config = client_config_tuple

    endpoint = f"/instance/setPresence/{config['instance_name']}"
    payload = {"presence": presence}

    try:
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        logger.debug(f"evolution.py: Presence '{presence}' set successfully.")
        return True
    except httpx.RequestError as e:
        logger.error(f"evolution.py: Network error setting presence: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        logger.error(f"evolution.py: HTTP error setting presence: Status={e.response.status_code}")
    except Exception as e:
        logger.error(f"evolution.py: Unexpected error setting presence: {e}", exc_info=True)
    return False


async def get_base64_from_media_message(message_key: Dict[str, Any], convert_to_mp4: bool = False, instance_name: str = None) -> Optional[Dict[str, Any]]:
    """
    Obtém o conteúdo de uma mensagem de mídia descriptografado em base64 com retry automático.

    A Evolution API descriptografa a mídia do WhatsApp e retorna em base64 pronto para uso.
    Este endpoint é NECESSÁRIO para processar áudios, pois as URLs do WhatsApp
    apontam para arquivos criptografados (.enc) que não podem ser processados diretamente.

    Args:
        message_key: Objeto key da mensagem contendo remoteJid, fromMe e id
                     Exemplo: {"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False, "id": "3EB01B580257047B4A20C7"}
        convert_to_mp4: Se True, converte vídeos para MP4. Para áudio, deixar False.
        instance_name: Nome da instância Evolution que recebeu a mensagem. Se não fornecido,
                       usa a instância configurada globalmente.

    Returns:
        Dict com campos: mediaType, fileName, mimetype, base64
        Ou None em caso de erro

    Exemplo de resposta:
        {
            "mediaType": "audioMessage",
            "fileName": "audio.oga",
            "mimetype": "audio/ogg; codecs=opus",
            "base64": "T2dnUwACAAAAAAA..."
        }
    """
    message_id = message_key.get('id', 'unknown')
    logger.info(f"evolution.py: [GET_BASE64_MEDIA] Solicitando mídia descriptografada para message_id: {message_id}, instance: {instance_name or 'default'}")

    client_config_tuple = await _get_evolution_client_and_config()
    if not client_config_tuple:
        logger.error("evolution.py: [GET_BASE64_MEDIA] Cannot get media: Evolution client/config unavailable.")
        return None
    client, config = client_config_tuple

    # Usar instância fornecida ou a configurada globalmente
    effective_instance = instance_name or config['instance_name']
    endpoint = f"/chat/getBase64FromMediaMessage/{effective_instance}"
    logger.info(f"evolution.py: [GET_BASE64_MEDIA] Usando instância: {effective_instance}")
    payload = {
        "message": {
            "key": message_key
        },
        "convertToMp4": convert_to_mp4
    }

    logger.debug(f"evolution.py: [GET_BASE64_MEDIA] Endpoint: {endpoint}, Payload: {json.dumps(payload)}")

    try:
        # Usar retry com timeout de mídia (maior para downloads)
        response = await _make_request_with_retry(
            client, "POST", endpoint,
            timeout_type="media",
            json=payload
        )
        response.raise_for_status()
        response_data = response.json()

        # Validar que recebemos base64
        if not response_data.get("base64"):
            logger.error(f"evolution.py: [GET_BASE64_MEDIA] Resposta não contém base64. Response: {str(response_data)[:200]}")
            return None

        logger.info(f"evolution.py: [GET_BASE64_MEDIA] Mídia obtida com sucesso. Type: {response_data.get('mediaType')}, "
                   f"Mimetype: {response_data.get('mimetype')}, Base64 size: {len(response_data.get('base64', ''))} chars")
        return response_data

    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.error(f"evolution.py: [GET_BASE64_MEDIA] Connection failed after retries: {e}")
        logger.warning(f"evolution.py: [GET_BASE64_MEDIA] Não foi possível obter mídia {message_id} - problema de conectividade")
    except httpx.RequestError as e:
        logger.error(f"evolution.py: [GET_BASE64_MEDIA] Network error: {e}", exc_info=True)
    except httpx.HTTPStatusError as e:
        error_text = e.response.text[:500] if e.response.text else "No response text"
        logger.error(f"evolution.py: [GET_BASE64_MEDIA] HTTP error: Status={e.response.status_code}, Response='{error_text}'")
        if e.response.status_code == 400:
            logger.error(f"evolution.py: [GET_BASE64_MEDIA] Bad Request - Verifique se o message_key está correto: {message_key}")
        elif e.response.status_code == 404:
            logger.error(f"evolution.py: [GET_BASE64_MEDIA] Message not found - A mensagem pode ter expirado ou sido deletada")
    except json.JSONDecodeError as e:
        logger.error(f"evolution.py: [GET_BASE64_MEDIA] Failed to decode JSON response: {e}")
    except Exception as e:
        logger.error(f"evolution.py: [GET_BASE64_MEDIA] Unexpected error: {e}", exc_info=True)

    return None


logger.info(f"evolution.py: Module loaded. Evolution API version: {EVOLUTION_API_VERSION}, Client version: {EVOLUTION_CLIENT_VERSION}")
