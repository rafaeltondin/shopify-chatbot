# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from src.core.config import settings, logger

# Contexto para hashing de senhas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Esquema OAuth2 para obter o token do header Authorization
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login") # Ajuste tokenUrl para o endpoint de login

# --- Modelos Pydantic ---
class TokenData(BaseModel):
    username: Optional[str] = None

class User(BaseModel):
    username: str
    # Adicionar outros campos do usuário se necessário, ex: email, full_name, disabled
    # Por enquanto, apenas username para simplicidade

class UserInDB(User):
    hashed_password: str

# --- Funções de Autenticação ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha plana corresponde à senha hasheada."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Gera o hash de uma senha."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Cria um novo token de acesso JWT."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    logger.debug(f"security.py: Access token created for data: {data}, expires at: {expire.isoformat()}")
    return encoded_jwt

# --- Usuário Fixo (Simulação de Banco de Dados de Usuários) ---
# Em uma aplicação real, isso viria de um banco de dados.
# A senha 'password' será hasheada na primeira vez que get_user for chamado ou no startup.
# Por enquanto, vamos manter o usuário admin fixo aqui.
# A senha plana está em settings.LOGIN_PASSWORD

_admin_user_in_db: Optional[UserInDB] = None

def _initialize_admin_user():
    global _admin_user_in_db
    if _admin_user_in_db is None:
        hashed_password = get_password_hash(settings.LOGIN_PASSWORD)
        _admin_user_in_db = UserInDB(username=settings.LOGIN_USER, hashed_password=hashed_password)
        logger.info(f"security.py: Admin user '{settings.LOGIN_USER}' initialized with hashed password.")

# Chame isso uma vez, talvez no startup do app se este módulo for importado.
# Ou chame antes da primeira autenticação.
# _initialize_admin_user() # Será chamado implicitamente por get_user

def get_user(username: str) -> Optional[UserInDB]:
    """Busca um usuário (simulado). Em uma app real, buscaria no DB."""
    _initialize_admin_user() # Garante que o admin user esteja inicializado
    if _admin_user_in_db and username == _admin_user_in_db.username:
        return _admin_user_in_db
    return None

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    Decodifica o token JWT, valida e retorna o usuário.
    Usado como uma dependência FastAPI para proteger rotas.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: Optional[str] = payload.get("sub") # "sub" é o campo padrão para o sujeito (username)
        if username is None:
            logger.warning("security.py: Token decoding failed - username (sub) missing in payload.")
            raise credentials_exception
        token_data = TokenData(username=username)
        logger.debug(f"security.py: Token decoded successfully for username: {username}")
    except JWTError as e:
        logger.error(f"security.py: JWTError during token decoding: {e}", exc_info=True)
        raise credentials_exception
    
    user = get_user(token_data.username)
    if user is None:
        logger.warning(f"security.py: User '{token_data.username}' not found after token decoding.")
        raise credentials_exception
    
    # Aqui você poderia verificar se o usuário está ativo, se necessário
    # if user.disabled:
    #     raise HTTPException(status_code=400, detail="Inactive user")
    logger.info(f"security.py: Current user successfully identified: {user.username}")
    return User(username=user.username) # Retorna o modelo User, não UserInDB (sem o hash)

logger.info("security.py: Module loaded. CryptContext and OAuth2PasswordBearer initialized.")
