# -*- coding: utf-8 -*-
import logging
import os
from pathlib import Path
from typing import Optional, Any, Literal, List
from urllib.parse import urlparse
import re
import aiomysql # Import aiomysql for db_pool type hinting
import redis.asyncio as redis_async # Import for redis_client type hinting

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from dotenv import load_dotenv

# --- Determine Base Directory ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --- Load .env File ---
dotenv_path = BASE_DIR / ".env"
RUNNING_IN_SHOPIFY_BOT_DOCKER = os.getenv('RUNNING_IN_SHOPIFY_BOT_DOCKER', 'false').lower() == 'true'

# Determinar se deve usar arquivo .env (apenas quando NÃO está em Docker)
USE_ENV_FILE = not RUNNING_IN_SHOPIFY_BOT_DOCKER and dotenv_path.exists()

if not RUNNING_IN_SHOPIFY_BOT_DOCKER:
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path)
        logging.info(f"config.py: Loaded .env file from: {dotenv_path}")
    else:
        logging.warning(f"config.py: .env file not found at {dotenv_path}. Using environment variables or defaults.")
else:
    logging.info("config.py: Running in Shopify Bot Docker. Skipping .env file load. Relying on external environment variables.")
    # Log das variáveis de ambiente disponíveis (sem valores sensíveis)
    env_vars_to_check = ['INSTANCE_ID', 'DATABASE_URL', 'REDIS_URL', 'OPENROUTER_API_KEY', 'SITE_URL', 'LOGIN_USER']
    for var in env_vars_to_check:
        val = os.getenv(var)
        if var in ['DATABASE_URL', 'OPENROUTER_API_KEY', 'REDIS_URL']:
            logging.info(f"  ENV {var}: {'SET' if val else 'NOT SET'}")
        else:
            logging.info(f"  ENV {var}: {val if val else 'NOT SET'}")

# --- Initial Logging Setup ---
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
root_logger = logging.getLogger()
root_logger.setLevel(log_level)

logging.getLogger("httpcore").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("aiomysql").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.INFO)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)
logger.info(f"Root logging level set to: {log_level_str}")
logger.info("Log levels for httpcore, httpx, aiomysql, urllib3 set to INFO/WARNING.")

# --- Settings Class ---
# CRÍTICO: Quando em Docker (RUNNING_IN_SHOPIFY_BOT_DOCKER=true), NÃO usar arquivo .env
# O pydantic-settings deve ler APENAS das variáveis de ambiente do sistema
_env_file_setting = str(dotenv_path) if USE_ENV_FILE else None

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file_setting,
        env_file_encoding='utf-8',
        extra='ignore',
        # Prioridade: variáveis de ambiente > arquivo .env
        # Isso garante que variáveis do Easypanel sobrescrevam qualquer .env
    )

    INSTANCE_ID: str

    APP_PORT: int = 8000
    LOG_LEVEL: str = log_level_str
    SITE_URL: str = "https://localhost:8000"  # Default corrigido para HTTPS
    SITE_NAME: str = "Shopify WhatsApp Chatbot"
    CORS_ORIGINS: list[str] = ["*"]

    LOGIN_USER: str = "admin"
    LOGIN_PASSWORD: str = "password" # Esta será a senha PLANA para o usuário admin, vamos hasheá-la internamente

    # JWT Settings
    SECRET_KEY: str = "a_very_secret_key_please_change_me_in_production" # Mude isso em produção!
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # 24 horas

    # LLM Settings - Melhorado com suporte a configuração dinâmica
    LLM_MODEL_PREFERENCE: str = 'anthropic/claude-3.5-haiku'  # Modelo primário
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT: int = 90
    LLM_MAX_RETRIES: int = 3
    LLM_ENABLE_STREAMING: bool = False
    LLM_ENABLE_CACHING: bool = True
    
    # Configurações de modelos por contexto
    LLM_CONVERSATION_MODELS: List[str] = [
        "anthropic/claude-3.5-haiku",
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o"
    ]
    LLM_SCHEDULING_MODELS: List[str] = [
        "anthropic/claude-3.5-haiku",
        "openai/gpt-4o",
        "google/gemini-2.5-flash"
    ]
    LLM_FORMATTING_MODELS: List[str] = [
        "anthropic/claude-3.5-haiku",
        "openai/gpt-4o-mini",
        "google/gemini-2.5-flash"
    ]
    
    # Provider routing e fallback
    LLM_PROVIDER_SORT: Literal['price', 'throughput', 'latency'] = 'throughput'
    LLM_ALLOW_FALLBACKS: bool = True
    LLM_DATA_COLLECTION: Literal['allow', 'deny'] = 'deny'
    LLM_REQUIRE_PARAMETERS: bool = True
    
    OPENROUTER_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None  # Fallback para transcrição de áudio
    OPENROUTER_BASE_URL: str = 'https://openrouter.ai/api/v1'
    
    # Headers otimizados para OpenRouter
    APP_VERSION: str = "2.1.0"
    APP_DESCRIPTION: str = "Shopify WhatsApp AI Chatbot"
    
    TRANSCRIPTION_PREFERENCE: Literal['openai', 'openrouter'] = "openai"
    
    # Configurações de cache e rate limiting
    LLM_CACHE_TTL: int = 3600  # 1 hora
    LLM_RATE_LIMIT_PER_MINUTE: int = 60
    LLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
    LLM_CIRCUIT_BREAKER_TIMEOUT: int = 60

    REDIS_URL: str = "redis://localhost:6379/0"

    DATABASE_URL: Optional[str] = None
    db_pool: Optional[aiomysql.Pool] = None # Add db_pool directly to settings
    redis_client: Optional[redis_async.Redis] = None # Correct type hint for redis_client

    # Shopify Settings
    SHOPIFY_STORE_URL: Optional[str] = None  # Ex: "minha-loja.myshopify.com"
    SHOPIFY_ACCESS_TOKEN: Optional[str] = None  # Admin API access token
    SHOPIFY_API_VERSION: str = "2024-10"
    SHOPIFY_WEBHOOK_SECRET: Optional[str] = None  # Para validar webhooks da Shopify

    # Email settings
    SMTP_TLS: bool = True
    SMTP_PORT: Optional[int] = None
    SMTP_HOST: Optional[str] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAILS_FROM_EMAIL: Optional[str] = None
    EMAILS_FROM_NAME: Optional[str] = None
    EMAIL_TEMPLATES_DIR: Path = BASE_DIR / "src/email-templates"
    ADMIN_EMAIL: Optional[str] = None
    LOW_BALANCE_THRESHOLD: float = 5.0

    @field_validator('SMTP_PORT', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None for SMTP_PORT."""
        if v == '' or v is None:
            return None
        return v

    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    AUDIO_DIR: Path = DATA_DIR / "audio"
    FLOW_AUDIO_DIR: Path = AUDIO_DIR / "flow_stages"
    TEMP_AUDIO_DOWNLOAD_DIR: Path = DATA_DIR / "temp_audio_downloads"

    MESSAGE_BUFFER_SECONDS: int = 15  # Segundos para agrupar msgs rápidas do cliente
    MAX_HISTORY_MESSAGES_PROSPECT_STATE: int = 30  # Máximo de msgs no contexto do LLM

    def __init__(self, **values: Any):
        super().__init__(**values)
        logger.info("Validating loaded settings...")
        self._validate_required()
        self._ensure_directories()
        self._log_loaded_settings()

    def _validate_required(self):
        # Validação da URL
        if self.SITE_URL:
            # Remover qualquer caminho após o domínio para garantir que seja apenas a base da URL
            parsed_url = urlparse(self.SITE_URL)
            # Reconstruir a URL apenas com esquema, netloc (domínio:porta)
            self.SITE_URL = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            if not re.match(r'^https?://', self.SITE_URL):
                logger.warning(f"SITE_URL ('{self.SITE_URL}') is missing http:// or https:// prefix. Auto-correcting...")
                self.SITE_URL = f"https://{self.SITE_URL.lstrip('htps:/')}"
            
            logger.info(f"Final SITE_URL after validation: {self.SITE_URL}")

        if not self.INSTANCE_ID:
            logger.critical("INSTANCE_ID is not configured. Set this environment variable uniquely for each instance.")
            raise ValueError("INSTANCE_ID is required.")
        elif not re.match(r"^[a-zA-Z0-9_-]+$", self.INSTANCE_ID):
             logger.critical(f"INSTANCE_ID ('{self.INSTANCE_ID}') contains invalid characters. Use only letters, numbers, hyphens, and underscores.")
             raise ValueError("INSTANCE_ID contains invalid characters.")
        else:
            logger.info(f"INSTANCE_ID: {self.INSTANCE_ID}")

        if not self.DATABASE_URL:
            logger.critical("DATABASE_URL is not configured. Application cannot connect to the database.")
        else:
            logger.info("DATABASE_URL is configured.")

        if not self.REDIS_URL:
            logger.critical("REDIS_URL is not configured. Application cannot connect to Redis (queue/state management will fail).")
        else:
            logger.info("REDIS_URL is configured.")

        # Validação LLM
        if not self.OPENAI_API_KEY and not self.OPENROUTER_API_KEY:
            logger.warning("Nenhuma chave de API LLM (OpenAI ou OpenRouter) configurada. Funcionalidades de LLM estarão indisponíveis.")
        else:
            if self.OPENAI_API_KEY: logger.info("OPENAI_API_KEY is configured.")
            if self.OPENROUTER_API_KEY: logger.info("OPENROUTER_API_KEY is configured.")
            if self.GROQ_API_KEY: logger.info("GROQ_API_KEY is configured (fallback para transcrição).")

        if not (0.0 <= self.LLM_TEMPERATURE <= 2.0):
            logger.warning(f"LLM_TEMPERATURE ({self.LLM_TEMPERATURE}) is outside the recommended range [0.0, 2.0]. Clamping to 0.7.")
            self.LLM_TEMPERATURE = 0.7
        
        # Validação das novas configurações de LLM
        if self.LLM_MAX_TOKENS <= 0:
            logger.warning(f"LLM_MAX_TOKENS ({self.LLM_MAX_TOKENS}) deve ser positivo. Definindo para 4096.")
            self.LLM_MAX_TOKENS = 4096
            
        if self.LLM_TIMEOUT <= 0:
            logger.warning(f"LLM_TIMEOUT ({self.LLM_TIMEOUT}) deve ser positivo. Definindo para 90.")
            self.LLM_TIMEOUT = 90
            
        if not self.LLM_CONVERSATION_MODELS:
            logger.warning("LLM_CONVERSATION_MODELS está vazio. Definindo modelos padrão.")
            self.LLM_CONVERSATION_MODELS = ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"]

        if self.LOGIN_USER == "admin" and self.LOGIN_PASSWORD == "password":
            logger.warning("Using default login credentials (admin/password). CHANGE THESE IN THE .env FILE FOR SECURITY!")
        else:
            logger.info("Custom login credentials found.")
        
        # Validação Shopify
        if not self.SHOPIFY_STORE_URL or not self.SHOPIFY_ACCESS_TOKEN:
            logger.warning("SHOPIFY_STORE_URL ou SHOPIFY_ACCESS_TOKEN não configurados. Integração Shopify estará indisponível.")
        else:
            logger.info(f"Shopify configurado para loja: {self.SHOPIFY_STORE_URL}")


    def _ensure_directories(self):
        dirs_to_check = [self.DATA_DIR, self.AUDIO_DIR, self.FLOW_AUDIO_DIR, self.TEMP_AUDIO_DOWNLOAD_DIR]
        for dir_path in dirs_to_check:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Directory verified/created: {dir_path}")
            except OSError as e:
                logger.error(f"Failed to create directory {dir_path}: {e}")

    def _log_loaded_settings(self):
        logger.info("--- Application Settings Loaded ---")
        logger.info(f"  APP_PORT: {self.APP_PORT}")
        logger.info(f"  LOG_LEVEL: {self.LOG_LEVEL}")
        logger.info(f"  SITE_URL: {self.SITE_URL}")
        logger.info(f"  SITE_NAME: {self.SITE_NAME}")
        logger.info(f"  LOGIN_USER: {self.LOGIN_USER}")
        logger.info(f"  LOGIN_PASSWORD: {'Set (Hidden)' if self.LOGIN_PASSWORD else 'Not Set'}")
        logger.info(f"  SECRET_KEY: {'Set (Hidden)' if self.SECRET_KEY else 'Not Set'}")
        logger.info(f"  ALGORITHM: {self.ALGORITHM}")
        logger.info(f"  ACCESS_TOKEN_EXPIRE_MINUTES: {self.ACCESS_TOKEN_EXPIRE_MINUTES}")
        
        logger.info(f"  LLM_MODEL_PREFERENCE: {self.LLM_MODEL_PREFERENCE}")
        logger.info(f"  LLM_TEMPERATURE: {self.LLM_TEMPERATURE}")
        logger.info(f"  LLM_MAX_TOKENS: {self.LLM_MAX_TOKENS}")
        logger.info(f"  LLM_TIMEOUT: {self.LLM_TIMEOUT}s")
        logger.info(f"  LLM_ENABLE_STREAMING: {self.LLM_ENABLE_STREAMING}")
        logger.info(f"  LLM_ENABLE_CACHING: {self.LLM_ENABLE_CACHING}")
        logger.info(f"  LLM_PROVIDER_SORT: {self.LLM_PROVIDER_SORT}")
        logger.info(f"  LLM_CONVERSATION_MODELS: {len(self.LLM_CONVERSATION_MODELS)} models")
        logger.info(f"  LLM_SCHEDULING_MODELS: {len(self.LLM_SCHEDULING_MODELS)} models")
        logger.info(f"  OPENROUTER_API_KEY: {'Set' if self.OPENROUTER_API_KEY else 'Not Set'}")
        logger.info(f"  OPENAI_API_KEY: {'Set' if self.OPENAI_API_KEY else 'Not Set'}")
        logger.info(f"  GROQ_API_KEY: {'Set' if self.GROQ_API_KEY else 'Not Set'}")
        
        logger.info(f"  TRANSCRIPTION_PREFERENCE: {self.TRANSCRIPTION_PREFERENCE}")
        try:
            redis_parsed = urlparse(self.REDIS_URL)
            redis_log = f"{redis_parsed.hostname}:{redis_parsed.port or 6379}"
        except Exception:
            redis_log = "Invalid URL Format"
        logger.info(f"  REDIS_URL (Host/Port): {redis_log}")
        logger.info(f"  REDIS_CLIENT_INITIALIZED: {'Yes' if self.redis_client else 'No'}")
        try:
            db_parsed = urlparse(self.DATABASE_URL) if self.DATABASE_URL else None
            db_log = f"{db_parsed.hostname}:{db_parsed.port or 3306}/{db_parsed.path.lstrip('/')}" if db_parsed else "Not Set"
        except Exception:
            db_log = "Invalid URL Format"
        logger.info(f"  DATABASE_URL (Host/Port/DB): {db_log}")
        logger.info(f"  DB_POOL_INITIALIZED: {'Yes' if self.db_pool else 'No'}")
        logger.info(f"  SHOPIFY_STORE_URL: {self.SHOPIFY_STORE_URL or 'Not Set'}")
        logger.info(f"  SHOPIFY_ACCESS_TOKEN: {'Set' if self.SHOPIFY_ACCESS_TOKEN else 'Not Set'}")
        logger.info(f"  SHOPIFY_API_VERSION: {self.SHOPIFY_API_VERSION}")
        logger.info(f"  SHOPIFY_WEBHOOK_SECRET: {'Set' if self.SHOPIFY_WEBHOOK_SECRET else 'Not Set'}")

        logger.info(f"  BASE_DIR: {self.BASE_DIR}")
        logger.info(f"  DATA_DIR: {self.DATA_DIR}")
        logger.info(f"  MESSAGE_BUFFER_SECONDS: {self.MESSAGE_BUFFER_SECONDS}")
        logger.info(f"  MAX_HISTORY_MESSAGES_PROSPECT_STATE: {self.MAX_HISTORY_MESSAGES_PROSPECT_STATE}")
        logger.info(f"  CORS_ORIGINS: {self.CORS_ORIGINS}")
        logger.info(f"  INSTANCE_ID: {self.INSTANCE_ID}")
        logger.info("-----------------------------------")

# --- Global Settings Instance ---
try:
    settings = Settings()
    logger.info("Settings instance created successfully.")
except Exception as e:
    logger.critical(f"FATAL ERROR during settings initialization: {e}", exc_info=True)
    settings = None # type: ignore
