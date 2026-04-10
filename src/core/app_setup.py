# src/core/app_setup.py
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi.staticfiles import StaticFiles

from src.core.config import settings, logger

# Logger specific to this module
module_logger = logging.getLogger(__name__)

# Importar o novo middleware
from src.core.middlewares import WalletBalanceCheckMiddleware


def setup_middlewares(app: FastAPI):
    """Configures middlewares for the FastAPI application."""
    module_logger.debug("app_setup.py: Adding ProxyHeadersMiddleware...")
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    module_logger.info("app_setup.py: ProxyHeadersMiddleware added.")

    module_logger.debug("app_setup.py: Adding CORS middleware...")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS if settings.CORS_ORIGINS else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    module_logger.info(f"app_setup.py: CORS middleware added. Allowed origins: {settings.CORS_ORIGINS if settings.CORS_ORIGINS else ['*']}")

    module_logger.debug("app_setup.py: Adding WalletBalanceCheckMiddleware...")
    app.add_middleware(WalletBalanceCheckMiddleware)
    module_logger.info("app_setup.py: WalletBalanceCheckMiddleware added.")

def setup_static_files(app: FastAPI):
    """Mounts static files directory and serves the index.html."""
    app.mount("/static", StaticFiles(directory="static"), name="static")
    module_logger.info("app_setup.py: Static files mounted at /static.")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        module_logger.info("app_setup.py: Serving index.html for the root path.")
        return FileResponse("static/index.html")
    module_logger.info("app_setup.py: Root path '/' configured to serve static/index.html.")

def setup_exception_handlers(app: FastAPI):
    """Registers custom exception handlers for the application."""
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        
        # Função auxiliar para garantir que todos os elementos do erro sejam serializáveis
        def make_serializable(obj):
            if isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [make_serializable(elem) for elem in obj]
            if isinstance(obj, bytes):
                try:
                    return obj.decode('utf-8')
                except UnicodeDecodeError:
                    return obj.decode('latin-1', errors='replace')
            # Converte outros tipos não-padrão (como o objeto de erro Pydantic) para string
            if not isinstance(obj, (str, int, float, bool, type(None))):
                return str(obj)
            return obj

        try:
            error_details = exc.errors()
            serializable_error_details = make_serializable(error_details)
        except Exception as e:
            # Fallback caso a extração de detalhes do erro falhe
            serializable_error_details = [{"msg": "Erro de validação complexo", "details": str(exc)}]
            module_logger.error(f"Falha ao serializar detalhes do erro de validação: {e}")

        module_logger.warning(f"Request validation error: Path='{request.url.path}', Errors='{serializable_error_details}'")
        return JSONResponse(
            status_code=422, 
            content={"detail": "Validation Error", "errors": serializable_error_details}
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        module_logger.warning(f"HTTP Exception: Status={exc.status_code}, Detail='{exc.detail}', Path='{request.url.path}'")
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=getattr(exc, 'headers', None))

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        module_logger.error(f"Unhandled exception: Path='{request.url.path}', Error='{exc}'", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": f"An unexpected internal server error occurred: {type(exc).__name__}"})
    
    module_logger.info("app_setup.py: Custom exception handlers registered.")

def setup_application_routes_and_handlers(app: FastAPI):
    """
    Sets up middlewares, static files, exception handlers, and API routers for the FastAPI app.
    """
    setup_middlewares(app)
    setup_static_files(app)
    setup_exception_handlers(app)
    
    # Import and include the API router
    from src.api.endpoints import router as api_router
    app.include_router(api_router, prefix="/api")
    module_logger.info("app_setup.py: API router included with prefix '/api'.")

module_logger.info("app_setup.py: Module loaded.")
