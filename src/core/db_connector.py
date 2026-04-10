# -*- coding: utf-8 -*-
import logging
import asyncio
from typing import List, Dict, Any, Optional

from sqlalchemy import create_engine, text, exc

logger = logging.getLogger(__name__)

def _sync_execute_query(db_url_sync: str, sql_query_sync: str) -> Optional[List[Dict[str, Any]]]:
    """
    Executa uma query SQL de forma síncrona usando SQLAlchemy.
    Esta função é destinada a ser executada em um thread separado.
    """
    logger.info(f"db_connector.py: [_sync_execute_query] Tentando conectar e executar query no DB: {db_url_sync}")
    logger.debug(f"db_connector.py: [_sync_execute_query] Query: {sql_query_sync}")
    try:
        # Modificar a URL de conexão para usar pymysql se for uma conexão mysql
        processed_db_url = db_url_sync
        if db_url_sync.startswith("mysql://"):
            processed_db_url = db_url_sync.replace("mysql://", "mysql+pymysql://", 1)
            logger.info(f"db_connector.py: [_sync_execute_query] URL de conexão MySQL modificada para usar PyMySQL: {processed_db_url}")
        
        engine = create_engine(processed_db_url)
        with engine.connect() as connection:
            result = connection.execute(text(sql_query_sync))
            # Para SQLAlchemy 1.x e 2.x, result.mappings().all() é uma forma robusta
            # de obter uma lista de dicionários.
            rows = [dict(row) for row in result.mappings().all()]
            logger.info(f"db_connector.py: [_sync_execute_query] Query executada com sucesso. {len(rows)} linhas retornadas.")
            return rows
    except exc.SQLAlchemyError as e:
        logger.error(f"db_connector.py: [_sync_execute_query] Erro de SQLAlchemy ao executar query em '{db_url_sync}': {e}", exc_info=True)
        return None
    except ImportError as e:
        # Isso pode acontecer se o driver do banco de dados não estiver instalado (ex: psycopg2 para postgresql)
        logger.error(f"db_connector.py: [_sync_execute_query] Erro de importação - driver do banco de dados para '{db_url_sync}' pode estar faltando: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"db_connector.py: [_sync_execute_query] Erro inesperado ao executar query em '{db_url_sync}': {e}", exc_info=True)
        return None

async def execute_sql_query(db_url: str, sql_query: str) -> Optional[List[Dict[str, Any]]]:
    """
    Executa uma query SQL em um banco de dados externo de forma assíncrona,
    rodando a lógica síncrona do SQLAlchemy em um thread separado.
    """
    logger.info(f"db_connector.py: [execute_sql_query] Agendando execução da query para DB: {db_url}")
    if not db_url or not sql_query:
        logger.warning("db_connector.py: [execute_sql_query] db_url ou sql_query estão vazios. Abortando.")
        return None
    try:
        # Executa a função síncrona em um thread separado para não bloquear o loop de eventos
        result = await asyncio.to_thread(_sync_execute_query, db_url, sql_query)
        return result
    except Exception as e:
        logger.error(f"db_connector.py: [execute_sql_query] Erro ao executar asyncio.to_thread: {e}", exc_info=True)
        return None

logger.info("db_connector.py: Módulo carregado.")
