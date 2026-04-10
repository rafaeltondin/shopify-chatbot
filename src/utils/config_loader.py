# -*- coding: utf-8 -*-
import logging
import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import asyncio
import threading

from ..core.config import settings

logger = logging.getLogger(__name__)

@dataclass
class LLMConfig:
    """Configuração dinâmica do LLM carregada do YAML"""
    
    # Geral
    version: str
    description: str
    environment: str
    
    # Modelos
    conversation_models: List[str]
    scheduling_models: List[str]
    formatting_models: List[str]
    
    # Provider routing
    provider_sort: str
    allow_fallbacks: bool
    require_parameters: bool
    data_collection: str
    
    # Cache
    cache_enabled: bool
    cache_ttl: int
    cache_exclude_tools: bool
    
    # Rate limiting
    rate_limiting_enabled: bool
    requests_per_minute: int
    burst_limit: int
    
    # Circuit breaker
    circuit_breaker_enabled: bool
    failure_threshold: int
    timeout_seconds: int
    
    # Retry
    retry_enabled: bool
    max_retry_attempts: int
    base_delay: float
    max_delay: float
    backoff_factor: float
    
    # Streaming
    streaming_enabled: bool
    streaming_buffer_size: int
    streaming_timeout: int
    
    # Monitoring
    monitoring_enabled: bool
    log_level: str
    track_costs: bool
    track_response_times: bool
    
    # Headers
    headers: Dict[str, str]
    
    # Tools
    tools_config: Dict[str, Any]
    
    # Raw data para acesso direto
    raw_config: Dict[str, Any]

class ConfigFileWatcher(FileSystemEventHandler):
    """Monitor de mudanças no arquivo de configuração"""

    def __init__(self, config_loader, config_file_path, event_loop=None):
        self.config_loader = config_loader
        self.config_file_path = Path(config_file_path)
        self.last_modified = 0
        self._event_loop = event_loop

    def on_modified(self, event):
        if not event.is_directory and Path(event.src_path) == self.config_file_path:
            current_time = os.path.getmtime(self.config_file_path)
            if current_time > self.last_modified:
                self.last_modified = current_time
                logger.info(f"Arquivo de configuração modificado: {self.config_file_path}")
                # Use run_coroutine_threadsafe to schedule async task from watchdog thread
                if self._event_loop and self._event_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.config_loader.reload_config(),
                        self._event_loop
                    )
                else:
                    logger.warning("Event loop not available for config reload scheduling")

class DynamicConfigLoader:
    """Carregador de configuração dinâmica com hot-reload"""
    
    def __init__(self, config_file_path: Optional[str] = None):
        self.config_file_path = Path(config_file_path or "llm_config.yaml")
        self.config: Optional[LLMConfig] = None
        self._observer: Optional[Observer] = None
        self._lock = asyncio.Lock()
        self._callbacks: List[callable] = []
        
    async def initialize(self):
        """Inicializa o carregador de configuração"""
        await self.load_config()
        if settings.LOG_LEVEL == "DEBUG":
            self.start_file_watcher()
        
    async def load_config(self) -> LLMConfig:
        """Carrega configuração do arquivo YAML"""
        async with self._lock:
            try:
                if not self.config_file_path.exists():
                    logger.warning(f"Arquivo de configuração não encontrado: {self.config_file_path}")
                    return self._get_default_config()
                
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    raw_config = yaml.safe_load(f)
                
                self.config = self._parse_config(raw_config)
                logger.info(f"Configuração carregada: {self.config_file_path}")
                
                # Executar callbacks de mudança de configuração
                await self._execute_callbacks()
                
                return self.config
                
            except Exception as e:
                logger.error(f"Erro ao carregar configuração: {e}", exc_info=True)
                if self.config is None:
                    return self._get_default_config()
                return self.config
    
    async def reload_config(self):
        """Recarrega configuração"""
        logger.info("Recarregando configuração dinâmica...")
        await self.load_config()
    
    def _parse_config(self, raw_config: Dict[str, Any]) -> LLMConfig:
        """Converte configuração raw em objeto LLMConfig"""
        
        # Substituir variáveis de ambiente
        processed_config = self._substitute_env_variables(raw_config)
        
        try:
            return LLMConfig(
                # Geral
                version=processed_config.get('general', {}).get('version', '2.1.0'),
                description=processed_config.get('general', {}).get('description', 'WhatsApp AI Agent'),
                environment=processed_config.get('general', {}).get('environment', 'production'),
                
                # Modelos
                conversation_models=self._get_model_list(processed_config, 'conversation'),
                scheduling_models=self._get_model_list(processed_config, 'scheduling'),
                formatting_models=self._get_model_list(processed_config, 'formatting'),
                
                # Provider routing
                provider_sort=processed_config.get('provider_routing', {}).get('default_sort', 'throughput'),
                allow_fallbacks=processed_config.get('provider_routing', {}).get('allow_fallbacks', True),
                require_parameters=processed_config.get('provider_routing', {}).get('require_parameters', True),
                data_collection=processed_config.get('provider_routing', {}).get('data_collection', 'deny'),
                
                # Cache
                cache_enabled=processed_config.get('cache', {}).get('enabled', True),
                cache_ttl=processed_config.get('cache', {}).get('ttl_seconds', 3600),
                cache_exclude_tools=processed_config.get('cache', {}).get('exclude_tools', True),
                
                # Rate limiting
                rate_limiting_enabled=processed_config.get('rate_limiting', {}).get('enabled', True),
                requests_per_minute=processed_config.get('rate_limiting', {}).get('requests_per_minute', 60),
                burst_limit=processed_config.get('rate_limiting', {}).get('burst_limit', 10),
                
                # Circuit breaker
                circuit_breaker_enabled=processed_config.get('circuit_breaker', {}).get('enabled', True),
                failure_threshold=processed_config.get('circuit_breaker', {}).get('failure_threshold', 5),
                timeout_seconds=processed_config.get('circuit_breaker', {}).get('timeout_seconds', 60),
                
                # Retry
                retry_enabled=processed_config.get('retry', {}).get('enabled', True),
                max_retry_attempts=processed_config.get('retry', {}).get('max_attempts', 3),
                base_delay=processed_config.get('retry', {}).get('base_delay', 1.0),
                max_delay=processed_config.get('retry', {}).get('max_delay', 60.0),
                backoff_factor=processed_config.get('retry', {}).get('backoff_factor', 2.0),
                
                # Streaming
                streaming_enabled=processed_config.get('streaming', {}).get('enabled', False),
                streaming_buffer_size=processed_config.get('streaming', {}).get('buffer_size', 1024),
                streaming_timeout=processed_config.get('streaming', {}).get('timeout_seconds', 300),
                
                # Monitoring
                monitoring_enabled=processed_config.get('monitoring', {}).get('enabled', True),
                log_level=processed_config.get('monitoring', {}).get('log_level', 'INFO'),
                track_costs=processed_config.get('monitoring', {}).get('metrics', {}).get('track_costs', True),
                track_response_times=processed_config.get('monitoring', {}).get('metrics', {}).get('track_response_times', True),
                
                # Headers
                headers=self._build_headers(processed_config.get('headers', {})),
                
                # Tools
                tools_config=processed_config.get('tools', {}),
                
                # Raw para acesso direto
                raw_config=processed_config
            )
        except Exception as e:
            logger.error(f"Erro ao parsear configuração: {e}", exc_info=True)
            return self._get_default_config()
    
    def _get_model_list(self, config: Dict[str, Any], model_type: str) -> List[str]:
        """Extrai lista de modelos de um tipo específico"""
        models_config = config.get('models', {}).get(model_type, {})
        result = []

        # Adicionar modelo primário
        primary = models_config.get('primary')
        if primary:
            result.append(primary)

        # Adicionar fallbacks
        fallbacks = models_config.get('fallbacks', [])
        result.extend(fallbacks)

        # PROTEÇÃO: Limitar a máximo 3 modelos (limite do OpenRouter)
        if len(result) > 3:
            logger.warning(f"Limitando modelos para {model_type} de {len(result)} para 3 (limite do OpenRouter)")
            result = result[:3]

        # Fallback para configuração padrão se vazio
        if not result:
            defaults = {
                'conversation': ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"],
                'scheduling': ["openai/gpt-4o", "anthropic/claude-3.5-haiku"],
                'formatting': ["anthropic/claude-3.5-haiku", "openai/gpt-4o-mini"]
            }
            result = defaults.get(model_type, ["openai/gpt-4o"])

        return result
    
    def _substitute_env_variables(self, config: Any) -> Any:
        """Substitui variáveis de ambiente no formato ${VAR}"""
        if isinstance(config, dict):
            return {k: self._substitute_env_variables(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._substitute_env_variables(item) for item in config]
        elif isinstance(config, str):
            # Substituir variáveis de ambiente
            import re
            def replace_env_var(match):
                var_name = match.group(1)
                return os.getenv(var_name, match.group(0))  # Retorna original se não encontrar
            
            return re.sub(r'\$\{([^}]+)\}', replace_env_var, config)
        else:
            return config
    
    def _build_headers(self, headers_config: Dict[str, Any]) -> Dict[str, str]:
        """Constrói headers a partir da configuração"""
        headers = {}
        
        # Headers padrão
        default_headers = {
            'HTTP-Referer': headers_config.get('http_referer', settings.SITE_URL),
            'X-Title': headers_config.get('x_title', settings.SITE_NAME),
            'X-Description': headers_config.get('x_description', settings.APP_DESCRIPTION),
            'User-Agent': headers_config.get('user_agent', f'InnovaFluxo/{settings.APP_VERSION}'),
            'X-App-Version': headers_config.get('x_app_version', settings.APP_VERSION)
        }
        
        headers.update(default_headers)
        
        # Headers customizados
        custom_headers = headers_config.get('custom', {})
        headers.update(custom_headers)
        
        return headers
    
    def _get_default_config(self) -> LLMConfig:
        """Retorna configuração padrão caso não consiga carregar do arquivo"""
        logger.info("Usando configuração padrão do LLM")
        return LLMConfig(
            version="2.1.0",
            description="WhatsApp AI Prospecting Agent",
            environment="production",
            conversation_models=["anthropic/claude-3.5-sonnet", "openai/gpt-4o"],
            scheduling_models=["openai/gpt-4o", "anthropic/claude-3.5-haiku"],
            formatting_models=["anthropic/claude-3.5-haiku", "openai/gpt-4o-mini"],
            provider_sort="throughput",
            allow_fallbacks=True,
            require_parameters=True,
            data_collection="deny",
            cache_enabled=True,
            cache_ttl=3600,
            cache_exclude_tools=True,
            rate_limiting_enabled=True,
            requests_per_minute=60,
            burst_limit=10,
            circuit_breaker_enabled=True,
            failure_threshold=5,
            timeout_seconds=60,
            retry_enabled=True,
            max_retry_attempts=3,
            base_delay=1.0,
            max_delay=60.0,
            backoff_factor=2.0,
            streaming_enabled=False,
            streaming_buffer_size=1024,
            streaming_timeout=300,
            monitoring_enabled=True,
            log_level="INFO",
            track_costs=True,
            track_response_times=True,
            headers={
                'HTTP-Referer': settings.SITE_URL,
                'X-Title': settings.SITE_NAME,
                'User-Agent': f'InnovaFluxo/{settings.APP_VERSION}'
            },
            tools_config={},
            raw_config={}
        )
    
    def start_file_watcher(self):
        """Inicia monitoramento de mudanças no arquivo"""
        if self._observer:
            return

        try:
            # Capture the current event loop for use in the watchdog thread
            try:
                event_loop = asyncio.get_running_loop()
            except RuntimeError:
                event_loop = None
                logger.warning("No running event loop when starting file watcher")

            self._observer = Observer()
            event_handler = ConfigFileWatcher(self, self.config_file_path, event_loop=event_loop)
            self._observer.schedule(event_handler, path=str(self.config_file_path.parent), recursive=False)
            self._observer.start()
            logger.info(f"Monitoramento de arquivo iniciado: {self.config_file_path}")
        except Exception as e:
            logger.error(f"Erro ao iniciar monitoramento de arquivo: {e}")
    
    def stop_file_watcher(self):
        """Para monitoramento de mudanças no arquivo"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Monitoramento de arquivo interrompido")
    
    def add_change_callback(self, callback: callable):
        """Adiciona callback para mudanças de configuração"""
        self._callbacks.append(callback)
    
    async def _execute_callbacks(self):
        """Executa callbacks de mudança de configuração"""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self.config)
                else:
                    callback(self.config)
            except Exception as e:
                logger.error(f"Erro ao executar callback: {e}")
    
    def get_config(self) -> Optional[LLMConfig]:
        """Retorna configuração atual"""
        return self.config
    
    def get_model_config(self, task_type: str) -> Dict[str, Any]:
        """Retorna configuração específica de modelo para um tipo de tarefa"""
        if not self.config:
            return {}
        
        models_config = self.config.raw_config.get('models', {})
        return models_config.get(task_type, {})
    
    def get_provider_config(self, task_type: Optional[str] = None) -> Dict[str, Any]:
        """Retorna configuração de provider routing"""
        if not self.config:
            return {}
        
        base_config = {
            "allow_fallbacks": self.config.allow_fallbacks,
            "require_parameters": self.config.require_parameters,
            "data_collection": self.config.data_collection,
            "sort": self.config.provider_sort
        }
        
        if task_type:
            task_config = self.config.raw_config.get('provider_routing', {}).get(task_type, {})
            base_config.update(task_config)
        
        return base_config

# Instância global
_config_loader = DynamicConfigLoader()

async def initialize_config_loader():
    """Inicializa carregador de configuração"""
    await _config_loader.initialize()

def get_config_loader() -> DynamicConfigLoader:
    """Retorna instância do carregador de configuração"""
    return _config_loader

def get_dynamic_config() -> Optional[LLMConfig]:
    """Retorna configuração dinâmica atual"""
    return _config_loader.get_config()

logger.info("config_loader: Carregador de configuração dinâmica YAML criado com hot-reload")