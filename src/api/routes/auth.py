# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from fastapi.security import OAuth2PasswordRequestForm

from src.api.routes.auth_models import Token
from src.core import security
from src.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/login", response_model=Token, tags=["Auth"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    logger.info(f"[AUTH_LOGIN] Tentativa de login para usuário: {form_data.username}")
    user = security.get_user(form_data.username) # Busca o usuário (simulado)
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        logger.warning(f"[AUTH_LOGIN] Falha no login para: {form_data.username}. Usuário ou senha inválidos.")
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    logger.info(f"[AUTH_LOGIN] Login bem-sucedido para: {user.username}. Token gerado.")
    return Token(access_token=access_token, token_type="bearer")
