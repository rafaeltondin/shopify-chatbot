# -*- coding: utf-8 -*-
import logging
import asyncio
import random
import httpx
from typing import Dict, Any, Optional
from datetime import datetime, time # Adicionado time
import pytz

from src.core.config import settings, logger
from src.core.prospect_management.state import ProspectState, get_prospect, save_prospect, add_message_to_history_state, update_prospect_stage_state, add_prospect_state
from src.core.db_operations import config_crud, prospect_crud # Modificado para importar config_crud e prospect_crud
from src.core import evolution # Para enviar mensagens
from src.utils import audio_utils, message_utils, formatting # Para utilitários de mensagem e áudio e FORMATAÇÃO
from src.api.routes.config_models import FirstMessageConfig # Importar o modelo
from src.core.llm import get_llm_response # Importar a função da LLM

logger = logging.getLogger(__name__)

FLOW_AUDIO_DIR = settings.FLOW_AUDIO_DIR

# In-memory state for prospect tasks (specific to flow_logic)
_prospect_tasks_fl: Dict[str, asyncio.Task] = {}

async def process_queued_prospect_flow(jid: str, name: Optional[str] = None) -> str:
    logger.info(f"[{jid}] [PROCESS_QUEUED_FLOW] Processing queued prospect (Name: {name if name else 'N/A'}).")
    if not jid:
        logger.warning("[PROCESS_QUEUED_FLOW] JID is empty. Ignoring.")
        return 'INVALID_JID'

    if jid in _prospect_tasks_fl and not _prospect_tasks_fl[jid].done():
        logger.info(f"[{jid}] [PROCESS_QUEUED_FLOW] Active task already exists. Ignoring.")
        return 'TASK_ALREADY_ACTIVE'

    prospect = await get_prospect(jid)
    if not prospect:
        logger.info(f"[{jid}] [PROCESS_QUEUED_FLOW] Prospect not found. Adding new (stage 1, initiator: llm_agent, name: {name}).")
        prospect = await add_prospect_state(jid, initial_stage=1, conversation_initiator='llm_agent', name=name)

    if not prospect:
        logger.error(f"[{jid}] [PROCESS_QUEUED_FLOW] Failed to get/create prospect.")
        return 'ERROR_GETTING_PROSPECT'

    # --- NOVA LÓGICA: VERIFICAÇÃO DE HORÁRIO E DIA DA SEMANA ---
    prospecting_config = await config_crud.get_schedule_times()
    allowed_weekdays = await config_crud.get_allowed_weekdays()
    
    start_time_obj = datetime.strptime(prospecting_config.get("start_time", "00:00"), "%H:%M").time()
    end_time_obj = datetime.strptime(prospecting_config.get("end_time", "23:59"), "%H:%M").time()
    
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    current_time_local = datetime.now(sao_paulo_tz).time()
    current_weekday = datetime.now(sao_paulo_tz).weekday() # Monday is 0, Sunday is 6

    if current_weekday not in allowed_weekdays or not (start_time_obj <= current_time_local <= end_time_obj):
        logger.info(f"[{jid}] [PROCESS_QUEUED_FLOW] Prospect deferred: Outside allowed hours/days. Current: Day {current_weekday}, Time {current_time_local}. Allowed: Days {allowed_weekdays}, Hours {start_time_obj}-{end_time_obj}.")
        return 'DEFERRED_OUTSIDE_HOURS'
    # --- FIM DA NOVA LÓGICA ---

    logger.info(f"[{jid}] [PROCESS_QUEUED_FLOW] Prospect obtained/created. Stage: {prospect.stage}. Creating task _execute_flow_stage_logic.")
    task = asyncio.create_task(_execute_flow_stage_logic(prospect))
    _prospect_tasks_fl[jid] = task

    try:
        await task
        logger.info(f"[{jid}] [PROCESS_QUEUED_FLOW] Task _execute_flow_stage_logic completed.")
        return 'PROCESSED'
    except Exception as e_task:
        logger.error(f"[{jid}] [PROCESS_QUEUED_FLOW] Exception in task _execute_flow_stage_logic: {e_task}", exc_info=True)
        return 'ERROR_IN_TASK'
    finally:
        if jid in _prospect_tasks_fl and _prospect_tasks_fl[jid] is task:
            del _prospect_tasks_fl[jid]
        logger.debug(f"[{jid}] [PROCESS_QUEUED_FLOW] Task removed from _prospect_tasks_fl dictionary.")


async def _execute_stage_sequence_logic(prospect: ProspectState, stage_def: Dict[str, Any]):
    phone_number = prospect.jid
    current_stage_num = prospect.stage
    
    # ✅ NOVA VALIDAÇÃO: Verificar se o JID é válido antes de processar
    try:
        from src.core.evolution import check_whatsapp_numbers
        from src.utils.formatting import clean_phone_number
        
        clean_number = clean_phone_number(phone_number)
        if clean_number:
            logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Validando número WhatsApp antes do processamento...")
            valid_numbers = await check_whatsapp_numbers([clean_number])
            if not valid_numbers or clean_number not in valid_numbers:
                logger.error(f"[{phone_number}] [EXEC_SEQ_LOGIC] ❌ Número não possui WhatsApp válido. Marcando como erro.")
                
                from src.core.db_operations import prospect_crud
                await prospect_crud.update_prospect_status_db(phone_number, "invalid_whatsapp")
                await add_message_to_history_state(
                    phone_number, 
                    "system", 
                    "[SYSTEM] ❌ Número não possui WhatsApp válido. Prospecção cancelada.",
                    conversation_initiator_override=prospect.conversation_initiator
                )
                return
            else:
                logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] ✅ Número WhatsApp validado com sucesso.")
    except Exception as e_validation:
        logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] Falha na validação WhatsApp: {e_validation}. Continuando com processamento...")
    
    logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Executing sequence for stage {current_stage_num}. Def: {stage_def.get('objective', 'N/A')}")
    
    sequence_actions = stage_def.get("action_sequence", [])
    if not sequence_actions: 
        logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] No actions in sequence."); return

    initial_history_len = len(prospect.history) 

    for i, action_item in enumerate(sequence_actions):
        action_idx = i + 1
        logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Action {action_idx}/{len(sequence_actions)}: {action_item.get('type')}")

        try:
            updated_prospect = await get_prospect(phone_number)
            if not updated_prospect: 
                logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] Prospect disappeared. Interrupting sequence."); return
            if not updated_prospect.llm_paused and len(updated_prospect.history) > initial_history_len and updated_prospect.history[-1].get("role") == "user":
                logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] User responded. Interrupting sequence and triggering reactive LLM analysis.")
                # Em vez de apenas retornar, acionamos a lógica da LLM para analisar a resposta.
                # Isso garante que a conversa continue e o estágio possa ser reavaliado.
                await _execute_flow_stage_logic(updated_prospect)
                return

            delay_ms = action_item.get("delay_ms", 0)
            if delay_ms > 0 and i > 0: 
                logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Delaying {delay_ms}ms.")
                await asyncio.sleep(delay_ms / 1000.0)
                updated_prospect_after_delay = await get_prospect(phone_number)
                if not updated_prospect_after_delay: return
                if not updated_prospect_after_delay.llm_paused and len(updated_prospect_after_delay.history) > initial_history_len and updated_prospect_after_delay.history[-1].get("role") == "user":
                    logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] User responded during delay. Interrupting sequence and triggering reactive LLM analysis.")
                    # Aciona a lógica da LLM para analisar a resposta do usuário.
                    await _execute_flow_stage_logic(updated_prospect_after_delay)
                    return
            
            action_type = action_item.get("type")
            initiator_for_history = prospect.conversation_initiator

            if action_type == "send_text":
                text_or_list = action_item.get("text", "")
                
                # Lógica de rotação e seleção da mensagem
                selected_text = ""
                if isinstance(text_or_list, list) and len(text_or_list) > 0:
                    if current_stage_num == 1: # Aplicar rotação APENAS para o Estágio 1
                        first_msg_config = await config_crud.get_first_message_config()
                        if first_msg_config.enabled and first_msg_config.messages:
                            current_index = await config_crud.get_initial_message_counter()
                            selected_text = first_msg_config.messages[current_index % len(first_msg_config.messages)]
                            await config_crud.increment_initial_message_counter()
                            logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Selected initial message (rotated from FirstMessageConfig): Index {current_index % len(first_msg_config.messages)}.")
                        else:
                            selected_text = random.choice(text_or_list)
                            logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] First stage (fallback random from list): Selected message.")
                    else:
                        selected_text = random.choice(text_or_list)
                        logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Selected message (random from list) for stage {current_stage_num}.")
                elif isinstance(text_or_list, str):
                    selected_text = text_or_list
                    logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Selected message (single string).")
                else: # Empty list or other invalid type for text_or_list
                    logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] 'send_text' action with invalid text configuration. Skipping.")
                    continue
                
                if not selected_text:
                    logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] 'send_text' action without text (or empty list). Skipping.")
                    continue

                 # Lógica de substituição de placeholder [NOME]
                if prospect.name:
                    selected_text = selected_text.replace("[NOME]", prospect.name)
                else:
                    selected_text = selected_text.replace("[NOME]", "Olá")


                send_success = await _send_text_message_fl(phone_number, selected_text)
                
                if send_success:
                    await add_message_to_history_state(phone_number, "assistant", selected_text, conversation_initiator_override=initiator_for_history)
                    prospect.last_outgoing_message_at = datetime.now(pytz.utc)
                    await save_prospect(prospect) # <-- ADICIONADO PARA PERSISTIR O TIMESTAMP
                    initial_history_len += 1
                else:
                    logger.error(f"[{phone_number}] [EXEC_SEQ_LOGIC] Failed to send text message after retries. Marking prospect as error.")
                    # Correção: Importar prospect_crud localmente para evitar erro de referência
                    from src.core.db_operations import prospect_crud
                    await prospect_crud.update_prospect_status_db(phone_number, "send_error")
                    await add_message_to_history_state(phone_number, "system", "[SYSTEM] Falha no envio da mensagem de texto após múltiplas tentativas. O prospect foi marcado com erro de envio.", conversation_initiator_override=initiator_for_history)
                    break

            elif action_type == "send_audio":
                audio_file = action_item.get("audio_file", "").strip()
                caption = action_item.get("text", "").strip()
                if not audio_file:
                    logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] 'send_audio' action without file name. Skipping.")
                    continue
                
                audio_path = FLOW_AUDIO_DIR / audio_file
                if not audio_path.is_file():
                    logger.error(f"[{phone_number}] [EXEC_SEQ_LOGIC] Audio file '{audio_file}' not found. Skipping.")
                    continue

                send_success = await _send_audio_message_fl(phone_number, str(audio_path), caption)

                if send_success:
                    hist_log = f"[AUDIO (Sequence): {audio_file}]" + (f" {caption}" if caption else "")
                    await add_message_to_history_state(phone_number, "assistant", hist_log, conversation_initiator_override=initiator_for_history)
                    prospect.last_outgoing_message_at = datetime.now(pytz.utc)
                    await save_prospect(prospect) # <-- ADICIONADO PARA PERSISTIR O TIMESTAMP
                    initial_history_len += 1
                else:
                    logger.error(f"[{phone_number}] [EXEC_SEQ_LOGIC] Failed to send audio message after retries. Marking prospect as error.")
                    # Correção: Importar prospect_crud localmente para evitar erro de referência
                    from src.core.db_operations import prospect_crud
                    await prospect_crud.update_prospect_status_db(phone_number, "send_error")
                    await add_message_to_history_state(phone_number, "system", f"[SYSTEM] Falha no envio do áudio '{audio_file}' após múltiplas tentativas. O prospect foi marcado com erro de envio.", conversation_initiator_override=initiator_for_history)
                    break
            else: 
                logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] Unknown action type '{action_type}'. Skipping.")

        except asyncio.CancelledError: 
            logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Sequence cancelled."); raise
        except Exception as e_act: 
            logger.error(f"[{phone_number}] [EXEC_SEQ_LOGIC] Error in action {action_idx}: {e_act}", exc_info=True); break 

    logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Sequence for stage {current_stage_num} completed/interrupted.")
    
    # Re-fetch the latest prospect state to check for user responses during the sequence.
    final_check = await get_prospect(phone_number)
    if not final_check: 
        logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] Prospect disappeared after sequence. Aborting transition logic.")
        return

    # If the user responded during the sequence, the reactive flow will take over. Do not transition automatically.
    if not final_check.llm_paused and len(final_check.history) > initial_history_len and final_check.history[-1].get("role") == "user":
        logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] User responded during or after sequence. The reactive flow will handle the next step. No automatic stage transition will occur here.")
        # A lógica reativa já foi chamada se o usuário respondeu no meio da sequência.
        # Se respondeu exatamente ao final, o próximo webhook irá acionar a lógica.
        return

    # If the user did NOT respond, proceed with the automatic stage transition.
    next_stage_after_seq = stage_def.get("next_stage_after_sequence")
    if next_stage_after_seq and isinstance(next_stage_after_seq, int):
        logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Sequência concluída sem interrupção do usuário. Iniciando transição automática {current_stage_num} → {next_stage_after_seq}.")
        
        # Importar prospect_crud para verificação
        from src.core.db_operations import prospect_crud
        
        # Verificar estado atual antes de tentar transição
        current_prospect = await get_prospect(phone_number)
        if current_prospect and current_prospect.stage != next_stage_after_seq:
            max_retries = 3
            retry_count = 0
            transition_success = False
            
            while retry_count < max_retries and not transition_success:
                try:
                    logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Tentativa {retry_count+1}: Executando transição automática {current_stage_num} → {next_stage_after_seq}")
                    
                    # Executar a transição
                    await update_prospect_stage_state(phone_number, next_stage_after_seq)
                    
                    # Verificar se a transição foi bem-sucedida
                    await asyncio.sleep(0.5)  # Pequena pausa para garantir persistência
                    
                    # Buscar novamente para confirmar no banco de dados
                    updated_db_stage = await prospect_crud.get_prospect_stage(phone_number, settings.INSTANCE_ID)
                    
                    if updated_db_stage == next_stage_after_seq:
                        logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] ✅ Transição automática confirmada no DB: {current_stage_num} → {next_stage_after_seq}")
                        
                        # Adicionar ao histórico para rastreabilidade
                        await add_message_to_history_state(
                            phone_number,
                            "system",
                            f"[SYSTEM] ✅ Transição automática após sequência: Estágio {current_stage_num} → {next_stage_after_seq}",
                            conversation_initiator_override=prospect.conversation_initiator
                        )
                        
                        transition_success = True
                        break
                    else:
                        logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] ❌ Transição não confirmada no DB. Esperado: {next_stage_after_seq}, Encontrado: {updated_db_stage}")
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(1)  # Aguarda antes de retry
                        
                except Exception as e_auto:
                    logger.error(f"[{phone_number}] [EXEC_SEQ_LOGIC] Erro na tentativa {retry_count+1} de transição automática: {e_auto}", exc_info=True)
                    retry_count += 1
                    if retry_count < max_retries:
                        await asyncio.sleep(1)
            
            # Se não conseguiu fazer a transição após todas as tentativas
            if not transition_success:
                logger.error(f"[{phone_number}] [EXEC_SEQ_LOGIC] ❌ FALHA na transição automática após {max_retries} tentativas")
                await add_message_to_history_state(
                    phone_number,
                    "system",
                    f"[SYSTEM] ❌ ERRO na transição automática do estágio {current_stage_num} para {next_stage_after_seq} após {max_retries} tentativas",
                    conversation_initiator_override=prospect.conversation_initiator
                )
        else:
            if current_prospect:
                logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Prospect já está no estágio {next_stage_after_seq}. Nenhuma transição necessária.")
            else:
                logger.warning(f"[{phone_number}] [EXEC_SEQ_LOGIC] Prospect não encontrado. Não é possível executar transição automática.")
    else:
        logger.info(f"[{phone_number}] [EXEC_SEQ_LOGIC] Sequência concluída. Nenhuma transição automática definida. Prospect permanece no estágio {current_stage_num}.")
        await add_message_to_history_state(
            phone_number, 
            "system", 
            f"[SYSTEM] Sequência do estágio {current_stage_num} concluída. Aguardando resposta do usuário ou follow-up.",
            conversation_initiator_override=prospect.conversation_initiator
        )

async def _send_text_message_fl(phone_number: str, text: str) -> bool:
    """Wrapper function to send text messages using the message_handling implementation"""
    from src.core.prospect_management.message_handling import _send_text_message_mh
    return await _send_text_message_mh(phone_number, text)

async def _send_audio_message_fl(phone_number: str, audio_path: str, caption: str = "") -> bool:
    """Wrapper function to send audio messages using the message_handling implementation"""
    from src.core.prospect_management.message_handling import _send_audio_message_mh
    return await _send_audio_message_mh(phone_number, audio_path, caption)

async def _execute_flow_stage_logic(prospect: ProspectState):
    """
    FUNÇÃO CRÍTICA: Executa a lógica do estágio baseado no tipo de ação configurado.
    Esta função decide se deve executar uma sequência automática ou chamar o LLM para análise.

    Agora suporta múltiplos funis de vendas - busca o funil específico do prospect.
    """
    phone_number = prospect.jid
    current_stage_num = prospect.stage

    logger.info(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Iniciando lógica para estágio {current_stage_num}")

    try:
        # Buscar funil do prospect (suporte a múltiplos funis)
        from src.core.db_operations.funnel_crud import get_funnel_for_prospect

        prospect_funnel = await get_funnel_for_prospect(phone_number, settings.INSTANCE_ID)

        if prospect_funnel:
            sales_flow_stages = prospect_funnel.get("stages", [])
            funnel_name = prospect_funnel.get("name", "Desconhecido")
            logger.info(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Usando funil '{funnel_name}' (ID: {prospect_funnel.get('funnel_id')})")
        else:
            # Fallback para o sistema legado (application_config)
            logger.warning(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Nenhum funil encontrado, usando configuração legada")
            sales_flow_stages = await config_crud.get_sales_flow_stages()

        current_stage_def = None

        for stage in sales_flow_stages:
            if stage.get("stage_number") == current_stage_num:
                current_stage_def = stage
                break
        
        if not current_stage_def:
            logger.error(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Estágio {current_stage_num} não encontrado na configuração")
            await add_message_to_history_state(
                phone_number, 
                "system", 
                f"[SYSTEM] Erro: Configuração do estágio {current_stage_num} não encontrada",
                conversation_initiator_override=prospect.conversation_initiator
            )
            return
        
        action_type = current_stage_def.get("action_type")
        logger.info(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Estágio {current_stage_num} - Tipo de ação: {action_type}")
        
        if action_type == "sequence":
            logger.info(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Executando sequência automática para estágio {current_stage_num}")
            await _execute_stage_sequence_logic(prospect, current_stage_def)
            
        elif action_type == "ask_llm":
            logger.info(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Tipo 'ask_llm' detectado - aguardando interação do usuário")
            # Para estágios "ask_llm", não fazemos nada automaticamente
            # A lógica será acionada quando o usuário responder (via webhook)
            await add_message_to_history_state(
                phone_number, 
                "system", 
                f"[SYSTEM] Estágio {current_stage_num} configurado para análise LLM - aguardando resposta do prospect",
                conversation_initiator_override=prospect.conversation_initiator
            )
            
        else:
            logger.warning(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Tipo de ação desconhecido: '{action_type}' para estágio {current_stage_num}")
            await add_message_to_history_state(
                phone_number, 
                "system", 
                f"[SYSTEM] Erro: Tipo de ação '{action_type}' não reconhecido no estágio {current_stage_num}",
                conversation_initiator_override=prospect.conversation_initiator
            )
    
    except Exception as e:
        logger.error(f"[{phone_number}] [EXECUTE_FLOW_STAGE_LOGIC] Erro crítico ao executar lógica do estágio {current_stage_num}: {e}", exc_info=True)
        await add_message_to_history_state(
            phone_number, 
            "system", 
            f"[SYSTEM] Erro crítico na execução da lógica do estágio {current_stage_num}: {str(e)}",
            conversation_initiator_override=prospect.conversation_initiator
        )
