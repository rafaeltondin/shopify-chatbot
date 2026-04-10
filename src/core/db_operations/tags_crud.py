# -*- coding: utf-8 -*-
"""
CRUD Operations for Tags and Automation Flows

Este módulo gerencia as operações de banco de dados para:
- Tags de prospects (categorização dinâmica)
- Fluxos de automação baseados em tags
- Execução e histórico de automações
"""
import logging
import json
import asyncio
from typing import Optional, Any, Dict, List, Literal
from datetime import datetime
import pytz

from src.core.config import settings

logger = logging.getLogger(__name__)

# ==================== TAG CRUD OPERATIONS ====================

async def get_prospect_tags(jid: str, instance_id: Optional[str] = None) -> List[str]:
    """
    Retorna lista de tags de um prospect.

    Args:
        jid: Identificador do prospect
        instance_id: ID da instância (usa settings.INSTANCE_ID se não fornecido)

    Returns:
        Lista de strings com os nomes das tags
    """
    start_time = datetime.now()
    request_id = f"req_tags_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [GET_PROSPECT_TAGS] [{request_id}] Iniciando busca de tags para JID '{jid}'")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [GET_PROSPECT_TAGS] [{request_id}] Database pool não disponível")
        return []

    sql = "SELECT tags FROM prospects WHERE instance_id = %s AND jid = %s"

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, jid))
            result = await cursor.fetchone()

            if result and result.get('tags'):
                tags = json.loads(result['tags']) if isinstance(result['tags'], str) else result['tags']
                duration = (datetime.now() - start_time).total_seconds() * 1000
                logger.info(f"[{datetime.now().isoformat()}] [GET_PROSPECT_TAGS] [{request_id}] Sucesso - {len(tags)} tags encontradas em {duration:.2f}ms")
                return tags

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [GET_PROSPECT_TAGS] [{request_id}] Nenhuma tag encontrada para JID '{jid}' em {duration:.2f}ms")
            return []

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [GET_PROSPECT_TAGS] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return []


async def add_tag_to_prospect(jid: str, tag: str, instance_id: Optional[str] = None) -> bool:
    """
    Adiciona uma tag a um prospect.

    Args:
        jid: Identificador do prospect
        tag: Nome da tag a adicionar
        instance_id: ID da instância

    Returns:
        True se a tag foi adicionada com sucesso
    """
    start_time = datetime.now()
    request_id = f"req_addtag_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [ADD_TAG_TO_PROSPECT] [{request_id}] Iniciando - JID: '{jid}', Tag: '{tag}'")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [ADD_TAG_TO_PROSPECT] [{request_id}] Database pool não disponível")
        return False

    try:
        # Buscar tags atuais
        current_tags = await get_prospect_tags(jid, instance_id)

        # Verificar se tag já existe
        if tag in current_tags:
            logger.info(f"[{datetime.now().isoformat()}] [ADD_TAG_TO_PROSPECT] [{request_id}] Tag '{tag}' já existe para JID '{jid}'")
            return True

        # Adicionar nova tag
        current_tags.append(tag)
        tags_json = json.dumps(current_tags)

        now_utc = datetime.utcnow()
        sql = "UPDATE prospects SET tags = %s, updated_at = %s WHERE instance_id = %s AND jid = %s"

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (tags_json, now_utc, instance_id, jid))

            if not conn.get_autocommit():
                await conn.commit()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [ADD_TAG_TO_PROSPECT] [{request_id}] Sucesso - Tag '{tag}' adicionada em {duration:.2f}ms")

            # CORREÇÃO CRÍTICA: Aguardar execução do evento de tag para garantir
            # que automações como pause_llm sejam executadas ANTES de retornar.
            # Anteriormente usava asyncio.create_task (fire-and-forget), o que causava
            # race condition onde a resposta do LLM era enviada antes do pause_llm ser ativado.
            await _trigger_tag_event(jid, tag, 'tag_added', instance_id)

            return True

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [ADD_TAG_TO_PROSPECT] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return False


async def remove_tag_from_prospect(jid: str, tag: str, instance_id: Optional[str] = None) -> bool:
    """
    Remove uma tag de um prospect.

    Args:
        jid: Identificador do prospect
        tag: Nome da tag a remover
        instance_id: ID da instância

    Returns:
        True se a tag foi removida com sucesso
    """
    start_time = datetime.now()
    request_id = f"req_rmtag_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [REMOVE_TAG_FROM_PROSPECT] [{request_id}] Iniciando - JID: '{jid}', Tag: '{tag}'")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [REMOVE_TAG_FROM_PROSPECT] [{request_id}] Database pool não disponível")
        return False

    try:
        # Buscar tags atuais
        current_tags = await get_prospect_tags(jid, instance_id)

        # Verificar se tag existe
        if tag not in current_tags:
            logger.info(f"[{datetime.now().isoformat()}] [REMOVE_TAG_FROM_PROSPECT] [{request_id}] Tag '{tag}' não existe para JID '{jid}'")
            return True

        # Remover tag
        current_tags.remove(tag)
        tags_json = json.dumps(current_tags)

        now_utc = datetime.utcnow()
        sql = "UPDATE prospects SET tags = %s, updated_at = %s WHERE instance_id = %s AND jid = %s"

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (tags_json, now_utc, instance_id, jid))

            if not conn.get_autocommit():
                await conn.commit()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [REMOVE_TAG_FROM_PROSPECT] [{request_id}] Sucesso - Tag '{tag}' removida em {duration:.2f}ms")

            # Aguardar execução do evento de tag para garantir consistência
            await _trigger_tag_event(jid, tag, 'tag_removed', instance_id)

            return True

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [REMOVE_TAG_FROM_PROSPECT] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return False


async def set_prospect_tags(jid: str, tags: List[str], instance_id: Optional[str] = None) -> bool:
    """
    Define as tags de um prospect (substitui todas as existentes).

    Args:
        jid: Identificador do prospect
        tags: Lista de tags a definir
        instance_id: ID da instância

    Returns:
        True se as tags foram definidas com sucesso
    """
    start_time = datetime.now()
    request_id = f"req_settags_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [SET_PROSPECT_TAGS] [{request_id}] Iniciando - JID: '{jid}', Tags: {tags}")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [SET_PROSPECT_TAGS] [{request_id}] Database pool não disponível")
        return False

    try:
        # Buscar tags anteriores para comparação
        old_tags = await get_prospect_tags(jid, instance_id)

        tags_json = json.dumps(tags)
        now_utc = datetime.utcnow()

        sql = "UPDATE prospects SET tags = %s, updated_at = %s WHERE instance_id = %s AND jid = %s"

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (tags_json, now_utc, instance_id, jid))

            if not conn.get_autocommit():
                await conn.commit()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [SET_PROSPECT_TAGS] [{request_id}] Sucesso - Tags definidas em {duration:.2f}ms")

            # Aguardar execução dos eventos de tags para garantir consistência
            # Processar em sequência para evitar race conditions
            added_tags = set(tags) - set(old_tags)
            for tag in added_tags:
                await _trigger_tag_event(jid, tag, 'tag_added', instance_id)

            removed_tags = set(old_tags) - set(tags)
            for tag in removed_tags:
                await _trigger_tag_event(jid, tag, 'tag_removed', instance_id)

            return True

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [SET_PROSPECT_TAGS] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return False


async def get_prospects_by_tag(tag: str, instance_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retorna lista de prospects que possuem uma determinada tag.

    Args:
        tag: Nome da tag para filtrar
        instance_id: ID da instância
        status: Filtrar por status (opcional)

    Returns:
        Lista de prospects com a tag especificada
    """
    start_time = datetime.now()
    request_id = f"req_bytag_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [GET_PROSPECTS_BY_TAG] [{request_id}] Iniciando - Tag: '{tag}', Status: '{status}'")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [GET_PROSPECTS_BY_TAG] [{request_id}] Database pool não disponível")
        return []

    try:
        # Usar JSON_CONTAINS para buscar na coluna JSON
        sql = """
            SELECT jid, name, current_stage, status, tags, last_interaction_at, created_at
            FROM prospects
            WHERE instance_id = %s AND JSON_CONTAINS(tags, %s)
        """
        params = [instance_id, json.dumps(tag)]

        if status:
            sql += " AND status = %s"
            params.append(status)

        sql += " ORDER BY updated_at DESC"

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            prospects = await cursor.fetchall()

            # Processar resultados
            for p in prospects:
                if p.get('tags'):
                    p['tags'] = json.loads(p['tags']) if isinstance(p['tags'], str) else p['tags']
                if p.get('last_interaction_at'):
                    p['last_interaction_at'] = p['last_interaction_at'].isoformat()
                if p.get('created_at'):
                    p['created_at'] = p['created_at'].isoformat()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [GET_PROSPECTS_BY_TAG] [{request_id}] Sucesso - {len(prospects)} prospects encontrados em {duration:.2f}ms")
            return prospects

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [GET_PROSPECTS_BY_TAG] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return []


async def get_all_tags(instance_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retorna lista de todas as tags únicas em uso com contagem de prospects.

    Args:
        instance_id: ID da instância

    Returns:
        Lista de dicts com nome da tag e contagem
    """
    start_time = datetime.now()
    request_id = f"req_alltags_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [GET_ALL_TAGS] [{request_id}] Iniciando busca de todas as tags")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [GET_ALL_TAGS] [{request_id}] Database pool não disponível")
        return []

    try:
        # Buscar todos os prospects com tags
        sql = "SELECT tags FROM prospects WHERE instance_id = %s AND tags IS NOT NULL AND tags != '[]'"

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id,))
            results = await cursor.fetchall()

            # Contar tags
            tag_counts: Dict[str, int] = {}
            for row in results:
                if row.get('tags'):
                    tags = json.loads(row['tags']) if isinstance(row['tags'], str) else row['tags']
                    for tag in tags:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

            # Formatar resultado
            tags_list = [{"name": tag, "count": count} for tag, count in sorted(tag_counts.items())]

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [GET_ALL_TAGS] [{request_id}] Sucesso - {len(tags_list)} tags únicas encontradas em {duration:.2f}ms")
            return tags_list

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [GET_ALL_TAGS] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return []


# ==================== TAG DEFINITIONS CRUD ====================

async def get_tag_definitions(instance_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retorna as definições de tags configuradas (nome, cor, descrição, triggers).

    Args:
        instance_id: ID da instância

    Returns:
        Lista de definições de tags
    """
    start_time = datetime.now()
    request_id = f"req_tagdefs_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [GET_TAG_DEFINITIONS] [{request_id}] Iniciando busca de definições de tags")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [GET_TAG_DEFINITIONS] [{request_id}] Database pool não disponível")
        return []

    try:
        sql = "SELECT config_value FROM application_config WHERE instance_id = %s AND config_key = 'tag_definitions'"

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id,))
            result = await cursor.fetchone()

            if result and result.get('config_value'):
                definitions = json.loads(result['config_value'])
                duration = (datetime.now() - start_time).total_seconds() * 1000
                logger.info(f"[{datetime.now().isoformat()}] [GET_TAG_DEFINITIONS] [{request_id}] Sucesso - {len(definitions)} definições encontradas em {duration:.2f}ms")
                return definitions

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [GET_TAG_DEFINITIONS] [{request_id}] Nenhuma definição encontrada em {duration:.2f}ms")
            return []

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [GET_TAG_DEFINITIONS] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return []


async def save_tag_definitions(definitions: List[Dict[str, Any]], instance_id: Optional[str] = None) -> bool:
    """
    Salva as definições de tags.

    Args:
        definitions: Lista de definições de tags
        instance_id: ID da instância

    Returns:
        True se salvo com sucesso
    """
    start_time = datetime.now()
    request_id = f"req_savetags_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [SAVE_TAG_DEFINITIONS] [{request_id}] Salvando {len(definitions)} definições de tags")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [SAVE_TAG_DEFINITIONS] [{request_id}] Database pool não disponível")
        return False

    try:
        config_value = json.dumps(definitions)

        sql = """
            INSERT INTO application_config (instance_id, config_key, config_value)
            VALUES (%s, 'tag_definitions', %s)
            ON DUPLICATE KEY UPDATE config_value = %s
        """

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, config_value, config_value))

            if not conn.get_autocommit():
                await conn.commit()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [SAVE_TAG_DEFINITIONS] [{request_id}] Sucesso em {duration:.2f}ms")
            return True

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [SAVE_TAG_DEFINITIONS] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return False


# ==================== AUTOMATION FLOWS CRUD ====================

async def get_automation_flows(instance_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retorna os fluxos de automação configurados.

    Args:
        instance_id: ID da instância

    Returns:
        Lista de fluxos de automação
    """
    start_time = datetime.now()
    request_id = f"req_flows_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_FLOWS] [{request_id}] Iniciando busca de fluxos de automação")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_FLOWS] [{request_id}] Database pool não disponível")
        return []

    try:
        sql = "SELECT config_value FROM application_config WHERE instance_id = %s AND config_key = 'automation_flows'"

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id,))
            result = await cursor.fetchone()

            if result and result.get('config_value'):
                flows = json.loads(result['config_value'])
                duration = (datetime.now() - start_time).total_seconds() * 1000
                logger.info(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_FLOWS] [{request_id}] Sucesso - {len(flows)} fluxos encontrados em {duration:.2f}ms")
                return flows

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_FLOWS] [{request_id}] Nenhum fluxo encontrado em {duration:.2f}ms")
            return []

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_FLOWS] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return []


async def save_automation_flows(flows: List[Dict[str, Any]], instance_id: Optional[str] = None) -> bool:
    """
    Salva os fluxos de automação.

    Args:
        flows: Lista de fluxos de automação
        instance_id: ID da instância

    Returns:
        True se salvo com sucesso
    """
    start_time = datetime.now()
    request_id = f"req_saveflows_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [SAVE_AUTOMATION_FLOWS] [{request_id}] Salvando {len(flows)} fluxos de automação")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [SAVE_AUTOMATION_FLOWS] [{request_id}] Database pool não disponível")
        return False

    try:
        config_value = json.dumps(flows)

        sql = """
            INSERT INTO application_config (instance_id, config_key, config_value)
            VALUES (%s, 'automation_flows', %s)
            ON DUPLICATE KEY UPDATE config_value = %s
        """

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, config_value, config_value))

            if not conn.get_autocommit():
                await conn.commit()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [SAVE_AUTOMATION_FLOWS] [{request_id}] Sucesso em {duration:.2f}ms")
            return True

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [SAVE_AUTOMATION_FLOWS] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return False


# ==================== AUTOMATION EXECUTION LOG ====================

async def log_automation_execution(
    jid: str,
    flow_id: str,
    flow_name: str,
    trigger_type: str,
    trigger_value: str,
    actions_executed: List[Dict[str, Any]],
    status: str,
    error_message: Optional[str] = None,
    instance_id: Optional[str] = None
) -> bool:
    """
    Registra a execução de uma automação.

    Args:
        jid: Identificador do prospect
        flow_id: ID do fluxo executado
        flow_name: Nome do fluxo
        trigger_type: Tipo de gatilho (tag_added, tag_removed, inactivity, etc)
        trigger_value: Valor que disparou (nome da tag, tempo de inatividade, etc)
        actions_executed: Lista de ações executadas
        status: success, partial, failed
        error_message: Mensagem de erro (se houver)
        instance_id: ID da instância

    Returns:
        True se registrado com sucesso
    """
    start_time = datetime.now()
    request_id = f"req_logauto_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [LOG_AUTOMATION_EXECUTION] [{request_id}] Registrando execução - Flow: '{flow_name}', JID: '{jid}', Status: '{status}'")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [LOG_AUTOMATION_EXECUTION] [{request_id}] Database pool não disponível")
        return False

    try:
        now_utc = datetime.utcnow()

        sql = """
            INSERT INTO automation_executions
            (instance_id, jid, flow_id, flow_name, trigger_type, trigger_value,
             actions_executed, status, error_message, executed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (
                instance_id,
                jid,
                flow_id,
                flow_name,
                trigger_type,
                trigger_value,
                json.dumps(actions_executed),
                status,
                error_message,
                now_utc
            ))

            if not conn.get_autocommit():
                await conn.commit()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [LOG_AUTOMATION_EXECUTION] [{request_id}] Sucesso em {duration:.2f}ms")
            return True

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [LOG_AUTOMATION_EXECUTION] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return False


async def get_automation_history(
    jid: Optional[str] = None,
    flow_id: Optional[str] = None,
    limit: int = 50,
    instance_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retorna histórico de execuções de automações.

    Args:
        jid: Filtrar por JID (opcional)
        flow_id: Filtrar por fluxo (opcional)
        limit: Limite de resultados
        instance_id: ID da instância

    Returns:
        Lista de execuções
    """
    start_time = datetime.now()
    request_id = f"req_autohist_{datetime.now().timestamp()}"

    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_HISTORY] [{request_id}] Buscando histórico - JID: '{jid}', Flow: '{flow_id}'")

    if not settings.db_pool:
        logger.error(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_HISTORY] [{request_id}] Database pool não disponível")
        return []

    try:
        sql = """
            SELECT id, jid, flow_id, flow_name, trigger_type, trigger_value,
                   actions_executed, status, error_message, executed_at
            FROM automation_executions
            WHERE instance_id = %s
        """
        params: List[Any] = [instance_id]

        if jid:
            sql += " AND jid = %s"
            params.append(jid)

        if flow_id:
            sql += " AND flow_id = %s"
            params.append(flow_id)

        sql += " ORDER BY executed_at DESC LIMIT %s"
        params.append(limit)

        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            results = await cursor.fetchall()

            # Processar resultados
            for r in results:
                if r.get('actions_executed'):
                    r['actions_executed'] = json.loads(r['actions_executed']) if isinstance(r['actions_executed'], str) else r['actions_executed']
                if r.get('executed_at'):
                    r['executed_at'] = r['executed_at'].isoformat()

            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_HISTORY] [{request_id}] Sucesso - {len(results)} execuções encontradas em {duration:.2f}ms")
            return results

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"[{datetime.now().isoformat()}] [GET_AUTOMATION_HISTORY] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)
        return []


# ==================== HELPER FUNCTIONS ====================

async def _trigger_tag_event(jid: str, tag: str, event_type: str, instance_id: str):
    """
    Dispara evento de tag para o motor de automação processar.
    Esta função é chamada de forma assíncrona (fire and forget).
    """
    logger.info(f"[{datetime.now().isoformat()}] [TRIGGER_TAG_EVENT] Disparando evento '{event_type}' para tag '{tag}' do JID '{jid}'")

    try:
        # Importar o motor de automação aqui para evitar importação circular
        from src.core.automation_engine import process_tag_event
        await process_tag_event(jid, tag, event_type, instance_id)
    except ImportError:
        logger.warning(f"[{datetime.now().isoformat()}] [TRIGGER_TAG_EVENT] Motor de automação não disponível")
    except Exception as e:
        logger.error(f"[{datetime.now().isoformat()}] [TRIGGER_TAG_EVENT] Erro ao processar evento: {e}", exc_info=True)


logger.info("db_operations.tags_crud: Module loaded.")
