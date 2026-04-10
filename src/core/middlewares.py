# -*- coding: utf-8 -*-
import logging
from fastapi import Request, HTTPException, status as http_status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Receive, Scope, Send, ASGIApp 
from starlette.responses import Response
import typing # Adicionado


from src.core.config import settings

logger = logging.getLogger(__name__)

# Definir o tipo RequestResponseCallNext para compatibilidade
RequestResponseCallNext = typing.Callable[[Request], typing.Awaitable[Response]]


class WalletBalanceCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseCallNext) -> Response:
        # Caminhos que NÃO devem ser verificados pelo middleware de saldo
        # (ex: login, webhook do MP, a própria página da wallet, status da app)
        exempt_paths = [
            "/api/login",
            "/api/wallet/mercado-pago/webhook", # Webhook do Mercado Pago
            "/api/wallet/balance", # Permitir verificar o saldo
            "/api/wallet/history", # Permitir ver histórico
            "/api/wallet/add-credit/initiate", # Permitir iniciar recarga
            "/api/status", # Status da aplicação
            "/static/", # Arquivos estáticos
            "/docs", "/openapi.json", "/redoc", # Documentação da API
            "/" # Rota raiz que serve o index.html
        ]

        # Verifica se o path da requisição começa com algum dos paths isentos
        is_exempt = any(request.url.path.startswith(p) for p in exempt_paths)
        
        # Adicionar lógica para permitir acesso à página de wallet no frontend mesmo sem saldo
        # O frontend fará chamadas para /api/wallet/* para carregar dados.
        # Se a rota for para a API da wallet, não bloquear aqui, pois a UI precisa carregar.
        # O bloqueio real de funcionalidade (ex: enviar mensagem) deve ser no endpoint específico ou lógica de negócio.
        # Este middleware é mais para um bloqueio geral de acesso a funcionalidades críticas.

        if is_exempt:
            logger.debug(f"MIDDLEWARE: Rota {request.url.path} isenta da verificação de saldo.")
            response = await call_next(request)
            return response

        # Para outras rotas, verificar o saldo
        # Obter instance_id: Em um sistema multi-tenant real, isso viria do token JWT (current_user)
        # ou de um header específico da instância.
        # Para este projeto, que parece ser single-instance por deploy (baseado em INSTANCE_ID no .env),
        # usamos settings.INSTANCE_ID.
        instance_id = settings.INSTANCE_ID
        
        # Usar a função real de wallet_manager quando disponível
        from src.core import wallet_manager # Importar aqui para usar a função real
        balance = await wallet_manager.get_wallet_balance(instance_id)


        if balance is not None and balance <= 0:
            logger.warning(f"MIDDLEWARE: Saldo insuficiente (R${balance}) para instance_id {instance_id} na rota {request.url.path}. Bloqueando acesso.")
            # Retornar uma resposta JSON com status 402
            # O frontend (api.js) deve ser capaz de capturar este status e exibir o popup.
            return JSONResponse(
                status_code=http_status.HTTP_402_PAYMENT_REQUIRED,
                content={"detail": "Seus créditos acabaram. Por favor, recarregue para continuar usando o sistema."}
            )
        
        logger.debug(f"MIDDLEWARE: Saldo suficiente (R${balance}) para instance_id {instance_id} na rota {request.url.path}. Acesso permitido.")
        response = await call_next(request)
        return response

logger.info("middlewares.py: Módulo carregado.")
