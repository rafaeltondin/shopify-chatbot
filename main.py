# -*- coding: utf-8 -*-
import uvicorn
from fastapi import FastAPI # Request e HTTPException removidos, FastAPI duplicado removido

# --- Project Imports ---
from src.core.config import settings, logger
from src.core.lifespan import lifespan # Import the new lifespan
from src.core.app_setup import setup_application_routes_and_handlers # Import the setup function

# --- FastAPI App Instance ---
logger.debug("main.py: Creating FastAPI application instance...")
app = FastAPI(
    title=settings.SITE_NAME,
    version="1.0.0",
    lifespan=lifespan,
    description="Shopify WhatsApp Chatbot - Atendimento ao cliente com IA e integração Shopify.",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)
logger.info(f"main.py: FastAPI app created: Title='{settings.SITE_NAME}', Version='1.0.0'")

# Setup middlewares, static files, exception handlers, and API router
setup_application_routes_and_handlers(app)

# --- Main Execution Block ---
if __name__ == "__main__":
    # Simplified Uvicorn run call
    log_level_name = settings.LOG_LEVEL.lower()
    uvicorn_log_levels = ['critical', 'error', 'warning', 'info', 'debug', 'trace']
    uvicorn_log_level = log_level_name if log_level_name in uvicorn_log_levels else 'info'

    logger.info("========================================")
    logger.info(f" main.py: Preparing to start Uvicorn server...")
    logger.info(f" main.py: Host: 0.0.0.0")
    logger.info(f" main.py: Port: {settings.APP_PORT}")
    logger.info(f" main.py: Application Entrypoint: main:app")
    logger.info(f" main.py: Uvicorn Log Level: {uvicorn_log_level}")
    logger.info(f" main.py: Reload Disabled (set reload=True for development)")
    logger.info("========================================")

    try:
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=int(settings.APP_PORT),
            reload=False,
            log_level=uvicorn_log_level,
        )
    except TypeError as e:
        if 'must be integer' in str(e).lower():
             logger.critical(f"main.py: Configuration Error: APP_PORT ('{settings.APP_PORT}') must be an integer. Please check your .env or environment variables.", exc_info=True)
        else:
             logger.critical(f"main.py: TypeError during Uvicorn startup: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"main.py: Failed to start Uvicorn server: {e}", exc_info=True)

    logger.info("main.py: Uvicorn server has stopped.")
