# -*- coding: utf-8 -*-
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

from src.core.config import settings, logger
from src.core.database import create_db_pool, close_db_pool, initialize_database
from src.core.db_operations.config_crud import set_config_value
from src.core import evolution, prospect as prospect_manager
from src.core.evolution import clear_evolution_cache, close_evolution_client
from src.core.shopify import initialize_shopify_client, close_shopify_client
from src.core.followup_scheduler import start_followup_scheduler, stop_followup_scheduler
from src.utils.config_loader import initialize_config_loader, get_config_loader
from src.utils.llm_utils import validate_openrouter_connection
from src.api import endpoints as api_endpoints_module


async def _perform_shutdown(startup_was_successful: bool):
    """
    Executa o processo de shutdown de forma segura.
    Só executa a limpeza completa se o startup foi bem-sucedido.
    """
    logger.info("========================================")
    logger.info("=== INITIATING APPLICATION SHUTDOWN ===")
    logger.info("========================================")

    if not startup_was_successful:
        logger.warning("[Shutdown] Startup was not successful. Performing minimal cleanup...")
        # Tentar fechar apenas os recursos que podem ter sido inicializados
        try:
            if settings.redis_client:
                await prospect_manager.close_redis()
                logger.info("[Shutdown] Redis connection closed (partial startup).")
        except Exception as e:
            logger.debug(f"[Shutdown] Error closing Redis during partial cleanup: {e}")

        try:
            await close_db_pool()
            logger.info("[Shutdown] Database pool closed (partial startup).")
        except Exception as e:
            logger.debug(f"[Shutdown] Error closing DB pool during partial cleanup: {e}")

        logger.info("========================================")
        logger.info("=== PARTIAL SHUTDOWN COMPLETE        ===")
        logger.info("========================================")
        return

    # Shutdown completo - startup foi bem-sucedido
    logger.info("[Shutdown Step 0/6] Parando follow-up scheduler...")
    try:
        await stop_followup_scheduler()
    except Exception as e:
        logger.debug(f"Error stopping followup scheduler: {e}")

    logger.info("[Shutdown Step 1/6] Iniciando desligamento...")

    logger.info("[Shutdown Step 2/6] Stopping configuration file watcher...")
    try:
        config_loader = get_config_loader()
        if config_loader:
            config_loader.stop_file_watcher()
        logger.info("[Shutdown Step 2/6] Configuration file watcher stopped.")
    except Exception as config_stop_err:
        logger.debug(f"Error stopping config loader: {config_stop_err}")

    logger.info("[Shutdown Step 2.5/6] Closing Shopify client...")
    try:
        await close_shopify_client()
        logger.info("[Shutdown Step 2.5/6] Shopify client closed.")
    except Exception as shopify_close_err:
        logger.debug(f"Error closing Shopify client: {shopify_close_err}")

    logger.info("[Shutdown Step 3/6] Closing Evolution API client...")
    try:
        await close_evolution_client()
        logger.info("[Shutdown Step 3/6] Evolution API client closed.")
    except Exception as evolution_close_err:
        logger.debug(f"Error closing Evolution API client: {evolution_close_err}")

    logger.info("[Shutdown Step 4/6] Closing Redis connection...")
    try:
        await prospect_manager.close_redis()
        logger.info("[Shutdown Step 4/6] Redis connection closed.")
    except Exception as redis_close_err:
        logger.debug(f"Error closing Redis connection: {redis_close_err}")

    logger.info("[Shutdown Step 5/6] Closing Database connection pool...")
    try:
        await close_db_pool()
        logger.info("[Shutdown Step 5/6] Database connection pool closed.")
    except Exception as db_close_err:
        logger.debug(f"Error closing Database pool: {db_close_err}")

    logger.info("[Shutdown Step 6/6] Cleanup complete.")

    logger.info("========================================")
    logger.info("=== APPLICATION SHUTDOWN COMPLETE    ===")
    logger.info("========================================")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and shutdown events."""
    logger.info("========================================")
    logger.info("===      STARTING APPLICATION        ===")
    logger.info("========================================")

    clear_evolution_cache()

    startup_successful = False
    try:
        logger.info("[Startup Step 1/5] Initializing Redis connection...")
        await prospect_manager.initialize_redis()
        if not settings.redis_client or not await settings.redis_client.ping():
            logger.error("Failed to ping Redis server after initialization.")
            raise ConnectionError("Failed to initialize or ping Redis client.")
        logger.info("[Startup Step 1/5] Redis connection initialized and ping successful.")

        logger.info("[Startup Step 2/5] Initializing Database connection pool...")
        await create_db_pool()
        logger.info("[Startup Step 2/5] Database connection pool creation attempt finished.")

        logger.info("[Startup Step 3/8] Initializing database schema and default configurations...")
        await initialize_database()
        logger.info("[Startup Step 3/8] Database schema/defaults initialization complete.")

        logger.info("[Startup Step 3.5/8] Initializing Shopify client...")
        if settings.SHOPIFY_STORE_URL and settings.SHOPIFY_ACCESS_TOKEN:
            await initialize_shopify_client(
                store_url=settings.SHOPIFY_STORE_URL,
                access_token=settings.SHOPIFY_ACCESS_TOKEN,
                api_version=settings.SHOPIFY_API_VERSION,
            )
            logger.info("[Startup Step 3.5/8] Shopify client initialized successfully.")
        else:
            logger.warning("[Startup Step 3.5/8] Shopify credentials not configured. Shopify integration disabled.")

        logger.info("[Startup Step 4/7] Initializing dynamic LLM configuration...")
        try:
            await initialize_config_loader()
            config = get_config_loader().get_config()
            if config:
                logger.info(f"Dynamic LLM configuration loaded successfully: version {config.version}")
            else:
                logger.warning("Dynamic LLM configuration not available, using static config")
        except Exception as config_err:
            logger.error(f"Failed to initialize dynamic configuration: {config_err}", exc_info=True)
            logger.warning("Continuing with static configuration")

        logger.info("[Startup Step 5/7] Validating OpenRouter connection...")
        try:
            if await validate_openrouter_connection():
                logger.info("OpenRouter connection validated successfully")
            else:
                logger.warning("OpenRouter connection validation failed")
        except Exception as openrouter_err:
            logger.error(f"Error validating OpenRouter connection: {openrouter_err}", exc_info=True)

        logger.info("[Startup Step 6/7] Setting Container URL for webhooks...")
        effective_container_url = settings.SITE_URL
        if effective_container_url and effective_container_url != "http://localhost:8000":
            logger.info(f"[Startup Step 6/7] Using container URL for webhooks: {effective_container_url}")
        else:
            logger.warning("SITE_URL not properly set in environment variables or is localhost. Webhook configuration might be skipped or use localhost.")
            effective_container_url = None
            logger.info("[Startup Step 6/7] Effective Container URL for webhook is None or localhost.")

        logger.info("[Startup Step 7/7] Configuring Evolution API Webhook (if Container URL available)...")
        if effective_container_url:
            try:
                webhook_target_url = f"{effective_container_url.rstrip('/')}/api/webhook"
                logger.info(f"Attempting to set Evolution API webhook to: {webhook_target_url}")

                logger.debug(f"About to call set_webhook_url with URL: {webhook_target_url}")
                webhook_set = await evolution.set_webhook_url(webhook_target_url)
                logger.debug(f"set_webhook_url result: {webhook_set}")
                if webhook_set:
                    logger.info("[Startup Step 7/7] Evolution API webhook configured successfully.")
                    logger.info("Attempting to get Evolution API connection state...")
                    connection_state = await evolution.get_connection_state()
                    if connection_state:
                        logger.info(f"Evolution API Instance Connection State: {connection_state}")
                    else:
                        logger.warning("Failed to get Evolution API connection state.")
                else:
                    logger.error("CRITICAL: Failed to configure Evolution API webhook (set_webhook_url returned False). Webhook events will NOT be received. Check Evolution logs and API settings.")
            except Exception as webhook_err:
                logger.error(f"CRITICAL: Error configuring Evolution webhook via API: {webhook_err}. Webhook events will NOT be received.", exc_info=True)
        else:
            logger.warning("Skipping automatic Evolution webhook configuration because Container URL is unavailable.")
            logger.info("[Startup Step 7/7] Evolution API webhook configuration skipped.")

        logger.info("[Final Step] Iniciando follow-up scheduler...")
        start_followup_scheduler()
        logger.info("[Final Step] Chatbot pronto para receber mensagens via webhook.")

        logger.info("========================================")
        logger.info("=== APPLICATION STARTUP COMPLETE     ===")
        logger.info("========================================")
        startup_successful = True

        # Yield control to the application
        yield

    except asyncio.CancelledError:
        # Shutdown foi solicitado durante o startup ou operação normal
        # Isso é esperado durante o graceful shutdown
        logger.info("[Lifespan] Received cancellation signal during lifespan.")
        raise  # Re-raise para que o Starlette saiba que foi cancelado

    except ConnectionError as conn_err:
        logger.critical(f"FATAL STARTUP ERROR (Connection): {conn_err}", exc_info=True)
        raise  # Re-raise para que o FastAPI/Uvicorn saiba que o startup falhou

    except Exception as e:
        logger.critical(f"FATAL STARTUP ERROR (General): {e}", exc_info=True)
        raise  # Re-raise para que o FastAPI/Uvicorn saiba que o startup falhou

    finally:
        # O shutdown é executado aqui, mas apenas se não foi um CancelledError
        # durante o yield (que já tratamos acima)
        try:
            await _perform_shutdown(startup_successful)
        except asyncio.CancelledError:
            # Se o shutdown também foi cancelado, fazer cleanup mínimo
            logger.warning("[Lifespan] Shutdown was cancelled. Performing emergency cleanup...")
            try:
                if settings.redis_client:
                    await settings.redis_client.close()
            except Exception:
                pass
            try:
                await close_db_pool()
            except Exception:
                pass
            logger.info("[Lifespan] Emergency cleanup completed.")
        except Exception as shutdown_err:
            logger.error(f"[Lifespan] Error during shutdown: {shutdown_err}", exc_info=True)
