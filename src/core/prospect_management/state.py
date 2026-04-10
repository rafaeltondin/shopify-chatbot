# -*- coding: utf-8 -*-
import logging
import asyncio
import json
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import pytz
from pydantic import BaseModel, Field

from src.core.config import settings
# logger de config não é importado, pois o logger local é usado.
from src.core.db_operations import prospect_crud
from src.core.db_operations.prospect_crud import get_prospect_funnel_id
from src.core.db_operations import funnel_crud
from src.core.websocket_manager import manager
from src.core.stage_change_notifier import notify_stage_change_async

logger = logging.getLogger(__name__)

# Redis client will be initialized in main.py and assigned to settings.redis_client
# For direct use here, we assume settings.redis_client is available after app startup.

_cached_instance_prefix_state = None
_cached_keys_state = {}

def _get_instance_prefix_state() -> str:
    global _cached_instance_prefix_state
    if _cached_instance_prefix_state is None:
        _cached_instance_prefix_state = settings.INSTANCE_ID
    return _cached_instance_prefix_state

def _get_prospect_key_state(phone_number: str) -> str:
    return f"prospect:{_get_instance_prefix_state()}:{phone_number}"

class ProspectState(BaseModel):
    jid: str
    instance_id: str # Adicionar o campo instance_id
    name: Optional[str] = None
    stage: int = 1
    history: List[Dict[str, str]] = Field(default_factory=list)
    last_outgoing_message_at: Optional[datetime] = None
    applied_follow_up_rules: List[str] = Field(default_factory=list)
    task: Optional[asyncio.Task] = Field(default=None, exclude=True)
    email: Optional[str] = None 
    conversation_initiator: Optional[Literal['user', 'llm_agent']] = None
    llm_paused: bool = False

    class Config:
        arbitrary_types_allowed = True

async def get_prospect(phone_number: str) -> Optional[ProspectState]:
    logger.debug(f"[{phone_number}] [PROSPECT_STATE_GET] Attempting to get prospect from Redis.")

    prospect_from_redis = None

    # Tentar buscar do Redis primeiro
    if settings.redis_client:
        key = _get_prospect_key_state(phone_number)
        try:
            prospect_json = await settings.redis_client.get(key)
            if prospect_json:
                logger.debug(f"[{phone_number}] [PROSPECT_STATE_GET] Prospect JSON found in Redis (key: {key}): {prospect_json[:150]}...")
                prospect_data = json.loads(prospect_json)

                # Adicionar lógica de fallback para instance_id ausente (retrocompatibilidade)
                if 'instance_id' not in prospect_data:
                    logger.warning(f"[{phone_number}] [PROSPECT_STATE_GET] 'instance_id' not found in Redis data. Falling back to settings.INSTANCE_ID.")
                    prospect_data['instance_id'] = settings.INSTANCE_ID

                dt_str = prospect_data.get('last_outgoing_message_at')
                if isinstance(dt_str, str):
                    try:
                        dt_aware = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                        prospect_data['last_outgoing_message_at'] = dt_aware.astimezone(pytz.utc)
                    except Exception as e_dt:
                        logger.warning(f"[{phone_number}] [PROSPECT_STATE_GET] Failed to convert 'last_outgoing_message_at' ('{dt_str}') to datetime: {e_dt}. Setting to None.")
                        prospect_data['last_outgoing_message_at'] = None

                prospect_from_redis = ProspectState(**prospect_data)
                logger.info(f"[{phone_number}] [PROSPECT_STATE_GET] Prospect deserialized from Redis. Stage: {prospect_from_redis.stage}, Email: {prospect_from_redis.email}, LLM Paused: {prospect_from_redis.llm_paused}")
                return prospect_from_redis
            else:
                logger.debug(f"[{phone_number}] [PROSPECT_STATE_GET] No prospect found in Redis for key {key}. Trying database fallback...")
        except Exception as e:
            logger.error(f"[{phone_number}] [PROSPECT_STATE_GET] Error getting prospect from Redis: {e}. Trying database fallback...", exc_info=True)
    else:
        logger.warning(f"[{phone_number}] [PROSPECT_STATE_GET] Redis client not available. Trying database fallback...")

    # FALLBACK: Tentar buscar do banco de dados
    try:
        prospect_db = await prospect_crud.get_prospect_from_db(phone_number, settings.INSTANCE_ID)
        if prospect_db:
            logger.info(f"[{phone_number}] [PROSPECT_STATE_GET] [FALLBACK] Prospect encontrado no banco de dados!")

            # Buscar histórico do banco de dados
            history_entries = await prospect_crud.get_conversation_history_db(phone_number, settings.INSTANCE_ID, limit=settings.MAX_HISTORY_MESSAGES_PROSPECT_STATE)

            # Converter para formato do ProspectState
            history = [{"role": h.get("role", "user"), "content": h.get("content", "")} for h in history_entries]

            prospect_state = ProspectState(
                jid=phone_number,
                instance_id=settings.INSTANCE_ID,
                name=prospect_db.get("name"),
                stage=prospect_db.get("current_stage", 1),
                history=history,
                last_outgoing_message_at=prospect_db.get("last_interaction_at"),
                applied_follow_up_rules=[],
                email=None,  # Email não está no DB atual
                conversation_initiator=prospect_db.get("conversation_initiator"),
                llm_paused=prospect_db.get("llm_paused", False)
            )

            # Restaurar no Redis para futuras consultas
            if settings.redis_client:
                try:
                    save_success = await save_prospect(prospect_state)
                    if save_success:
                        logger.info(f"[{phone_number}] [PROSPECT_STATE_GET] [FALLBACK] Prospect restaurado no Redis a partir do DB")
                    else:
                        logger.warning(f"[{phone_number}] [PROSPECT_STATE_GET] [FALLBACK] Falha ao restaurar prospect no Redis")
                except Exception as e_save:
                    logger.error(f"[{phone_number}] [PROSPECT_STATE_GET] [FALLBACK] Erro ao restaurar no Redis: {e_save}")

            return prospect_state
        else:
            logger.info(f"[{phone_number}] [PROSPECT_STATE_GET] [FALLBACK] Prospect não encontrado no banco de dados.")
            return None

    except Exception as e_db:
        logger.error(f"[{phone_number}] [PROSPECT_STATE_GET] [FALLBACK] Erro ao buscar prospect do banco de dados: {e_db}", exc_info=True)
        return None

async def save_prospect(prospect: ProspectState, conversation_initiator: Optional[Literal['user', 'llm_agent']] = None) -> bool:
    logger.debug(f"[{prospect.jid}] [PROSPECT_STATE_SAVE] Attempting to save prospect to Redis. Initiator for DB: {conversation_initiator}")
    if not settings.redis_client:
        logger.error(f"[{prospect.jid}] [PROSPECT_STATE_SAVE] Redis client not available.")
        return False
    key = _get_prospect_key_state(prospect.jid)
    try:
        prospect_dict = prospect.model_dump(exclude={'task'}) 
        dt_utc = prospect_dict.get('last_outgoing_message_at')
        if isinstance(dt_utc, datetime):
            dt_utc = dt_utc.astimezone(pytz.utc) if dt_utc.tzinfo else pytz.utc.localize(dt_utc)
            prospect_dict['last_outgoing_message_at'] = dt_utc.isoformat(timespec='seconds').replace('+00:00', 'Z')
        
        prospect_json = json.dumps(prospect_dict)
        logger.debug(f"[{prospect.jid}] [PROSPECT_STATE_SAVE] JSON to save (key: {key}): {prospect_json[:200]}...")
        set_result = await settings.redis_client.set(key, prospect_json)
        
        if set_result:
            logger.info(f"[{prospect.jid}] [PROSPECT_STATE_SAVE] Prospect saved to Redis successfully.")
            return True
        else: 
            logger.error(f"[{prospect.jid}] [PROSPECT_STATE_SAVE] Failed to save prospect to Redis (set returned {set_result}).")
            return False
    except Exception as e:
        logger.error(f"[{prospect.jid}] [PROSPECT_STATE_SAVE] Generic error serializing or saving prospect: {type(e).__name__} - {e}", exc_info=True)
        return False

async def add_prospect_state(phone_number: str, initial_stage: int = 1, conversation_initiator: Optional[Literal['user', 'llm_agent']] = None, name: Optional[str] = None, instance_id: Optional[str] = None) -> Optional[ProspectState]:
    logger.info(f"[{phone_number}] [PROSPECT_STATE_ADD] Attempting to add new prospect state. Initial stage: {initial_stage}, Initiator: {conversation_initiator}, Name: {name}, Instance: {instance_id}")
    if not settings.redis_client:
        logger.error(f"[{phone_number}] [PROSPECT_STATE_ADD] Redis client not available.")
        return None

    prospect = ProspectState(
        jid=phone_number,
        instance_id=instance_id or settings.INSTANCE_ID, # Usar o instance_id fornecido ou o global
        name=name,
        stage=initial_stage,
        conversation_initiator=conversation_initiator,
        llm_paused=False
    )

    if not await save_prospect(prospect, conversation_initiator=conversation_initiator):
        logger.error(f"[{phone_number}] [PROSPECT_STATE_ADD] Failed to save initial prospect state to Redis. Aborting.")
        return None
    
    logger.info(f"[{phone_number}] [PROSPECT_STATE_ADD] New prospect state created and saved to Redis.")

    try:
        # Buscar o funil padrão para associar ao novo prospect
        default_funnel_id = None
        try:
            default_funnel = await funnel_crud.get_default_funnel(instance_id or settings.INSTANCE_ID)
            if default_funnel:
                default_funnel_id = default_funnel.get('funnel_id')
                logger.info(f"[{phone_number}] [PROSPECT_STATE_ADD] Funil padrão encontrado: '{default_funnel_id}'")
            else:
                logger.warning(f"[{phone_number}] [PROSPECT_STATE_ADD] Nenhum funil padrão configurado para a instância")
        except Exception as e_funnel:
            logger.warning(f"[{phone_number}] [PROSPECT_STATE_ADD] Erro ao buscar funil padrão: {e_funnel}")

        prospect_data_for_db = {
            'name': prospect.name,
            'current_stage': prospect.stage,
            'status': 'active',
            'conversation_initiator': prospect.conversation_initiator,
            'llm_paused': prospect.llm_paused
        }
        # Incluir funnel_id apenas se encontrado
        if default_funnel_id:
            prospect_data_for_db['funnel_id'] = default_funnel_id

        await prospect_crud.add_or_update_prospect_db(
            jid=prospect.jid,
            instance_id=settings.INSTANCE_ID,
            **prospect_data_for_db
        )
        logger.info(f"[{phone_number}] [PROSPECT_STATE_ADD] Prospect record successfully synced with PostgreSQL DB (funnel_id: {default_funnel_id}).")
    except Exception as e:
        key = _get_prospect_key_state(phone_number)
        logger.error(f"[{phone_number}] [PROSPECT_STATE_ADD] Failed to sync prospect with DB. Removing from Redis to prevent inconsistency. Error: {e}", exc_info=True)
        await settings.redis_client.delete(key)
        return None

    return prospect

async def update_prospect_stage_state(phone_number: str, new_stage: int, status: str = 'active'):
    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] === INÍCIO DA TRANSIÇÃO DE ESTÁGIO ===")
    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] Estágio desejado: {new_stage}, Status: {status}")

    # Verificar estado atual no Redis
    prospect = await get_prospect(phone_number)
    if not prospect:
        logger.error(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ❌ Prospect NÃO ENCONTRADO no Redis")
        raise Exception("Prospect não encontrado")

    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] Estado Redis - Estágio atual: {prospect.stage}")

    # Verificar estado atual no Banco de Dados
    try:
        db_stage = await prospect_crud.get_prospect_stage(phone_number, settings.INSTANCE_ID)
        logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] Estado DB - Estágio atual: {db_stage}")
    except Exception as e_db_check:
        logger.warning(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] Erro ao verificar estágio no DB: {e_db_check}")
        db_stage = None

    if prospect.stage == new_stage:
        logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ⚠️ Estágio {new_stage} já é o atual. Nenhuma alteração necessária.")
        return

    old_stage = prospect.stage
    prospect.stage = new_stage
    prospect.applied_follow_up_rules = []
    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ✏️ Alterando estágio Redis: {old_stage} → {new_stage}")
    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] 🔄 Regras de follow-up resetadas.")

    # Salvar no Redis
    save_success = await save_prospect(prospect)
    if not save_success:
        logger.error(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ❌ FALHA CRÍTICA ao salvar no Redis")
        raise Exception("Falha ao salvar no Redis")

    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ✅ Estado SALVO no Redis com sucesso")

    # ✅ FASE 3: Sincronizar com BD usando optimistic locking
    max_retries_optimistic = 3
    retry_count_optimistic = 0
    sync_success = False

    while retry_count_optimistic < max_retries_optimistic and not sync_success:
        try:
            logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] 🔄 Tentativa {retry_count_optimistic + 1}/{max_retries_optimistic} de sincronização com BD usando optimistic locking...")

            # Buscar versão atual do DB
            current_version = await prospect_crud.get_prospect_version(phone_number, settings.INSTANCE_ID)
            logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] Versão atual do DB: {current_version}")

            # Tentar update com versão
            update_success = await prospect_crud.update_prospect_stage_with_version(
                jid=prospect.jid,
                instance_id=settings.INSTANCE_ID,
                new_stage=prospect.stage,
                expected_version=current_version,
                status=status
            )

            if update_success:
                logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ✅ Sincronização BD CONFIRMADA com optimistic locking: estágio {new_stage}")
                sync_success = True

                # Transmitir evento WebSocket
                try:
                    await manager.broadcast(
                        "prospect_stage_updated",
                        {"jid": phone_number, "old_stage": old_stage, "new_stage": new_stage}
                    )
                    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] 📡 Evento WebSocket transmitido com sucesso")
                except Exception as e_ws:
                    logger.warning(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ⚠️ Falha no WebSocket (não crítico): {e_ws}")

                # Enviar notificação de mudança de etapa (fire and forget)
                try:
                    # Obter o funnel_id do prospect para filtro de notificações
                    prospect_funnel_id = await get_prospect_funnel_id(phone_number, settings.INSTANCE_ID)
                    asyncio.create_task(
                        notify_stage_change_async(
                            prospect_jid=phone_number,
                            prospect_name=prospect.name,
                            old_stage=old_stage,
                            new_stage=new_stage,
                            instance_id=settings.INSTANCE_ID,
                            prospect_funnel_id=prospect_funnel_id
                        )
                    )
                    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] 🔔 Notificação de mudança de etapa agendada (funil: {prospect_funnel_id})")
                except Exception as e_notify:
                    logger.warning(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ⚠️ Falha ao agendar notificação (não crítico): {e_notify}")

                # Disparar evento de automação para mudança de estágio (fire and forget)
                try:
                    from src.core.automation_engine import process_stage_change_event
                    asyncio.create_task(
                        process_stage_change_event(phone_number, old_stage, new_stage, settings.INSTANCE_ID)
                    )
                    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ⚡ Evento de automação de estágio disparado")
                except ImportError:
                    pass  # Motor de automação não disponível
                except Exception as e_auto:
                    logger.warning(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ⚠️ Falha no evento de automação (não crítico): {e_auto}")
            else:
                # Optimistic lock conflict - versão mudou
                logger.warning(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ⚠️ Conflito de versão detectado na tentativa {retry_count_optimistic + 1}")
                retry_count_optimistic += 1
                if retry_count_optimistic < max_retries_optimistic:
                    await asyncio.sleep(0.1 * (2 ** retry_count_optimistic))  # Exponential backoff

        except Exception as e_db:
            logger.error(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ❌ Erro na tentativa {retry_count_optimistic + 1}: {e_db}", exc_info=True)
            retry_count_optimistic += 1
            if retry_count_optimistic < max_retries_optimistic:
                await asyncio.sleep(0.1 * (2 ** retry_count_optimistic))

    if not sync_success:
        logger.error(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] ❌ FALHA CRÍTICA na sincronização BD após {max_retries_optimistic} tentativas")
        # Reverter mudança no Redis se DB falhou
        prospect.stage = old_stage
        await save_prospect(prospect)
        logger.warning(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] 🔄 Reversão Redis executada")
        raise Exception(f"Falha na sincronização BD após {max_retries_optimistic} tentativas")

    logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] === FIM DA TRANSIÇÃO DE ESTÁGIO ===")

    # Verificação final de estado
    try:
        final_redis_stage = (await get_prospect(phone_number)).stage if await get_prospect(phone_number) else None
        final_db_stage = await prospect_crud.get_prospect_stage(phone_number, settings.INSTANCE_ID)
        logger.info(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] 📊 Estado final - Redis: {final_redis_stage}, DB: {final_db_stage}")
    except Exception as e_final:
        logger.warning(f"[{phone_number}] [PROSPECT_STATE_UPDATE_STAGE] Erro na verificação final: {e_final}")

async def add_message_to_history_state(
    phone_number: str, 
    role: str, 
    content: str, 
    token_usage: Optional[Dict[str, Any]] = None,
    conversation_initiator_override: Optional[Literal['user', 'llm_agent']] = None
):
    logger.debug(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY] Adding message. Role: {role}, Content: '{content[:70]}...', InitiatorOverride: {conversation_initiator_override}")
    prospect = await get_prospect(phone_number)
    
    if prospect and prospect.history:
        last_message = prospect.history[-1]
        if last_message.get("role") == role and last_message.get("content") == content:
            logger.warning(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY] Duplicate message detected. Aborting to prevent duplicate history entry. Role: '{role}', Content: '{content[:70]}...'")
            return

    current_stage = prospect.stage if prospect else None
    
    current_initiator = conversation_initiator_override
    if current_initiator is None and prospect:
        current_initiator = prospect.conversation_initiator
    
    if prospect:
        if conversation_initiator_override and prospect.conversation_initiator is None:
            prospect.conversation_initiator = conversation_initiator_override

        prospect.history.append({"role": role, "content": content})
        max_history = settings.MAX_HISTORY_MESSAGES_PROSPECT_STATE
        if len(prospect.history) > max_history:
            prospect.history = prospect.history[-max_history:]
            logger.debug(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY] History truncated to {max_history} messages.")
        if role == 'assistant': 
            prospect.last_outgoing_message_at = datetime.now(pytz.utc)
        
        await save_prospect(prospect, conversation_initiator=current_initiator if current_initiator else prospect.conversation_initiator)
        logger.info(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY] Message added to Redis history. Effective Initiator for save: {current_initiator if current_initiator else prospect.conversation_initiator}")
    elif conversation_initiator_override:
        logger.info(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY] Prospect not in Redis, but initiator_override ('{conversation_initiator_override}') provided for DB history.")
        current_initiator = conversation_initiator_override
    else:
        logger.warning(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY] Prospect not found in Redis and no initiator_override. Initiator for DB history will be None.")

    try:
        logger.info(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY_DEBUG] Chamando add_history_entry_db com os seguintes parâmetros:")
        logger.info(f"  - jid: {phone_number}")
        logger.info(f"  - role: {role}")
        logger.info(f"  - content: {content[:100]}...")
        logger.info(f"  - stage: {current_stage}")
        logger.info(f"  - instance_id: {settings.INSTANCE_ID}")
        logger.info(f"  - conversation_initiator: {current_initiator} (Tipo: {type(current_initiator)})")

        await prospect_crud.add_history_entry_db(
            jid=phone_number, role=role, content=content, stage=current_stage,
            instance_id=settings.INSTANCE_ID,
            llm_model=token_usage.get("model") if token_usage else None,
            prompt_tokens=token_usage.get("prompt_tokens") if token_usage else None,
            completion_tokens=token_usage.get("completion_tokens") if token_usage else None,
            total_tokens=token_usage.get("total_tokens") if token_usage else None,
            conversation_initiator=current_initiator
        )
        logger.info(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY] History entry saved to DB. Stage: {current_stage}, Role: {role}, Initiator: {current_initiator}, Tokens: {token_usage if token_usage else 'N/A'}.")
    except Exception as e_db: 
        logger.error(f"[{phone_number}] [PROSPECT_STATE_ADD_HISTORY] Error saving history entry to DB: {e_db}", exc_info=True)

logger.info("prospect_management.state: Module loaded.")
