# -*- coding: utf-8 -*-
import logging
import aiomysql
import pymysql.err
import json
import asyncio
import random
from typing import Optional, Any, Dict, List, Tuple, Literal, Callable
from datetime import datetime
import pytz

from src.core.config import settings, logger

logger = logging.getLogger(__name__)

# Timezone padrão: America/Sao_Paulo (GMT-3)
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

def _now() -> datetime:
    """Retorna datetime atual no timezone de São Paulo (GMT-3)."""
    return datetime.now(SAO_PAULO_TZ)

# ==================== FASE 2: RETRY MECHANISM ====================
# ==================== FASE 4: METRICS TRACKING ====================

# Métricas globais de retry para monitoramento
_retry_metrics = {
    "total_operations": 0,
    "total_retries": 0,
    "total_successes": 0,
    "total_failures": 0,
    "lock_timeouts_1205": 0,
    "deadlocks_1213": 0,
    "lost_connections_2013": 0,
    "max_retries_reached": 0
}

def get_retry_metrics() -> Dict[str, int]:
    """Retorna métricas de retry para monitoramento"""
    return _retry_metrics.copy()

def reset_retry_metrics():
    """Reseta métricas de retry"""
    global _retry_metrics
    _retry_metrics = {
        "total_operations": 0,
        "total_retries": 0,
        "total_successes": 0,
        "total_failures": 0,
        "lock_timeouts_1205": 0,
        "deadlocks_1213": 0,
        "lost_connections_2013": 0,
        "max_retries_reached": 0
    }
    logger.info("✅ Retry metrics reset")

async def execute_with_retry(
    operation: Callable,
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
    jid: str = "unknown"
) -> Any:
    """
    Executa operação de DB com retry exponencial e jitter.

    Args:
        operation: Função async a ser executada
        max_retries: Número máximo de tentativas (padrão: 3)
        base_delay: Delay base em segundos (padrão: 0.1s)
        max_delay: Delay máximo em segundos (padrão: 2.0s)
        jid: Identificador para logging

    Returns:
        Resultado da operação

    Raises:
        Exception: Se todas as tentativas falharem
    """
    global _retry_metrics
    _retry_metrics["total_operations"] += 1
    last_exception = None
    operation_start_time = _now()

    for attempt in range(max_retries):
        try:
            result = await operation()

            # ✅ FASE 4: Logging de sucesso com métricas
            if attempt > 0:
                _retry_metrics["total_retries"] += attempt
                elapsed_time = (_now() - operation_start_time).total_seconds()
                logger.info(
                    f"[{jid}] ✅ DB operation succeeded after {attempt} retries "
                    f"(total time: {elapsed_time:.2f}s)"
                )

            _retry_metrics["total_successes"] += 1
            return result

        except (aiomysql.OperationalError, pymysql.err.OperationalError) as e:
            error_code = e.args[0] if e.args else 0

            # Erros que justificam retry: deadlock (1213), lock timeout (1205), lost connection (2013)
            if error_code not in [1205, 1213, 2013]:
                logger.error(f"[{jid}] Non-retryable DB error {error_code}: {e}")
                _retry_metrics["total_failures"] += 1
                raise

            # ✅ FASE 4: Rastrear tipo de erro específico
            if error_code == 1205:
                _retry_metrics["lock_timeouts_1205"] += 1
            elif error_code == 1213:
                _retry_metrics["deadlocks_1213"] += 1
            elif error_code == 2013:
                _retry_metrics["lost_connections_2013"] += 1
                logger.warning(f"[{jid}] Lost connection to MySQL, will retry...")

            last_exception = e

            if attempt == max_retries - 1:
                _retry_metrics["max_retries_reached"] += 1
                _retry_metrics["total_failures"] += 1
                elapsed_time = (_now() - operation_start_time).total_seconds()
                logger.error(
                    f"[{jid}] ❌ Max retries ({max_retries}) reached for DB operation "
                    f"(error {error_code}, total time: {elapsed_time:.2f}s)"
                )
                raise

            # Exponential backoff com jitter aleatório
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.1), max_delay)
            logger.warning(
                f"[{jid}] ⚠️ DB operation failed (error {error_code}), "
                f"retry {attempt + 1}/{max_retries} after {delay:.2f}s"
            )
            await asyncio.sleep(delay)

        except Exception as e:
            # Outros tipos de exceção não fazem retry
            logger.error(f"[{jid}] Unexpected error in DB operation: {e}", exc_info=True)
            _retry_metrics["total_failures"] += 1
            raise

    # Se chegou aqui, todas as tentativas falharam
    if last_exception:
        raise last_exception

# ================================================================

async def get_prospects_list(status: Optional[str]=None, stage: Optional[int]=None, jid_search: Optional[str]=None, limit: int=50, offset: int=0, funnel_id: Optional[str]=None, include_null_funnel: bool = True) -> Tuple[List[Dict[str, Any]], int]:
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available. Cannot fetch prospect list.")
        return [], 0
    base_sql = "FROM prospects WHERE instance_id = %s"; count_sql = "SELECT COUNT(*) as total "; data_sql = "SELECT jid, name, cpf, full_name, birth_date, current_stage, status, llm_paused, last_interaction_at, created_at, tags, funnel_id "
    order_sql = " ORDER BY updated_at DESC LIMIT %s OFFSET %s"; where_clauses = []; params = [settings.INSTANCE_ID]
    if status: where_clauses.append("status = %s"); params.append(status)
    if stage is not None: where_clauses.append("current_stage = %s"); params.append(stage)
    if jid_search: where_clauses.append("jid LIKE %s"); params.append(f"%{jid_search}%")
    # CORREÇÃO: Incluir prospects sem funnel_id (NULL) junto com o funil especificado
    # Isso garante que leads antigos sem funil apareçam no kanban
    if funnel_id is not None:
        if include_null_funnel:
            where_clauses.append("(funnel_id = %s OR funnel_id IS NULL)")
        else:
            where_clauses.append("funnel_id = %s")
        params.append(funnel_id)
    if where_clauses: base_sql += " AND " + " AND ".join(where_clauses)
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(count_sql + base_sql, tuple(params))
            total_count = (await cursor.fetchone())['total'] or 0
            params_for_data = list(params)
            params_for_data.extend([limit, offset])
            await cursor.execute(data_sql + base_sql + order_sql, tuple(params_for_data))
            prospects = await cursor.fetchall()
            sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
            for p in prospects:
                if p.get('last_interaction_at'):
                    dt_utc = pytz.utc.localize(p['last_interaction_at'])
                    dt_sao_paulo = dt_utc.astimezone(sao_paulo_tz)
                    p['last_interaction_at'] = dt_sao_paulo.isoformat()
                if p.get('created_at'):
                    dt_utc = pytz.utc.localize(p['created_at'])
                    dt_sao_paulo = dt_utc.astimezone(sao_paulo_tz)
                    p['created_at'] = dt_sao_paulo.isoformat()
                # Parse tags JSON to list
                tags_raw = p.get('tags')
                if tags_raw:
                    try:
                        p['tags'] = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                    except:
                        p['tags'] = []
                else:
                    p['tags'] = []
                # Formatar birth_date para string ISO se existir
                if p.get('birth_date'):
                    p['birth_date'] = p['birth_date'].isoformat() if hasattr(p['birth_date'], 'isoformat') else str(p['birth_date'])
            logger.info(f"db_operations.prospect_crud: Fetched {len(prospects)} prospects out of {total_count} total.")
            return prospects, total_count
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error fetching prospect list: {e}", exc_info=True)
        return [],0

async def get_prospect_conversation_history(jid: str, instance_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available. Cannot fetch conversation history.")
        return []
    sql = "SELECT role, content, timestamp, llm_model, prompt_tokens, completion_tokens, total_tokens FROM conversation_history WHERE instance_id = %s AND prospect_jid = %s ORDER BY timestamp ASC"
    params = [instance_id, jid]
    if limit: sql += " LIMIT %s"; params.append(limit)
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            history = await cursor.fetchall()
            for item in history:
                if item.get('timestamp'): item['timestamp'] = item['timestamp'].isoformat()
            logger.info(f"db_operations.prospect_crud: Fetched {len(history)} history entries for JID '{jid}'.")
            return history
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error fetching history for {jid}: {e}", exc_info=True)
        return []

async def get_prospect_db_status(jid: str, instance_id: str) -> Optional[str]:
    logger.debug(f"db_operations.prospect_crud: Getting prospect status for JID '{jid}' for instance '{instance_id}'.")
    if not settings.db_pool:
        logger.warning("db_operations.prospect_crud: Database pool not available. Cannot get prospect status.")
        return None
    sql = "SELECT status FROM prospects WHERE instance_id = %s AND jid = %s"
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, jid))
            result = await cursor.fetchone()
            status = result['status'] if result else None
            logger.debug(f"db_operations.prospect_crud: Status for JID '{jid}': {status}.")
            return status
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error fetching status for {jid}: {e}", exc_info=True)
        return None

async def get_prospect_stage(jid: str, instance_id: str) -> Optional[int]:
    logger.debug(f"db_operations.prospect_crud: Getting prospect stage for JID '{jid}' for instance '{instance_id}'.")
    if not settings.db_pool:
        logger.warning("db_operations.prospect_crud: Database pool not available. Cannot get prospect stage.")
        return None
    sql = "SELECT current_stage FROM prospects WHERE instance_id = %s AND jid = %s"
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, jid))
            result = await cursor.fetchone()
            stage = result['current_stage'] if result else None
            logger.debug(f"db_operations.prospect_crud: Current stage for JID '{jid}': {stage}.")
            return stage
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error fetching stage for {jid}: {e}", exc_info=True)
        return None

# ==================== FASE 3: OPTIMISTIC LOCKING ====================

async def get_prospect_version(jid: str, instance_id: str) -> int:
    """
    Retorna a versão atual do prospect no DB para optimistic locking.

    Args:
        jid: Identificador do prospect
        instance_id: ID da instância

    Returns:
        Número da versão atual (0 se não encontrado)
    """
    logger.debug(f"db_operations.prospect_crud: Getting version for JID '{jid}'.")
    if not settings.db_pool:
        logger.warning("db_operations.prospect_crud: Database pool not available.")
        return 0

    sql = "SELECT version FROM prospects WHERE instance_id = %s AND jid = %s"
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, jid))
            result = await cursor.fetchone()
            version = result['version'] if result else 0
            logger.debug(f"db_operations.prospect_crud: Version for JID '{jid}': {version}.")
            return version
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: Error fetching version for {jid}: {e}", exc_info=True)
        return 0

async def update_prospect_stage_with_version(
    jid: str,
    instance_id: str,
    new_stage: int,
    expected_version: int,
    status: str = 'active'
) -> bool:
    """
    Atualiza estágio do prospect usando optimistic locking.

    Args:
        jid: Identificador do prospect
        instance_id: ID da instância
        new_stage: Novo estágio
        expected_version: Versão esperada (para verificar conflito)
        status: Status a ser definido (padrão: 'active')

    Returns:
        True se update foi bem-sucedido, False se houve conflito de versão
    """
    logger.info(f"db_operations.prospect_crud: Updating stage for '{jid}' to {new_stage} with version check (expected: {expected_version}).")
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available.")
        return False

    # ✅ FASE 3: Encapsular para usar com retry
    async def _do_operation():
        now_utc = _now()
        sql = """
            UPDATE prospects
            SET current_stage = %s,
                status = %s,
                last_interaction_at = %s,
                updated_at = %s,
                version = version + 1
            WHERE instance_id = %s
            AND jid = %s
            AND version = %s
        """

        async with settings.db_pool.acquire() as conn:
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql, (new_stage, status, now_utc, now_utc, instance_id, jid, expected_version))
                    rows_affected = cursor.rowcount

                    if not conn.get_autocommit():
                        await conn.commit()

                    if rows_affected == 0:
                        logger.warning(f"db_operations.prospect_crud: ⚠️ Optimistic lock conflict for '{jid}' - version mismatch (expected: {expected_version})")
                        return False

                    logger.info(f"db_operations.prospect_crud: ✅ Prospect '{jid}' updated to stage {new_stage} with version increment")
                    return True

            except Exception as e:
                if not conn.get_autocommit():
                    try:
                        await conn.rollback()
                    except Exception as rb_err:
                        logger.error(f"db_operations.prospect_crud: Rollback failed: {rb_err}")
                raise

    # ✅ FASE 3: Executar com retry
    try:
        return await execute_with_retry(_do_operation, jid=jid)
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: Error updating prospect '{jid}' with version: {e}", exc_info=True)
        return False

# ================================================================

async def add_or_update_prospect_db(jid: str, instance_id: Optional[str] = None, **kwargs: Any):
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    if not settings.db_pool:
        logger.error(f"db_operations.prospect_crud: Database pool not available. Cannot add/update prospect '{jid}'.")
        return

    # ✅ FASE 2: Encapsular lógica em função para usar com retry
    async def _do_operation():
        now_utc = _now()

        all_table_fields = [
            'jid', 'instance_id', 'name', 'cpf', 'full_name', 'birth_date',
            'current_stage', 'status', 'llm_paused', 'conversation_initiator',
            'last_interaction_at', 'created_at', 'updated_at', 'funnel_id'
        ]

        insert_fields = {
            'instance_id': instance_id,
            'jid': jid,
            'created_at': now_utc,
            'updated_at': now_utc,
            'last_interaction_at': now_utc,
            'current_stage': 1,
            'status': 'active',
            'llm_paused': False,
            'name': None,
            'conversation_initiator': None
        }
        for key, value in kwargs.items():
            if key in all_table_fields:
                insert_fields[key] = value

        insert_fields['updated_at'] = now_utc
        if 'last_interaction_at' not in kwargs:
            insert_fields['last_interaction_at'] = now_utc

        insert_cols = ", ".join([f"`{k}`" for k in insert_fields.keys()])
        insert_placeholders = ", ".join(["%s"] * len(insert_fields))
        params = list(insert_fields.values())

        update_assignments = []
        for key in kwargs:
            if key in all_table_fields and key not in ['jid', 'instance_id', 'created_at']:
                if key == 'conversation_initiator':
                    update_assignments.append("`conversation_initiator` = COALESCE(prospects.conversation_initiator, NEW.conversation_initiator)")
                else:
                    update_assignments.append(f"`{key}` = NEW.`{key}`")

        update_assignments.append("`updated_at` = NEW.`updated_at`")

        update_assignments_str = ",\n        ".join(sorted(list(set(update_assignments))))

        if not update_assignments_str.strip() or not any(k in kwargs for k in all_table_fields if k not in ['jid', 'instance_id', 'created_at']):
            update_assignments_str = "`updated_at` = NEW.`updated_at`"

        sql = f"""
            INSERT INTO prospects ({insert_cols})
            VALUES ({insert_placeholders}) AS NEW
            ON DUPLICATE KEY UPDATE
                {update_assignments_str}
        """

        logger.debug(f"db_operations.prospect_crud: Attempting to add/update prospect: JID='{jid}' with data: {kwargs}")

        # ✅ FASE 2: Tratamento de transação com rollback
        async with settings.db_pool.acquire() as conn:
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql, tuple(params))
                    # Com autocommit=True, não precisa de commit manual
                    # Mas mantemos compatibilidade para caso autocommit seja desabilitado
                    if not conn.get_autocommit():
                        await conn.commit()
                logger.info(f"db_operations.prospect_crud: Prospect '{jid}' added/updated successfully in DB.")
            except Exception as e:
                # Rollback apenas se autocommit estiver desabilitado
                if not conn.get_autocommit():
                    try:
                        await conn.rollback()
                        logger.warning(f"db_operations.prospect_crud: Transaction rolled back for '{jid}'")
                    except Exception as rb_err:
                        logger.error(f"db_operations.prospect_crud: Rollback failed for '{jid}': {rb_err}")
                raise

    # ✅ FASE 2: Executar com retry automático
    try:
        await execute_with_retry(_do_operation, jid=jid)
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error inserting/updating prospect {jid}: {e}", exc_info=True)
        raise

async def update_prospect_status_db(jid: str, status: str, instance_id: Optional[str] = None):
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    logger.info(f"db_operations.prospect_crud: Updating status for prospect '{jid}' to '{status}' for instance '{instance_id}'.")
    if not settings.db_pool:
        logger.error(f"db_operations.prospect_crud: Database pool not available. Cannot update prospect status for '{jid}'.")
        return

    # ✅ FASE 2: Encapsular para usar com retry
    async def _do_operation():
        now_utc = _now()
        sql = "UPDATE prospects SET status = %s, last_interaction_at = %s WHERE instance_id = %s AND jid = %s"

        async with settings.db_pool.acquire() as conn:
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql, (status, now_utc, instance_id, jid))
                    if not conn.get_autocommit():
                        await conn.commit()
                logger.info(f"db_operations.prospect_crud: Status for prospect '{jid}' updated to '{status}' successfully.")
            except Exception as e:
                if not conn.get_autocommit():
                    try:
                        await conn.rollback()
                    except Exception as rb_err:
                        logger.error(f"db_operations.prospect_crud: Rollback failed: {rb_err}")
                raise

    # ✅ FASE 2: Executar com retry
    try:
        await execute_with_retry(_do_operation, jid=jid)
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error updating status for {jid} to {status}: {e}", exc_info=True)

async def update_prospect_llm_pause_status_db(jid: str, llm_paused: bool, instance_id: Optional[str] = None):
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    logger.info(f"db_operations.prospect_crud: Updating LLM pause status for prospect '{jid}' to '{llm_paused}' for instance '{instance_id}'.")
    if not settings.db_pool:
        logger.error(f"db_operations.prospect_crud: Database pool not available. Cannot update LLM pause status for '{jid}'.")
        return False
    now_utc = _now()
    sql = "UPDATE prospects SET llm_paused = %s, updated_at = %s WHERE instance_id = %s AND jid = %s"
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (llm_paused, now_utc, instance_id, jid))
            await conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"db_operations.prospect_crud: LLM pause status for prospect '{jid}' updated to '{llm_paused}' successfully.")
                return True
            else:
                logger.warning(f"db_operations.prospect_crud: Prospect '{jid}' not found or no change in LLM pause status for instance '{instance_id}'.")
                return False
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error updating LLM pause status for {jid} to {llm_paused}: {e}", exc_info=True)
        return False

async def add_history_entry_db(
    jid: str, role: str, content: str, instance_id: Optional[str] = None,
    stage: Optional[int]=None, message_id: Optional[str]=None,
    llm_model: Optional[str]=None, prompt_tokens: Optional[int]=None,
    completion_tokens: Optional[int]=None, total_tokens: Optional[int]=None,
    conversation_initiator: Optional[Literal['user', 'llm_agent']] = None
):
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    logger.info(f"db_operations.prospect_crud: Adding history entry for JID '{jid}', Role '{role}', Stage '{stage}', Initiator '{conversation_initiator}' for instance '{instance_id}'.")
    if not settings.db_pool:
        logger.error(f"db_operations.prospect_crud: Database pool not available. Cannot add history entry for '{jid}'.")
        return
    
    now_utc = _now()
    sql = """
        INSERT INTO conversation_history 
        (instance_id, prospect_jid, role, content, stage_at_message, message_id, timestamp, 
        llm_model, prompt_tokens, completion_tokens, total_tokens, conversation_initiator) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        instance_id, jid, role, content, stage, message_id, now_utc, 
        llm_model, prompt_tokens, completion_tokens, total_tokens, conversation_initiator
    )
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, params)
            await conn.commit()
        logger.info(f"db_operations.prospect_crud: History entry added successfully for '{jid}'.")

    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error adding history for {jid}: {e}", exc_info=True)

async def get_total_token_usage(instance_id: Optional[str] = None, initiator: Optional[Literal['user', 'llm_agent']] = None) -> Dict[str, int]:
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    logger.info(f"db_operations.prospect_crud: Calculating total token usage for instance '{instance_id}', initiator: {initiator}.")
    if not settings.db_pool:
        logger.warning("db_operations.prospect_crud: Database pool not available. Cannot calculate token usage. Returning zeros.")
        return totals
    sql = "SELECT SUM(prompt_tokens) as total_prompt, SUM(completion_tokens) as total_completion, SUM(total_tokens) as grand_total FROM conversation_history WHERE instance_id = %s AND total_tokens IS NOT NULL"
    params = [instance_id]
    if initiator:
        sql += " AND conversation_initiator = %s"
        params.append(initiator)
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            result = await cursor.fetchone()
            if result:
                totals["prompt_tokens"] = int(result.get("total_prompt") or 0)
                totals["completion_tokens"] = int(result.get("total_completion") or 0)
                totals["total_tokens"] = int(result.get("grand_total") or 0)
        logger.info(f"db_operations.prospect_crud: Total token usage for instance '{instance_id}', initiator: {initiator}: {totals}.")
        return totals
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error calculating total token usage for instance '{instance_id}', initiator: {initiator}: {e}", exc_info=True)
        return totals

async def clear_all_leads_from_db(instance_id: str) -> int:
    logger.info(f"db_operations.prospect_crud: Attempting to delete all leads for instance_id '{instance_id}'.")
    if not settings.db_pool:
        logger.error(f"db_operations.prospect_crud: Database pool not available. Cannot clear leads for instance '{instance_id}'.")
        return 0
    sql = "DELETE FROM prospects WHERE instance_id = %s"
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id,))
            rows_deleted = cursor.rowcount
            await conn.commit()
            logger.info(f"db_operations.prospect_crud: Successfully deleted {rows_deleted} leads for instance_id '{instance_id}'.")
            return rows_deleted
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error clearing leads for instance '{instance_id}': {e}", exc_info=True)
        return 0

async def clear_all_conversations_from_db(instance_id: str) -> int:
    logger.info(f"db_operations.prospect_crud: Attempting to delete all conversation history for instance_id '{instance_id}'.")
    if not settings.db_pool:
        logger.error(f"db_operations.prospect_crud: Database pool not available. Cannot clear conversation history for instance '{instance_id}'.")
        return 0
    sql = "DELETE FROM conversation_history WHERE instance_id = %s"
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id,))
            rows_deleted = cursor.rowcount
            await conn.commit()
            logger.info(f"db_operations.prospect_crud: Successfully deleted {rows_deleted} conversation history entries for instance_id '{instance_id}'.")
            return rows_deleted
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error clearing conversation history for instance '{instance_id}': {e}", exc_info=True)
        return 0

async def clear_all_token_usage_from_db(instance_id: str) -> int:
    logger.info(f"db_operations.prospect_crud: Token usage is stored within 'conversation_history' table for instance_id '{instance_id}'. "
                f"Clearing conversation history also clears token usage data.")
    return 0

async def get_active_prospect_jids(instance_id: str) -> List[str]:
    """Fetches a list of JIDs for prospects with status 'active' for a given instance."""
    logger.debug(f"db_operations.prospect_crud: Fetching active prospect JIDs for instance '{instance_id}'.")
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available. Cannot fetch active JIDs.")
        return []
    
    sql = "SELECT jid FROM prospects WHERE instance_id = %s AND status = 'active'"
    jids = []
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id,))
            results = await cursor.fetchall()
            jids = [row['jid'] for row in results]
        logger.info(f"db_operations.prospect_crud: Fetched {len(jids)} active prospect JIDs for instance '{instance_id}'.")
        return jids
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error fetching active prospect JIDs for instance '{instance_id}': {e}", exc_info=True)
        return []

async def get_active_prospect_count_db(instance_id: Optional[str] = None, initiator: Optional[Literal['user', 'llm_agent']] = None) -> int:
    """Counts the number of prospects with status 'active' for a given instance."""
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    logger.debug(f"db_operations.prospect_crud: Counting active prospects for instance '{instance_id}', initiator: {initiator}.")
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available. Cannot count active prospects.")
        return 0
    
    sql = "SELECT COUNT(*) as count FROM prospects WHERE instance_id = %s AND status = 'active'"
    params = [instance_id]
    if initiator:
        sql += " AND conversation_initiator = %s"
        params.append(initiator)
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            result = await cursor.fetchone()
            count = result['count'] if result else 0
        logger.info(f"db_operations.prospect_crud: Found {count} active prospects for instance '{instance_id}', initiator: {initiator}.")
        return count
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error counting active prospects for instance '{instance_id}', initiator: {initiator}: {e}", exc_info=True)
        return 0

async def get_total_prospected_count_db(instance_id: Optional[str] = None, initiator: Optional[Literal['user', 'llm_agent']] = None) -> int:
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    logger.debug(f"db_operations.prospect_crud: Counting total prospects for instance '{instance_id}', initiator: {initiator}.")
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available. Cannot count total prospects.")
        return 0
    
    sql = "SELECT COUNT(*) as count FROM prospects WHERE instance_id = %s"
    params = [instance_id]
    if initiator:
        sql += " AND conversation_initiator = %s"
        params.append(initiator)
        
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            result = await cursor.fetchone()
            count = result['count'] if result else 0
        logger.info(f"db_operations.prospect_crud: Found {count} total prospects for instance '{instance_id}', initiator: {initiator}.")
        return count
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error counting total prospects for instance '{instance_id}', initiator: {initiator}: {e}", exc_info=True)
        return 0

async def get_funnel_stages_db(instance_id: Optional[str] = None, initiator: Optional[Literal['user', 'llm_agent']] = None) -> List[Dict[str, Any]]:
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    logger.debug(f"db_operations.prospect_crud: Getting funnel stage counts for instance '{instance_id}', initiator: {initiator}.")
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available. Cannot get funnel stages.")
        return []

    sql = "SELECT current_stage, COUNT(*) as count FROM prospects WHERE instance_id = %s AND status = 'active'"
    params = [instance_id]
    if initiator:
        sql += " AND conversation_initiator = %s"
        params.append(initiator)
    sql += " GROUP BY current_stage ORDER BY current_stage ASC"

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            results = await cursor.fetchall()
        logger.info(f"db_operations.prospect_crud: Fetched {len(results)} funnel stage counts for instance '{instance_id}', initiator: {initiator}.")
        return [{'stage_number': r['current_stage'], 'count': r['count']} for r in results]
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error getting funnel stages for instance '{instance_id}', initiator: {initiator}: {e}", exc_info=True)
        return []

async def get_messages_sent_count_db(instance_id: Optional[str] = None, initiator: Optional[Literal['user', 'llm_agent']] = None) -> int:
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    logger.debug(f"db_operations.prospect_crud: Counting messages sent for instance '{instance_id}', initiator: {initiator}.")
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available. Cannot count messages sent.")
        return 0

    sql = "SELECT COUNT(*) as count FROM conversation_history WHERE instance_id = %s AND role = 'assistant'"
    params = [instance_id]
    if initiator:
        sql += " AND conversation_initiator = %s"
        params.append(initiator)

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            result = await cursor.fetchone()
            count = result['count'] if result else 0
        logger.info(f"db_operations.prospect_crud: Found {count} messages sent for instance '{instance_id}', initiator: {initiator}.")
        return count
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error counting messages sent for instance '{instance_id}', initiator: {initiator}: {e}", exc_info=True)
        return 0

async def get_all_instance_ids(db_pool: aiomysql.Pool) -> List[str]:
    """
    Fetches all unique instance_ids from the prospects table.
    In a real multi-tenant system, this would be used by background jobs.
    For now, it will likely just return the single instance_id.
    """
    logger.debug("db_operations.prospect_crud: Fetching all unique instance_ids.")
    if not db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available. Cannot fetch instance_ids.")
        return []
    
    sql = "SELECT DISTINCT instance_id FROM prospects"
    try:
        async with db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql)
            results = await cursor.fetchall()
            instance_ids = [row['instance_id'] for row in results]
        logger.info(f"db_operations.prospect_crud: Found {len(instance_ids)} unique instance_ids.")
        return instance_ids
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error fetching unique instance_ids: {e}", exc_info=True)
        return []

async def get_prospects_count_by_status_db(instance_id: str, status: str, initiator: Optional[Literal['user', 'llm_agent']] = None) -> int:
    logger.debug(f"db_operations.prospect_crud: Counting prospects by status '{status}' for instance '{instance_id}', initiator: {initiator}.")
    if not settings.db_pool:
        logger.error(f"db_operations.prospect_crud: Database pool not available. Cannot count prospects by status '{status}'.")
        return 0
    
    sql = "SELECT COUNT(*) as count FROM prospects WHERE instance_id = %s AND status = %s"
    params: List[Any] = [instance_id, status]
    if initiator:
        sql += " AND conversation_initiator = %s"
        params.append(initiator)
        
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            result = await cursor.fetchone()
            count = result['count'] if result else 0
        logger.info(f"db_operations.prospect_crud: Found {count} prospects with status '{status}' for instance '{instance_id}', initiator: {initiator}.")
        return count
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error counting prospects by status '{status}' for instance '{instance_id}', initiator: {initiator}: {e}", exc_info=True)
        return 0

async def get_funnel_analytics_db(instance_id: Optional[str] = None, initiator: Optional[Literal['user', 'llm_agent']] = None) -> Dict[str, Any]:
    """
    Calculates advanced funnel analytics: conversion rates and average time in stage.
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID
    logger.info(f"db_operations.prospect_crud: Calculating funnel analytics for instance '{instance_id}', initiator: {initiator}.")
    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available for analytics.")
        return {"conversion_rates": [], "avg_time_in_stage": []}

    # 1. Calculate prospects who reached each stage (for conversion rates)
    # This query counts how many unique prospects have a max stage >= X
    stage_reach_sql = """
        SELECT 
            s.stage_number,
            COUNT(p.jid) AS reached_count
        FROM 
            (SELECT 1 AS stage_number UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6) AS s
        LEFT JOIN (
            SELECT jid, MAX(current_stage) AS max_stage
            FROM prospects
            WHERE instance_id = %s
            GROUP BY jid
        ) AS p ON p.max_stage >= s.stage_number
        GROUP BY s.stage_number
        ORDER BY s.stage_number;
    """
    # The initiator filter needs to be applied to the subquery
    if initiator:
        stage_reach_sql = stage_reach_sql.replace("GROUP BY jid", "AND conversation_initiator = %s GROUP BY jid")
    
    params_reach = [instance_id]
    if initiator:
        params_reach.append(initiator)

    # 2. Calculate average time in each stage
    # This query uses LAG to find time difference between stage changes
    avg_time_sql = """
        WITH stage_changes AS (
            SELECT
                prospect_jid,
                stage_at_message,
                timestamp,
                LAG(stage_at_message, 1, 0) OVER (PARTITION BY prospect_jid ORDER BY timestamp) as prev_stage,
                LAG(timestamp, 1) OVER (PARTITION BY prospect_jid ORDER BY timestamp) as prev_timestamp
            FROM conversation_history
            WHERE instance_id = %s AND stage_at_message IS NOT NULL
        )
        SELECT
            prev_stage AS stage,
            AVG(TIMESTAMPDIFF(SECOND, prev_timestamp, timestamp)) as avg_duration_seconds
        FROM stage_changes
        WHERE prev_timestamp IS NOT NULL AND stage_at_message > prev_stage
        GROUP BY prev_stage;
    """
    # The initiator filter for this query is more complex, would require a JOIN.
    # For now, we calculate avg time across all prospects for simplicity.
    params_time = [instance_id]

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            # Execute conversion rate query
            await cursor.execute(stage_reach_sql, tuple(params_reach))
            stage_reach_results = await cursor.fetchall()
            
            # Execute average time query
            await cursor.execute(avg_time_sql, tuple(params_time))
            avg_time_results = await cursor.fetchall()

        # Process conversion rates
        conversion_rates = []
        for i in range(len(stage_reach_results) - 1):
            from_stage = stage_reach_results[i]
            to_stage = stage_reach_results[i+1]
            rate = 0
            if from_stage['reached_count'] > 0:
                rate = (to_stage['reached_count'] / from_stage['reached_count']) * 100
            
            conversion_rates.append({
                "from_stage": from_stage['stage_number'],
                "to_stage": to_stage['stage_number'],
                "conversion_rate": round(rate, 2),
                "from_count": from_stage['reached_count'],
                "to_count": to_stage['reached_count']
            })

        # Process average time
        avg_time_in_stage = [
            {
                "stage": row['stage'],
                "avg_duration_seconds": round(float(row['avg_duration_seconds']), 2)
            } for row in avg_time_results
        ]
        
        analytics_data = {
            "conversion_rates": conversion_rates,
            "avg_time_in_stage": avg_time_in_stage
        }
        logger.info(f"db_operations.prospect_crud: Funnel analytics calculated successfully for instance '{instance_id}'.")
        return analytics_data

    except Exception as e:
        logger.error(f"db_operations.prospect_crud: DB error calculating funnel analytics for instance '{instance_id}': {e}", exc_info=True)
        return {"conversion_rates": [], "avg_time_in_stage": []}


async def update_prospect_funnel_db(
    jid: str,
    funnel_id: str,
    instance_id: Optional[str] = None,
    reset_stage: bool = True,
    target_stage: Optional[int] = None
) -> bool:
    """
    Updates the funnel assignment for a prospect.

    Args:
        jid: Prospect's JID
        funnel_id: New funnel ID to assign
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)
        reset_stage: If True, resets prospect to stage 1 of the new funnel
        target_stage: Specific stage to set (if reset_stage is False)

    Returns:
        True if successful, False otherwise
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"db_operations.prospect_crud: Updating funnel for prospect '{jid}' to '{funnel_id}' (reset_stage={reset_stage}, target_stage={target_stage})")

    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available.")
        return False

    new_stage = 1 if reset_stage else (target_stage if target_stage else 1)
    now_utc = _now()

    sql = """
        UPDATE prospects
        SET funnel_id = %s, current_stage = %s, updated_at = %s
        WHERE instance_id = %s AND jid = %s
    """

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, (funnel_id, new_stage, now_utc, instance_id, jid))
                rows_affected = cursor.rowcount

                if not conn.get_autocommit():
                    await conn.commit()

        if rows_affected == 0:
            logger.warning(f"db_operations.prospect_crud: Prospect '{jid}' not found")
            return False

        logger.info(f"db_operations.prospect_crud: Prospect '{jid}' updated to funnel '{funnel_id}' at stage {new_stage}")
        return True

    except Exception as e:
        logger.error(f"db_operations.prospect_crud: Error updating funnel for '{jid}': {e}", exc_info=True)
        return False


async def get_prospect_funnel_id(jid: str, instance_id: Optional[str] = None) -> Optional[str]:
    """
    Gets the funnel_id for a specific prospect.

    Args:
        jid: Prospect's JID
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)

    Returns:
        Funnel ID or None if not set/found
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    if not settings.db_pool:
        logger.warning("db_operations.prospect_crud: Database pool not available.")
        return None

    sql = "SELECT funnel_id FROM prospects WHERE instance_id = %s AND jid = %s"

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, jid))
            result = await cursor.fetchone()
            return result['funnel_id'] if result else None
    except Exception as e:
        logger.error(f"db_operations.prospect_crud: Error getting funnel_id for '{jid}': {e}", exc_info=True)
        return None


async def get_prospect_from_db(phone_number: str, instance_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Busca dados completos de um prospect diretamente do banco de dados.
    Usado como fallback quando Redis não está disponível.

    Args:
        phone_number: Número de telefone (JID) do prospect
        instance_id: ID da instância (defaults to settings.INSTANCE_ID)

    Returns:
        Dict com dados do prospect ou None se não encontrado
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.debug(f"db_operations.prospect_crud: Fetching prospect from DB: {phone_number}")

    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available for get_prospect_from_db.")
        return None

    sql = """
        SELECT
            jid, name, current_stage, status, llm_paused,
            conversation_initiator, last_interaction_at,
            created_at, updated_at, funnel_id, tags, version
        FROM prospects
        WHERE instance_id = %s AND jid = %s
    """

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, phone_number))
            result = await cursor.fetchone()

            if not result:
                logger.debug(f"db_operations.prospect_crud: Prospect '{phone_number}' not found in DB.")
                return None

            # Parse tags JSON
            tags_raw = result.get('tags')
            if tags_raw:
                try:
                    result['tags'] = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                except:
                    result['tags'] = []
            else:
                result['tags'] = []

            # Convert datetime fields to ISO format
            sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
            for field in ['last_interaction_at', 'created_at', 'updated_at']:
                if result.get(field):
                    try:
                        dt_utc = pytz.utc.localize(result[field])
                        dt_sao_paulo = dt_utc.astimezone(sao_paulo_tz)
                        result[field] = dt_sao_paulo.isoformat()
                    except:
                        result[field] = result[field].isoformat() if hasattr(result[field], 'isoformat') else str(result[field])

            logger.info(f"db_operations.prospect_crud: Prospect '{phone_number}' fetched from DB successfully.")
            return dict(result)

    except Exception as e:
        logger.error(f"db_operations.prospect_crud: Error fetching prospect '{phone_number}' from DB: {e}", exc_info=True)
        return None


async def get_conversation_history_db(phone_number: str, instance_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Busca histórico de conversa diretamente do banco de dados.
    Usado como fallback quando Redis não está disponível.

    Args:
        phone_number: Número de telefone (JID) do prospect
        instance_id: ID da instância (defaults to settings.INSTANCE_ID)
        limit: Número máximo de mensagens a retornar

    Returns:
        Lista de mensagens no formato [{role, content}, ...]
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.debug(f"db_operations.prospect_crud: Fetching conversation history from DB for: {phone_number}")

    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: Database pool not available for get_conversation_history_db.")
        return []

    sql = """
        SELECT role, content, timestamp
        FROM conversation_history
        WHERE instance_id = %s AND prospect_jid = %s
        ORDER BY timestamp DESC
        LIMIT %s
    """

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, phone_number, limit))
            results = await cursor.fetchall()

            # Converter para formato do ProspectState e inverter ordem (mais recentes -> mais antigos para LLM)
            history = []
            for row in reversed(results):
                history.append({
                    "role": row['role'],
                    "content": row['content']
                })

            logger.info(f"db_operations.prospect_crud: Fetched {len(history)} history entries from DB for '{phone_number}'.")
            return history

    except Exception as e:
        logger.error(f"db_operations.prospect_crud: Error fetching conversation history for '{phone_number}': {e}", exc_info=True)
        return []


# ==================== DADOS DO PACIENTE PARA CLÍNICAS ====================

async def get_prospect_patient_data(jid: str, instance_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Busca dados do paciente (CPF, nome completo, data de nascimento) de um prospect.

    Args:
        jid: Identificador do prospect (WhatsApp JID)
        instance_id: ID da instância (defaults to settings.INSTANCE_ID)

    Returns:
        Dict com cpf, full_name, birth_date ou None se não encontrado
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.debug(f"db_operations.prospect_crud: [GET_PATIENT_DATA] Buscando dados do paciente para JID '{jid}'")

    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: [GET_PATIENT_DATA] Database pool not available.")
        return None

    sql = """
        SELECT cpf, full_name, birth_date, name
        FROM prospects
        WHERE instance_id = %s AND jid = %s
    """

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, jid))
            result = await cursor.fetchone()

            if not result:
                logger.debug(f"db_operations.prospect_crud: [GET_PATIENT_DATA] Prospect '{jid}' não encontrado.")
                return None

            patient_data = {
                'cpf': result.get('cpf'),
                'full_name': result.get('full_name'),
                'birth_date': result.get('birth_date').isoformat() if result.get('birth_date') and hasattr(result.get('birth_date'), 'isoformat') else result.get('birth_date'),
                'name': result.get('name')  # Nome curto/apelido
            }

            logger.info(f"db_operations.prospect_crud: [GET_PATIENT_DATA] Dados do paciente para '{jid}': CPF={patient_data.get('cpf')}, Nome={patient_data.get('full_name')}, Nascimento={patient_data.get('birth_date')}")
            return patient_data

    except Exception as e:
        logger.error(f"db_operations.prospect_crud: [GET_PATIENT_DATA] Erro ao buscar dados do paciente para '{jid}': {e}", exc_info=True)
        return None


async def update_prospect_patient_data(
    jid: str,
    instance_id: Optional[str] = None,
    cpf: Optional[str] = None,
    full_name: Optional[str] = None,
    birth_date: Optional[str] = None
) -> bool:
    """
    Atualiza dados do paciente de um prospect.

    Args:
        jid: Identificador do prospect (WhatsApp JID)
        instance_id: ID da instância (defaults to settings.INSTANCE_ID)
        cpf: CPF do paciente (formato: 000.000.000-00 ou apenas números)
        full_name: Nome completo do paciente
        birth_date: Data de nascimento (formato: YYYY-MM-DD ou DD/MM/YYYY)

    Returns:
        True se atualizado com sucesso, False caso contrário
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"db_operations.prospect_crud: [UPDATE_PATIENT_DATA] Atualizando dados do paciente para JID '{jid}': CPF={cpf}, Nome={full_name}, Nascimento={birth_date}")

    if not settings.db_pool:
        logger.error("db_operations.prospect_crud: [UPDATE_PATIENT_DATA] Database pool not available.")
        return False

    # Construir SET clause dinamicamente apenas com campos fornecidos
    updates = []
    params = []

    if cpf is not None:
        # Limpa e formata o CPF
        cpf_clean = ''.join(filter(str.isdigit, cpf))
        if len(cpf_clean) == 11:
            cpf_formatted = f"{cpf_clean[:3]}.{cpf_clean[3:6]}.{cpf_clean[6:9]}-{cpf_clean[9:]}"
            updates.append("cpf = %s")
            params.append(cpf_formatted)
        elif cpf:  # Se foi fornecido mas é inválido, salva como está
            updates.append("cpf = %s")
            params.append(cpf)

    if full_name is not None:
        updates.append("full_name = %s")
        params.append(full_name.strip().title() if full_name else None)

    if birth_date is not None:
        # Tenta converter diferentes formatos de data
        parsed_date = None
        if birth_date:
            # Tenta DD/MM/YYYY
            if '/' in birth_date:
                try:
                    parts = birth_date.split('/')
                    if len(parts) == 3:
                        day, month, year = parts
                        # Corrige anos com 2 dígitos
                        if len(year) == 2:
                            year = '19' + year if int(year) > 30 else '20' + year
                        parsed_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                except Exception as e:
                    logger.warning(f"db_operations.prospect_crud: [UPDATE_PATIENT_DATA] Falha ao parsear data DD/MM/YYYY: {birth_date} - {e}")
            # Tenta YYYY-MM-DD
            elif '-' in birth_date and len(birth_date) >= 8:
                parsed_date = birth_date
            # Tenta DDMMYYYY
            elif len(birth_date) == 8 and birth_date.isdigit():
                parsed_date = f"{birth_date[4:]}-{birth_date[2:4]}-{birth_date[:2]}"

        if parsed_date:
            updates.append("birth_date = %s")
            params.append(parsed_date)
        elif birth_date:
            logger.warning(f"db_operations.prospect_crud: [UPDATE_PATIENT_DATA] Data de nascimento em formato não reconhecido: {birth_date}")

    if not updates:
        logger.warning(f"db_operations.prospect_crud: [UPDATE_PATIENT_DATA] Nenhum campo para atualizar para '{jid}'")
        return False

    # Sempre atualizar updated_at
    updates.append("updated_at = %s")
    params.append(_now())

    # Adicionar parâmetros do WHERE
    params.extend([instance_id, jid])

    sql = f"""
        UPDATE prospects
        SET {', '.join(updates)}
        WHERE instance_id = %s AND jid = %s
    """

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, tuple(params))
                rows_affected = cursor.rowcount

                if not conn.get_autocommit():
                    await conn.commit()

        if rows_affected == 0:
            logger.warning(f"db_operations.prospect_crud: [UPDATE_PATIENT_DATA] Prospect '{jid}' não encontrado ou nenhuma alteração")
            return False

        logger.info(f"db_operations.prospect_crud: [UPDATE_PATIENT_DATA] Dados do paciente para '{jid}' atualizados com sucesso")
        return True

    except Exception as e:
        logger.error(f"db_operations.prospect_crud: [UPDATE_PATIENT_DATA] Erro ao atualizar dados do paciente para '{jid}': {e}", exc_info=True)
        return False


async def check_patient_data_complete(jid: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Verifica se os dados do paciente estão completos para agendamento.

    Args:
        jid: Identificador do prospect (WhatsApp JID)
        instance_id: ID da instância (defaults to settings.INSTANCE_ID)

    Returns:
        Dict com:
            - is_complete: bool - Se todos os dados obrigatórios estão preenchidos
            - missing_fields: list - Lista de campos faltantes
            - data: dict - Dados atuais do paciente
    """
    patient_data = await get_prospect_patient_data(jid, instance_id)

    if not patient_data:
        return {
            'is_complete': False,
            'missing_fields': ['cpf', 'full_name', 'birth_date'],
            'data': None
        }

    missing_fields = []

    if not patient_data.get('cpf'):
        missing_fields.append('cpf')
    if not patient_data.get('full_name'):
        missing_fields.append('full_name')
    if not patient_data.get('birth_date'):
        missing_fields.append('birth_date')

    logger.info(f"db_operations.prospect_crud: [CHECK_PATIENT_DATA] JID '{jid}' - Completo: {len(missing_fields) == 0}, Faltando: {missing_fields}")

    return {
        'is_complete': len(missing_fields) == 0,
        'missing_fields': missing_fields,
        'data': patient_data
    }


def validate_cpf(cpf: str) -> bool:
    """
    Valida um CPF brasileiro usando o algoritmo oficial.

    Args:
        cpf: CPF a ser validado (com ou sem formatação)

    Returns:
        True se o CPF é válido, False caso contrário
    """
    # Remove caracteres não numéricos
    cpf_clean = ''.join(filter(str.isdigit, cpf))

    # Verifica se tem 11 dígitos
    if len(cpf_clean) != 11:
        return False

    # Verifica se todos os dígitos são iguais (caso inválido)
    if cpf_clean == cpf_clean[0] * 11:
        return False

    # Calcula primeiro dígito verificador
    soma = 0
    for i in range(9):
        soma += int(cpf_clean[i]) * (10 - i)
    resto = soma % 11
    digito1 = 0 if resto < 2 else 11 - resto

    # Calcula segundo dígito verificador
    soma = 0
    for i in range(10):
        soma += int(cpf_clean[i]) * (11 - i)
    resto = soma % 11
    digito2 = 0 if resto < 2 else 11 - resto

    # Verifica se os dígitos calculados conferem
    return cpf_clean[-2:] == f"{digito1}{digito2}"


logger.info("db_operations.prospect_crud: Module loaded.")
