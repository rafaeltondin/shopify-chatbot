# -*- coding: utf-8 -*-
"""
Módulo de API para gerenciamento de Leads.
Fornece endpoints para listar leads com informações completas incluindo
última mensagem, tags, status e metadados.
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
import pytz

from fastapi import APIRouter, HTTPException, status as http_status, Query
from pydantic import BaseModel, Field

from src.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["Leads"])

# Timezone padrão
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')


# ==================== MODELS ====================

class LastMessageInfo(BaseModel):
    """Informações sobre a última mensagem do lead."""
    content: str = Field(..., description="Conteúdo da última mensagem")
    role: str = Field(..., description="Quem enviou: 'user' ou 'assistant'")
    timestamp: Optional[str] = Field(None, description="Data/hora da mensagem")


class LeadListItem(BaseModel):
    """Item de lead para listagem."""
    jid: str = Field(..., description="Identificador único do lead (número WhatsApp)")
    name: Optional[str] = Field(None, description="Nome do lead")
    current_stage: int = Field(..., description="Estágio atual no funil")
    status: str = Field(..., description="Status do lead")
    tags: List[str] = Field(default_factory=list, description="Lista de tags")
    llm_paused: bool = Field(False, description="Se a IA está pausada para este lead")
    funnel_id: Optional[str] = Field(None, description="ID do funil atual")
    conversation_initiator: Optional[str] = Field(None, description="Quem iniciou: 'user' ou 'llm_agent'")
    last_message: Optional[LastMessageInfo] = Field(None, description="Última mensagem da conversa")
    total_messages: int = Field(0, description="Total de mensagens na conversa")
    last_interaction_at: Optional[str] = Field(None, description="Data da última interação")
    created_at: Optional[str] = Field(None, description="Data de criação")


class LeadsListResponse(BaseModel):
    """Resposta da listagem de leads."""
    leads: List[LeadListItem] = Field(default_factory=list, description="Lista de leads")
    total_count: int = Field(0, description="Total de leads encontrados")
    page: int = Field(1, description="Página atual")
    limit: int = Field(20, description="Itens por página")
    total_pages: int = Field(0, description="Total de páginas")


# ==================== HELPER FUNCTIONS ====================

async def get_leads_with_last_message(
    status: Optional[str] = None,
    stage: Optional[int] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    funnel_id: Optional[str] = None,
    initiator: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> tuple[List[Dict[str, Any]], int]:
    """
    Busca leads com informações completas incluindo última mensagem.

    Returns:
        Tupla com lista de leads e contagem total.
    """
    logger.info(f"[LEADS_API] get_leads_with_last_message: status={status}, stage={stage}, tag={tag}, search={search}, limit={limit}, offset={offset}")

    if not settings.db_pool:
        logger.error("[LEADS_API] Database pool not available.")
        return [], 0

    # Query base para prospects
    base_where = "WHERE p.instance_id = %s"
    params = [settings.INSTANCE_ID]

    # Filtros opcionais
    if status:
        base_where += " AND p.status = %s"
        params.append(status)

    if stage is not None:
        base_where += " AND p.current_stage = %s"
        params.append(stage)

    if tag:
        base_where += " AND JSON_CONTAINS(p.tags, %s)"
        params.append(f'"{tag}"')

    if search:
        base_where += " AND (p.jid LIKE %s OR p.name LIKE %s)"
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    if funnel_id:
        base_where += " AND p.funnel_id = %s"
        params.append(funnel_id)

    if initiator:
        base_where += " AND p.conversation_initiator = %s"
        params.append(initiator)

    # Query de contagem
    count_sql = f"""
        SELECT COUNT(*) as total
        FROM prospects p
        {base_where}
    """

    # Query principal com subquery para última mensagem e contagem
    # IMPORTANTE: Usa ROW_NUMBER() para garantir apenas UMA linha por prospect_jid,
    # evitando duplicação quando há mensagens com mesmo timestamp
    data_sql = f"""
        SELECT
            p.jid,
            p.name,
            p.current_stage,
            p.status,
            p.tags,
            p.llm_paused,
            p.funnel_id,
            p.conversation_initiator,
            p.last_interaction_at,
            p.created_at,
            lm.content as last_message_content,
            lm.role as last_message_role,
            lm.timestamp as last_message_timestamp,
            COALESCE(mc.msg_count, 0) as total_messages
        FROM prospects p
        LEFT JOIN (
            SELECT prospect_jid, content, role, timestamp
            FROM (
                SELECT
                    prospect_jid,
                    content,
                    role,
                    timestamp,
                    ROW_NUMBER() OVER (PARTITION BY prospect_jid ORDER BY timestamp DESC, id DESC) as rn
                FROM conversation_history
                WHERE instance_id = %s
            ) ranked
            WHERE rn = 1
        ) lm ON p.jid = lm.prospect_jid
        LEFT JOIN (
            SELECT prospect_jid, COUNT(*) as msg_count
            FROM conversation_history
            WHERE instance_id = %s
            GROUP BY prospect_jid
        ) mc ON p.jid = mc.prospect_jid
        {base_where}
        ORDER BY p.last_interaction_at DESC, p.created_at DESC
        LIMIT %s OFFSET %s
    """

    # Parâmetros para a query principal (2 instance_ids das subqueries + params originais)
    data_params = [settings.INSTANCE_ID, settings.INSTANCE_ID] + params + [limit, offset]

    try:
        import json
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Contar total
                await cursor.execute(count_sql, tuple(params))
                count_result = await cursor.fetchone()
                total_count = count_result['total'] if count_result else 0

                # Buscar dados
                await cursor.execute(data_sql, tuple(data_params))
                rows = await cursor.fetchall()

        leads = []
        for row in rows:
            # Parse tags JSON
            tags_raw = row.get('tags')
            if tags_raw:
                try:
                    tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                except:
                    tags = []
            else:
                tags = []

            # Converter timestamps para timezone SP
            last_interaction_at = None
            if row.get('last_interaction_at'):
                try:
                    dt = row['last_interaction_at']
                    if dt.tzinfo is None:
                        dt = pytz.utc.localize(dt)
                    last_interaction_at = dt.astimezone(SAO_PAULO_TZ).isoformat()
                except:
                    pass

            created_at = None
            if row.get('created_at'):
                try:
                    dt = row['created_at']
                    if dt.tzinfo is None:
                        dt = pytz.utc.localize(dt)
                    created_at = dt.astimezone(SAO_PAULO_TZ).isoformat()
                except:
                    pass

            # Última mensagem
            last_message = None
            if row.get('last_message_content'):
                last_msg_ts = None
                if row.get('last_message_timestamp'):
                    try:
                        dt = row['last_message_timestamp']
                        if dt.tzinfo is None:
                            dt = pytz.utc.localize(dt)
                        last_msg_ts = dt.astimezone(SAO_PAULO_TZ).isoformat()
                    except:
                        pass

                last_message = {
                    'content': row['last_message_content'],
                    'role': row['last_message_role'],
                    'timestamp': last_msg_ts
                }

            leads.append({
                'jid': row['jid'],
                'name': row.get('name'),
                'current_stage': row['current_stage'],
                'status': row['status'],
                'tags': tags,
                'llm_paused': bool(row.get('llm_paused')),
                'funnel_id': row.get('funnel_id'),
                'conversation_initiator': row.get('conversation_initiator'),
                'last_message': last_message,
                'total_messages': row.get('total_messages', 0),
                'last_interaction_at': last_interaction_at,
                'created_at': created_at
            })

        logger.info(f"[LEADS_API] Found {len(leads)} leads out of {total_count} total.")
        return leads, total_count

    except Exception as e:
        logger.error(f"[LEADS_API] Error fetching leads: {e}", exc_info=True)
        return [], 0


# ==================== ENDPOINTS ====================

@router.get("", response_model=LeadsListResponse)
async def list_leads_endpoint(
    status: Optional[str] = Query(None, description="Filtrar por status (active, completed, failed, etc)"),
    stage: Optional[int] = Query(None, description="Filtrar por estágio do funil"),
    tag: Optional[str] = Query(None, description="Filtrar por tag específica"),
    search: Optional[str] = Query(None, description="Buscar por JID ou nome"),
    funnel_id: Optional[str] = Query(None, description="Filtrar por funil"),
    initiator: Optional[str] = Query(None, description="Filtrar por iniciador (user, llm_agent)"),
    page: int = Query(1, ge=1, description="Número da página"),
    limit: int = Query(20, ge=1, le=100, description="Itens por página")
):
    """
    Lista todos os leads com informações completas.

    Retorna dados incluindo:
    - Nome e JID do lead
    - Tags associadas
    - Última mensagem da conversa
    - Status e estágio no funil
    - Data de criação e última interação
    """
    logger.info(f"[LEADS_API] list_leads_endpoint: status={status}, stage={stage}, tag={tag}, search={search}, page={page}, limit={limit}")

    try:
        offset = (page - 1) * limit

        leads_data, total_count = await get_leads_with_last_message(
            status=status,
            stage=stage,
            tag=tag,
            search=search,
            funnel_id=funnel_id,
            initiator=initiator,
            limit=limit,
            offset=offset
        )

        # Converter para modelos Pydantic
        leads_items = []
        for lead in leads_data:
            last_msg = None
            if lead.get('last_message'):
                last_msg = LastMessageInfo(
                    content=lead['last_message']['content'],
                    role=lead['last_message']['role'],
                    timestamp=lead['last_message'].get('timestamp')
                )

            leads_items.append(LeadListItem(
                jid=lead['jid'],
                name=lead.get('name'),
                current_stage=lead['current_stage'],
                status=lead['status'],
                tags=lead.get('tags', []),
                llm_paused=lead.get('llm_paused', False),
                funnel_id=lead.get('funnel_id'),
                conversation_initiator=lead.get('conversation_initiator'),
                last_message=last_msg,
                total_messages=lead.get('total_messages', 0),
                last_interaction_at=lead.get('last_interaction_at'),
                created_at=lead.get('created_at')
            ))

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0

        return LeadsListResponse(
            leads=leads_items,
            total_count=total_count,
            page=page,
            limit=limit,
            total_pages=total_pages
        )

    except Exception as e:
        logger.error(f"[LEADS_API] Error in list_leads_endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao buscar leads."
        )


@router.get("/stats")
async def get_leads_stats_endpoint():
    """
    Retorna estatísticas resumidas dos leads.
    """
    logger.info("[LEADS_API] get_leads_stats_endpoint called")

    if not settings.db_pool:
        logger.error("[LEADS_API] Database pool not available.")
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não disponível."
        )

    try:
        stats_sql = """
            SELECT
                COUNT(*) as total_leads,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_leads,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_leads,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_leads,
                SUM(CASE WHEN conversation_initiator = 'user' THEN 1 ELSE 0 END) as user_initiated,
                SUM(CASE WHEN conversation_initiator = 'llm_agent' THEN 1 ELSE 0 END) as agent_initiated
            FROM prospects
            WHERE instance_id = %s
        """

        tags_sql = """
            SELECT
                JSON_UNQUOTE(tag_value) as tag,
                COUNT(*) as count
            FROM prospects,
            JSON_TABLE(tags, '$[*]' COLUMNS (tag_value VARCHAR(100) PATH '$')) AS jt
            WHERE instance_id = %s
            GROUP BY tag_value
            ORDER BY count DESC
            LIMIT 10
        """

        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Stats gerais
                await cursor.execute(stats_sql, (settings.INSTANCE_ID,))
                stats_row = await cursor.fetchone()

                # Top tags
                await cursor.execute(tags_sql, (settings.INSTANCE_ID,))
                tags_rows = await cursor.fetchall()

        top_tags = [{'tag': row['tag'], 'count': row['count']} for row in tags_rows] if tags_rows else []

        return {
            'total_leads': stats_row['total_leads'] if stats_row else 0,
            'active_leads': stats_row['active_leads'] if stats_row else 0,
            'completed_leads': stats_row['completed_leads'] if stats_row else 0,
            'failed_leads': stats_row['failed_leads'] if stats_row else 0,
            'user_initiated': stats_row['user_initiated'] if stats_row else 0,
            'agent_initiated': stats_row['agent_initiated'] if stats_row else 0,
            'top_tags': top_tags
        }

    except Exception as e:
        logger.error(f"[LEADS_API] Error in get_leads_stats_endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao buscar estatísticas."
        )


logger.info("[LEADS_API] Módulo carregado.")
