# -*- coding: utf-8 -*-
import logging
import asyncio
from typing import List, Dict, Any, Optional

from src.core.config import settings, logger
from src.core.prospect_management.main_prospect_logic import (
    initialize_redis_main as initialize_redis,
    close_redis_main as close_redis,
    add_jids_to_prospect_queue,
    handle_incoming_message_logic as handle_incoming_message,
    start_queue_processor_main as start_queue_processor,
    stop_queue_processor_main as stop_queue_processor,
    get_is_queue_paused as is_queue_paused,
    is_processing_queue_main, # Adicionada importação direta da variável
    pause_processing_queue as pause_queue,
    resume_processing_queue as resume_queue,
    get_current_queue_size as get_queue_size,
    clear_prospect_queue as clear_queue,
    start_message_handler as start_message_processor, # Renomeado para consistência
    stop_message_handler as stop_message_processor,   # Renomeado para consistência
    start_follow_up_processing as start_follow_up_scheduler,
    stop_follow_up_processing as stop_follow_up_scheduler,
    start_wallet_checker,
    stop_wallet_checker,
    get_total_prospected as get_total_prospected_count,
    get_funnel_data as get_funnel_counts,
    get_messages_sent as get_messages_sent_count,
    get_active_prospects as get_active_prospect_count,
    clear_redis_data as clear_all_redis_history,
    get_prospecting_schedule as get_schedule_times,
    set_prospecting_schedule as set_schedule_times,
    # get_prospecting_delays is already available via config_crud in main_prospect_logic
    # get_allowed_weekdays is already available via config_crud in main_prospect_logic
    get_all_jids_in_memory_queue as get_current_jids_in_queue, # Adicionado para exportar JIDs da fila
    get_all_follow_up_rules as get_follow_up_rules, # from config_crud via main_prospect_logic
    set_all_follow_up_rules as set_follow_up_rules, # from config_crud via main_prospect_logic
    clear_all_db_leads_and_conversations_main as clear_all_db_leads_and_conversations, # Importa a nova função combinada
    # Dead Letter Queue retry system
    get_dlq_items as get_dead_letter_queue_items,
    retry_dlq_item as retry_dead_letter_queue_item,
    process_dlq_retries as process_dead_letter_queue_retries,
    start_dlq_processor as start_dlq_retry_processor,
    stop_dlq_processor as stop_dlq_retry_processor,
)
# Import specific db operations if not exposed by main_prospect_logic
from src.core.prospect_management.queue import get_all_jids_in_memory_queue, is_jid_in_prospected_set # Importação adicionada
# Import get_total_token_usage para reexportar
from src.core.db_operations.prospect_crud import (
    get_total_token_usage,
    get_prospect_conversation_history, # Adicionado
    get_prospects_list # Adicionado
)
from src.core.db_operations import config_crud
from src.core.db_operations import config_crud


logger = logging.getLogger(__name__)

# As funções de estado do prospect (ProspectState, get_prospect, _save_prospect, add_prospect, update_prospect_stage, add_message_to_history)
# agora estão em src.core.prospect_management.state e são usadas internamente pelos handlers e lógicas de fluxo.
# As funções de controle de fila e processadores de background também foram movidas e são chamadas a partir de main_prospect_logic.

# Funções que ainda podem ser úteis diretamente neste módulo ou que são re-exportadas de main_prospect_logic
# para manter a interface anterior, se necessário.

# Expor a variável is_processing_queue_main para ser acessível como prospect_manager.is_processing_queue_main
# A importação já foi feita acima.

# Exemplo de como você pode re-exportar ou chamar funções de config_crud diretamente se necessário:
get_prospecting_delays = config_crud.get_prospecting_delays
set_prospecting_delays = config_crud.set_prospecting_delays
get_allowed_weekdays = config_crud.get_allowed_weekdays
set_allowed_weekdays = config_crud.set_allowed_weekdays

# Novas funções para FirstMessageConfig
get_first_message_config = config_crud.get_first_message_config
set_first_message_config = config_crud.set_first_message_config

# A função clear_all_db_history foi removida, pois clear_all_db_leads_and_conversations (importada acima) faz o trabalho.

logger.info("src.core.prospect: Module refactored to use prospect_management sub-package.")
