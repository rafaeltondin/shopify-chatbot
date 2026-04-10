# -*- coding: utf-8 -*-
import logging
import aiomysql
import aiomysql
from typing import List

from src.core.config import logger

logger = logging.getLogger(__name__)

async def check_column_exists(cursor: aiomysql.DictCursor, db_name: str, table_name: str, column_name: str) -> bool:
    logger.debug(f"db_operations.schema_management: Checking if column '{column_name}' exists in '{table_name}'.")
    sql = "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s LIMIT 1;"
    try:
        await cursor.execute(sql, (db_name, table_name, column_name))
        result = await cursor.fetchone()
        logger.debug(f"db_operations.schema_management: Column '{column_name}' exists in '{table_name}': {result is not None}.")
        return result is not None
    except aiomysql.Error as e:
        logger.error(f"db_operations.schema_management: Error checking if column '{column_name}' exists in '{table_name}': {e}", exc_info=True)
        return False

async def add_column_if_not_exists(cursor: aiomysql.DictCursor, db_name: str, table_name: str, column_name: str, column_definition: str):
    logger.debug(f"db_operations.schema_management: Attempting to add column '{column_name}' to '{table_name}' if not exists.")
    if not await check_column_exists(cursor, db_name, table_name, column_name):
        sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {column_definition};"
        try:
            logger.info(f"db_operations.schema_management: Column '{column_name}' not found in '{table_name}'. Attempting to add...")
            await cursor.execute(sql)
            logger.info(f"db_operations.schema_management: Successfully added column '{column_name}' to table '{table_name}'.")
        except Exception as e:
             logger.error(f"db_operations.schema_management: Error adding column '{column_name}' to table '{table_name}': {e}", exc_info=True)
    else:
        logger.debug(f"db_operations.schema_management: Column '{column_name}' already exists in '{table_name}'. Skipping add.")

async def check_index_exists(cursor: aiomysql.DictCursor, db_name: str, table_name: str, index_name: str) -> bool:
    logger.debug(f"db_operations.schema_management: Checking if index '{index_name}' exists on '{table_name}'.")
    sql = "SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = %s LIMIT 1;"
    try:
        await cursor.execute(sql, (db_name, table_name, index_name))
        result = await cursor.fetchone()
        logger.debug(f"db_operations.schema_management: Index '{index_name}' exists on '{table_name}': {result is not None}.")
        return result is not None
    except aiomysql.Error as e:
        logger.error(f"db_operations.schema_management: Error checking if index '{index_name}' exists on '{table_name}': {e}", exc_info=True)
        return False

async def add_index_if_not_exists(cursor: aiomysql.DictCursor, db_name: str, table_name: str, index_name: str, index_definition: str):
    logger.debug(f"db_operations.schema_management: Attempting to add index '{index_name}' to '{table_name}' if not exists.")
    if not await check_index_exists(cursor, db_name, table_name, index_name):
        sql = f"ALTER TABLE `{table_name}` ADD INDEX `{index_name}` {index_definition};"
        try:
            logger.info(f"db_operations.schema_management: Index '{index_name}' not found on '{table_name}'. Attempting to add...")
            await cursor.execute(sql)
            logger.info(f"db_operations.schema_management: Successfully added index '{index_name}' to table '{table_name}'.")
        except Exception as e:
             logger.error(f"db_operations.schema_management: Error adding index '{index_name}' to table '{table_name}': {e}", exc_info=True)
    else:
        logger.debug(f"db_operations.schema_management: Index '{index_name}' already exists in '{table_name}'. Skipping add.")

async def update_primary_key_if_needed(cursor: aiomysql.DictCursor, db_name: str, table_name: str, expected_cols: List[str]):
    logger.debug(f"db_operations.schema_management: Checking/updating primary key for '{table_name}'.")
    get_pk_cols_sql = "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME = 'PRIMARY' ORDER BY ORDINAL_POSITION;"
    try:
        await cursor.execute(get_pk_cols_sql, (db_name, table_name))
        current_pk_cols = [row['COLUMN_NAME'] for row in await cursor.fetchall()]
        if current_pk_cols != expected_cols:
            logger.info(f"db_operations.schema_management: Primary key on '{table_name}' needs update. Current: {current_pk_cols}, Expected: {expected_cols}. Attempting update...")
            if current_pk_cols:
                await cursor.execute(f"ALTER TABLE `{table_name}` DROP PRIMARY KEY;")
                logger.info(f"db_operations.schema_management: Dropped existing primary key for '{table_name}'.")
            pk_definition = ", ".join([f"`{col}`" for col in expected_cols])
            await cursor.execute(f"ALTER TABLE `{table_name}` ADD PRIMARY KEY ({pk_definition});")
            logger.info(f"db_operations.schema_management: Successfully updated primary key for '{table_name}'.")
        else:
            logger.debug(f"db_operations.schema_management: Primary key on '{table_name}' is already correct ({current_pk_cols}).")
    except aiomysql.Error as e:
        logger.error(f"db_operations.schema_management: Error checking/updating primary key for '{table_name}': {e}", exc_info=True)

async def modify_column_type_if_different(
    cursor: aiomysql.DictCursor, 
    db_name: str, 
    table_name: str, 
    column_name: str, 
    expected_column_type_name: str, # ex: 'mediumtext'
    new_column_full_definition: str # ex: 'MEDIUMTEXT COMMENT \'New comment\''
):
    """
    Verifica o tipo de dados de uma coluna e a modifica se for diferente do esperado.
    """
    logger.debug(f"schema_management: Verificando tipo da coluna '{column_name}' na tabela '{table_name}'. Esperado (nome base): '{expected_column_type_name}'")
    try:
        get_type_sql = """
            SELECT DATA_TYPE 
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """
        await cursor.execute(get_type_sql, (db_name, table_name, column_name))
        result = await cursor.fetchone()

        if not result:
            logger.warning(f"schema_management: Coluna '{column_name}' não encontrada na tabela '{table_name}'. Não é possível modificar o tipo.")
            return

        current_data_type = result.get('DATA_TYPE')
        if not current_data_type:
            logger.warning(f"schema_management: Não foi possível obter o DATA_TYPE da coluna '{column_name}' na tabela '{table_name}'.")
            return

        logger.info(f"schema_management: Tipo atual da coluna '{table_name}.{column_name}' é '{current_data_type}'.")

        if current_data_type.lower() != expected_column_type_name.lower():
            logger.info(f"schema_management: Tipo da coluna '{table_name}.{column_name}' ('{current_data_type}') é diferente do esperado ('{expected_column_type_name}'). Tentando alterar para '{new_column_full_definition}'...")
            alter_sql = f"ALTER TABLE `{table_name}` MODIFY COLUMN `{column_name}` {new_column_full_definition};"
            logger.debug(f"schema_management: Executando SQL de alteração: {alter_sql}")
            await cursor.execute(alter_sql)
            logger.info(f"schema_management: Coluna '{table_name}.{column_name}' alterada com sucesso para '{new_column_full_definition}'.")
        else:
            logger.info(f"schema_management: Tipo da coluna '{table_name}.{column_name}' ('{current_data_type}') já é o esperado ('{expected_column_type_name}'). Nenhuma alteração necessária.")

    except aiomysql.Error as e:
        logger.error(f"schema_management: Erro de MySQL ao tentar modificar coluna '{table_name}.{column_name}': {e}", exc_info=True)
    except Exception as e:
        logger.error(f"schema_management: Erro inesperado ao tentar modificar coluna '{table_name}.{column_name}': {e}", exc_info=True)

logger.info("db_operations.schema_management: Module loaded.")
