# -*- coding: utf-8 -*-
import logging
import json
from typing import Optional, Any, Dict, List

from src.api.routes.config_models import FirstMessageConfig

from src.core.config import settings, logger
from src.api.routes.config_models import ProductContextResponse

logger = logging.getLogger(__name__)

async def get_config_value(key: str, default: Optional[Any] = None, instance_id: Optional[str] = None) -> Optional[Any]:
    # Usa o instance_id fornecido, ou recorre ao settings.INSTANCE_ID como fallback
    final_instance_id = instance_id or settings.INSTANCE_ID
    logger.info(f"[CONFIG_CRUD_DEBUG] get_config_value para key='{key}'. instance_id recebido='{instance_id}', final_instance_id='{final_instance_id}'.")

    if not final_instance_id:
        logger.error(f"[CONFIG_CRUD_DEBUG] FATAL: final_instance_id é NULO ou VAZIO para a chave '{key}'. Não é possível consultar a DB.")
        return default

    logger.debug(f"db_operations.config_crud: Fetching config value for key '{key}' for instance '{final_instance_id}'.")
    if not settings.db_pool:
        logger.warning(f"db_operations.config_crud: Database pool not available. Cannot fetch config '{key}'. Returning default.")
        return default
    try:
        async with settings.db_pool.acquire() as conn: # Use settings.db_pool
            async with conn.cursor() as cursor:
                await cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;")
                sql = "SELECT config_value FROM application_config WHERE instance_id = %s AND config_key = %s"
                logger.info(f"[CONFIG_CRUD_DEBUG] Executando SQL: {sql} com parâmetros: ('{final_instance_id}', '{key}')")
                await cursor.execute(sql, (final_instance_id, key))
                result = await cursor.fetchone()
                logger.info(f"[CONFIG_CRUD_DEBUG] Resultado da DB para key='{key}', instance='{final_instance_id}': {result}")
                # Alterado para DEBUG para não poluir os logs de produção com o contexto completo
                logger.debug(f"db_operations.config_crud: Raw DB result for key '{key}', instance '{instance_id}': {result}")
                value = result['config_value'] if result else default
                
                if key == "google_calendar_availability_schedule" or key == "google_calendar_api_key": # Adicionado log para google_calendar_api_key também
                    logger.info(f"db_operations.config_crud: [DEBUG_CONFIG_GET] Value for '{key}' after fetch (before JSON parse): '{value}' (Type: {type(value)})")

                if isinstance(value, str) and value.strip().startswith(('[', '{')):
                    try:
                        parsed_value = json.loads(value)
                        logger.debug(f"db_operations.config_crud: Config '{key}' parsed as JSON.")
                        if key == "google_calendar_availability_schedule":
                             logger.info(f"db_operations.config_crud: [DEBUG_CONFIG_GET] Parsed JSON value for '{key}': {json.dumps(parsed_value, indent=2)}")
                             logger.info(f"db_operations.config_crud: [DEBUG_CONFIG_GET] 'include_video_call' in parsed JSON: {parsed_value.get('include_video_call')} (Type: {type(parsed_value.get('include_video_call'))})")
                        return parsed_value
                    except json.JSONDecodeError:
                        logger.debug(f"db_operations.config_crud: Config '{key}' is string but not valid JSON. Returning raw string.")
                        pass
                logger.debug(f"db_operations.config_crud: Config '{key}' fetched successfully. Value: {str(value)[:100]}...")
                return value
    except Exception as e:
        logger.error(f"db_operations.config_crud: Error fetching config '{key}' for instance '{instance_id}': {e}", exc_info=True)
        return default

async def set_config_value(key: str, value: Any) -> bool:
    instance_id = settings.INSTANCE_ID
    if not settings.db_pool: # Use settings.db_pool
        logger.error(f"db_operations.config_crud: Database pool not available. Cannot save config '{key}'.")
        return False
    
    sql = """
        INSERT INTO application_config (instance_id, config_key, config_value) 
        VALUES (%s, %s, %s)
        AS new_values
        ON DUPLICATE KEY UPDATE 
            config_value = new_values.config_value, 
            updated_at = CURRENT_TIMESTAMP
    """
    value_to_save = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    
    if key == "google_calendar_availability_schedule":
        logger.info(f"db_operations.config_crud: [DEBUG_CONFIG_SET] Attempting to save raw value for '{key}': {value_to_save}")
        try:
            # Log o valor específico de include_video_call que está sendo salvo
            data_to_log = json.loads(value_to_save) # value_to_save é uma string JSON
            logger.info(f"db_operations.config_crud: [DEBUG_CONFIG_SET] 'include_video_call' being saved to DB for '{key}': {data_to_log.get('include_video_call')} (Type: {type(data_to_log.get('include_video_call'))})")
        except json.JSONDecodeError:
            logger.warning(f"db_operations.config_crud: [DEBUG_CONFIG_SET] Could not parse value_to_save as JSON for detailed logging of '{key}'.")


    logger.debug(f"db_operations.config_crud: Attempting to save config: Key='{key}', Value='{value_to_save[:100]}...' for Instance='{instance_id}'")
    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor: # Use settings.db_pool
            await cursor.execute(sql, (instance_id, key, value_to_save))
            rows_affected = cursor.rowcount
            logger.info(f"db_operations.config_crud: Config '{key}' saved successfully for instance '{instance_id}'. Rows affected: {rows_affected}.")
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"db_operations.config_crud: Error saving config '{key}' for instance '{instance_id}': {e}", exc_info=True)
        return False

async def get_evolution_config() -> Dict[str, Optional[str]]:
    logger.debug("db_operations.config_crud: Getting Evolution API configuration.")
    return {
        "url": await get_config_value("evolution_api_url"),
        "api_key": await get_config_value("evolution_api_key"),
        "instance_name": await get_config_value("evolution_instance_name")
    }

async def set_evolution_config(url: str, api_key: str, instance_name: str) -> bool:
    logger.debug(f"db_operations.config_crud: Setting Evolution API configuration: URL={url}, Instance={instance_name}, KeyProvided={bool(api_key)}.")
    if not all([url, api_key, instance_name]):
        logger.warning("db_operations.config_crud: Missing required fields for Evolution config. Aborting save.")
        return False
    return all([
        await set_config_value("evolution_api_url", url),
        await set_config_value("evolution_api_key", api_key),
        await set_config_value("evolution_instance_name", instance_name)
    ])

async def get_product_context(instance_id: str = None) -> ProductContextResponse:
    logger.debug(f"db_operations.config_crud: Getting product context for instance_id='{instance_id}'.")
    # get_config_value tenta parsear JSON, retornando um dict em caso de sucesso, ou str caso contrário.
    context_data = await get_config_value("product_context", {}, instance_id=instance_id)

    if isinstance(context_data, dict):
        logger.debug("db_operations.config_crud: Product context loaded as a dictionary.")
        # Garante que o objeto ProductContextResponse seja criado de forma segura.
        return ProductContextResponse(
            context=context_data.get('context'),
            db_url=context_data.get('db_url'),
            sql_query=context_data.get('sql_query'),
            db_data=context_data.get('db_data')
        )
    
    # Se não for um dicionário, trata como um contexto de texto simples.
    logger.debug(f"db_operations.config_crud: Product context loaded as plain text (type: {type(context_data)}).")
    return ProductContextResponse(context=str(context_data or ""))

async def set_product_context(context_json_str: str) -> bool:
    logger.debug(f"db_operations.config_crud: Setting product context (length: {len(context_json_str)}).")
    return await set_config_value("product_context", context_json_str)

async def get_llm_system_prompt(instance_id: str = None) -> str:
    logger.debug(f"db_operations.config_crud: Getting LLM system prompt for instance_id='{instance_id}'.")
    prompt = await get_config_value("llm_system_prompt", "", instance_id=instance_id)
    default_prompt = """
Você é Melissa, uma assistente de vendas da Innova Fluxo, especialista em prospecção via WhatsApp. Seu objetivo é guiar o cliente pelo funil de vendas de forma natural e eficiente.
**REGRAS GERAIS:**
- Seja cordial, profissional e direto(a).
- Use o CONTEXTO DO PRODUTO fornecido para responder perguntas.
- Siga o OBJETIVO DO ESTÁGIO atual.
- Analise o FLUXO DE VENDAS COMPLETO para entender a jornada.
- Responda **APENAS** no formato JSON especificado.
**FORMATO OBRIGATÓRIO DA RESPOSTA JSON:**
```json
{
  "action": "send_text | send_audio | wait | end_conversation",
  "text": "string (obrigatório se action=send_text/end_conversation)",
  "audio_file": "string (obrigatório se action=send_audio, nome do arquivo .ogg)",
  "reason": "string (obrigatório, sua justificativa para a ação)",
  "next_stage": number (OPCIONAL, inclua APENAS se o usuário claramente aceitou avançar)
}
```"""
    return prompt if prompt else default_prompt.strip()

async def set_llm_system_prompt(prompt: str) -> bool:
    logger.debug(f"db_operations.config_crud: Setting LLM system prompt (length: {len(prompt)}).")
    return await set_config_value("llm_system_prompt", prompt) if isinstance(prompt, str) and prompt.strip() else False

# As funções get_llm_preferences e set_llm_preferences foram removidas
# pois as configurações de LLM agora são lidas diretamente do settings (.env).

async def get_sales_flow_stages(instance_id: Optional[str] = None) -> List[Dict[str, Any]]:
    logger.debug(f"db_operations.config_crud: Getting sales flow stages for instance '{instance_id}'.")
    try:
        # Passa o instance_id para a função get_config_value
        stages = await get_config_value("sales_flow_stages", [], instance_id=instance_id)
        
        # Verificar se stages é uma lista válida
        if not isinstance(stages, list):
            logger.warning(f"db_operations.config_crud: sales_flow_stages is not a list (type: {type(stages)}). Returning empty list.")
            return []
        # Se a lista está vazia, gerar, salvar e retornar uma nova configuração
        if not stages:
            logger.warning(f"db_operations.config_crud: sales_flow_stages está vazio para a instância '{instance_id}'. Iniciando geração automática.")
            try:
                from src.core.llm import generate_sales_flow_from_context
                
                # 1. Obter o contexto do produto para a instância
                product_context = await get_product_context(instance_id=instance_id)
                if not product_context or not product_context.context:
                    logger.error(f"Não foi possível gerar o funil de vendas: o contexto do produto está vazio para a instância '{instance_id}'.")
                    return [] # Retorna vazio para evitar loop infinito

                # 2. Gerar o novo funil de vendas usando a LLM
                logger.info(f"Gerando novo funil de vendas para a instância '{instance_id}' com base no contexto do produto.")
                generated_stages = await generate_sales_flow_from_context(product_context)

                if not generated_stages:
                    logger.error("A geração do funil de vendas retornou uma lista vazia. Verifique o módulo LLM.")
                    return []

                # 3. Salvar o novo funil no banco de dados para uso futuro
                logger.info(f"Salvando o novo funil de vendas com {len(generated_stages)} estágios para a instância '{instance_id}'.")
                await set_sales_flow_stages(generated_stages)
                
                # 4. Retornar o funil recém-gerado para uso imediato
                return generated_stages

            except Exception as e_generate:
                logger.error(f"Falha crítica durante a geração automática do funil de vendas para a instância '{instance_id}': {e_generate}", exc_info=True)
                return [] # Retorna vazio em caso de erro na geração

        return stages
    except Exception as e:
        logger.error(f"db_operations.config_crud: Error getting sales flow stages: {e}", exc_info=True)
        return []

async def set_sales_flow_stages(stages: List[Dict[str, Any]]) -> bool:
    logger.debug(f"db_operations.config_crud: Setting sales flow stages (count: {len(stages)}).")
    return await set_config_value("sales_flow_stages", stages) if isinstance(stages, list) else False

async def get_follow_up_rules() -> List[Dict[str, Any]]:
    logger.debug("db_operations.config_crud: Getting follow-up rules.")
    return await get_config_value("followup_rules", []) or []

async def set_follow_up_rules(rules: List[Dict[str, Any]]) -> bool:
    logger.debug(f"db_operations.config_crud: Setting follow-up rules (count: {len(rules)}).")
    return await set_config_value("followup_rules", rules) if isinstance(rules, list) else False

async def get_prospecting_delays() -> Dict[str, Optional[int]]:
    logger.debug("db_operations.config_crud: Getting prospecting delays.")
    min_d_str = await get_config_value("min_delay_seconds", str(settings.MIN_DELAY_SECONDS))
    max_d_str = await get_config_value("max_delay_seconds", str(settings.MAX_DELAY_SECONDS))
    
    min_delay_val = settings.MIN_DELAY_SECONDS
    if min_d_str is not None:
        try:
            min_delay_val = int(min_d_str)
        except ValueError:
            logger.warning(f"Invalid value for min_delay_seconds in config: '{min_d_str}'. Using default: {settings.MIN_DELAY_SECONDS}")
            min_delay_val = settings.MIN_DELAY_SECONDS

    max_delay_val = settings.MAX_DELAY_SECONDS
    if max_d_str is not None:
        try:
            max_delay_val = int(max_d_str)
        except ValueError:
            logger.warning(f"Invalid value for max_delay_seconds in config: '{max_d_str}'. Using default: {settings.MAX_DELAY_SECONDS}")
            max_delay_val = settings.MAX_DELAY_SECONDS
            
    return {"min_delay": min_delay_val, "max_delay": max_delay_val}

async def get_schedule_times() -> Dict[str, Optional[str]]: # Adicionando get_schedule_times que também estava faltando
    logger.debug("db_operations.config_crud: Getting schedule times.")
    start_time = await get_config_value("schedule_start_time", "08:00")
    end_time = await get_config_value("schedule_end_time", "17:00")
    return {"start_time": start_time, "end_time": end_time}

async def get_allowed_weekdays() -> List[int]:
    """
    Obtém os dias da semana permitidos para prospecção.
    Segunda-feira = 0, Domingo = 6.
    """
    logger.debug("db_operations.config_crud: Getting allowed weekdays.")
    # O padrão correto para Segunda a Sexta é [0, 1, 2, 3, 4]
    default_weekdays = json.dumps([0, 1, 2, 3, 4])
    raw_value = await get_config_value("allowed_weekdays", default_weekdays)
    
    days_list_to_check = None
    
    if isinstance(raw_value, list):
        days_list_to_check = raw_value
    elif isinstance(raw_value, str):
        try:
            days_list_to_check = json.loads(raw_value)
        except json.JSONDecodeError:
            logger.warning(f"JSONDecodeError for allowed_weekdays in config: '{raw_value}'. Using default.")
            return json.loads(default_weekdays)
    else:
        logger.warning(f"Unexpected type for allowed_weekdays in config: {type(raw_value)}. Value: '{raw_value}'. Using default.")
        return json.loads(default_weekdays)

    if isinstance(days_list_to_check, list) and all(isinstance(day, int) and 0 <= day <= 6 for day in days_list_to_check):
        return days_list_to_check
    
    logger.warning(f"Invalid format or content for allowed_weekdays in config: '{raw_value}'. Using default.")
    return json.loads(default_weekdays)

async def set_schedule_times(start_time: str, end_time: str) -> bool:
    logger.debug(f"db_operations.config_crud: Setting schedule times: Start='{start_time}', End='{end_time}'.")
    s1 = await set_config_value("schedule_start_time", start_time)
    s2 = await set_config_value("schedule_end_time", end_time)
    return s1 and s2

async def set_prospecting_delays(min_delay: int, max_delay: int) -> bool:
    logger.debug(f"db_operations.config_crud: Setting prospecting delays: Min='{min_delay}', Max='{max_delay}'.")
    s1 = await set_config_value("min_delay_seconds", str(min_delay))
    s2 = await set_config_value("max_delay_seconds", str(max_delay))
    return s1 and s2

async def set_allowed_weekdays(days: List[int]) -> bool:
    logger.debug(f"db_operations.config_crud: Setting allowed weekdays: {days}.")
    return await set_config_value("allowed_weekdays", json.dumps(days))

async def get_initial_message_counter() -> int:
    counter_str = await get_config_value("initial_message_counter", "0")
    try:
        return int(counter_str)
    except ValueError:
        logger.warning(f"db_operations.config_crud: Invalid value for initial_message_counter in config: '{counter_str}'. Using 0.")
        return 0

async def increment_initial_message_counter() -> bool:
    current_count = await get_initial_message_counter()
    return await set_config_value("initial_message_counter", str(current_count + 1))

async def get_first_message_config() -> FirstMessageConfig:
    logger.debug("db_operations.config_crud: Getting first message configuration.")
    raw_config = await get_config_value("first_message_config", {})
    if isinstance(raw_config, str): # Case config is saved as JSON string
        try:
            raw_config = json.loads(raw_config)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON for first_message_config. Using default.")
            raw_config = {}
    
    messages = raw_config.get("messages", ["Olá [NOME], sou da [LISTA]..."])
    if not isinstance(messages, list) or not all(isinstance(m, str) for m in messages):
        logger.warning("Invalid 'messages' format in first_message_config. Using default messages.")
        messages = ["Olá [NOME], sou da [LISTA]..."]

    enabled = raw_config.get("enabled", True)
    if not isinstance(enabled, bool):
        logger.warning("Invalid 'enabled' format in first_message_config. Using default True.")
        enabled = True

    return FirstMessageConfig(messages=messages, enabled=enabled)

async def set_first_message_config(config: FirstMessageConfig) -> bool:
    logger.debug(f"db_operations.config_crud: Setting first message configuration: {config.model_dump_json()}.")
    return await set_config_value("first_message_config", config.model_dump_json())

async def get_ai_for_prospect_queue_only(instance_id: str = None) -> bool:
    logger.debug(f"db_operations.config_crud: Getting 'ai_for_prospect_queue_only' setting for instance_id='{instance_id}'.")
    # Default to "false" if not found in DB, then convert to boolean
    value_str = await get_config_value("ai_for_prospect_queue_only", "false", instance_id=instance_id)
    return str(value_str).lower() == "true"

async def set_ai_for_prospect_queue_only(enabled: bool) -> bool:
    logger.debug(f"db_operations.config_crud: Setting 'ai_for_prospect_queue_only' to {enabled}.")
    # Store as string "true" or "false"
    return await set_config_value("ai_for_prospect_queue_only", str(enabled).lower())

async def get_all_configs_as_dict() -> Dict[str, Any]:
    """Fetches all configuration key-value pairs for the current instance."""
    instance_id = settings.INSTANCE_ID
    logger.info(f"db_operations.config_crud: Fetching all config values for instance '{instance_id}'.")
    configs = {}
    if not settings.db_pool:
        logger.error("db_operations.config_crud: Database pool not available. Cannot fetch all configs.")
        return configs
    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "SELECT config_key, config_value FROM application_config WHERE instance_id = %s"
                await cursor.execute(sql, (instance_id,))
                results = await cursor.fetchall()
                for row in results:
                    key = row['config_key']
                    value = row['config_value']
                    # Attempt to parse JSON strings back into objects/lists
                    if isinstance(value, str) and value.strip().startswith(('[', '{')):
                        try:
                            configs[key] = json.loads(value)
                        except json.JSONDecodeError:
                            configs[key] = value # Keep as string if not valid JSON
                    else:
                        configs[key] = value
                logger.info(f"db_operations.config_crud: Fetched {len(configs)} config items for instance '{instance_id}'.")
                return configs
    except Exception as e:
        logger.error(f"db_operations.config_crud: Error fetching all configs for instance '{instance_id}': {e}", exc_info=True)
        return {}

async def get_insufficient_context_notification_config(instance_id: str = None) -> Dict[str, Any]:
    """
    Obtém a configuração de notificação para contexto insuficiente.
    """
    logger.debug(f"db_operations.config_crud: Getting insufficient context notification config for instance_id='{instance_id}'.")
    raw_config = await get_config_value("insufficient_context_notification_config", {}, instance_id=instance_id)

    # Se for string, tentar parsear como JSON
    if isinstance(raw_config, str):
        try:
            raw_config = json.loads(raw_config)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON for insufficient_context_notification_config. Using default.")
            raw_config = {}

    # Valores padrão
    default_config = {
        "enabled": True,
        "notification_whatsapp_number": None,
        "notification_message_template": "⚠️ *Contexto Insuficiente Detectado*\n\n📱 *Cliente:* {customer_phone}\n💬 *Mensagem:* {customer_message}\n\n❓ O agente de IA não encontrou informações suficientes no contexto para responder esta pergunta.\n\n⏰ *Horário:* {timestamp}",
        "suppress_response_to_customer": False,
        "customer_fallback_message": "Entendi sua dúvida. Vou verificar essa informação e retorno em breve!"
    }

    # Merge com valores padrão
    if isinstance(raw_config, dict):
        for key, value in default_config.items():
            if key not in raw_config:
                raw_config[key] = value
        return raw_config

    return default_config


async def set_insufficient_context_notification_config(config_data: Dict[str, Any]) -> bool:
    """
    Salva a configuração de notificação para contexto insuficiente.
    """
    logger.debug(f"db_operations.config_crud: Setting insufficient context notification config: {config_data}")
    return await set_config_value("insufficient_context_notification_config", config_data)


async def get_stage_change_notification_config(instance_id: str = None) -> Dict[str, Any]:
    """
    Obtém a configuração de notificação para mudança de etapa.
    """
    logger.debug(f"db_operations.config_crud: Getting stage change notification config for instance_id='{instance_id}'.")
    raw_config = await get_config_value("stage_change_notification_config", {}, instance_id=instance_id)

    # Se for string, tentar parsear como JSON
    if isinstance(raw_config, str):
        try:
            raw_config = json.loads(raw_config)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON for stage_change_notification_config. Using default.")
            raw_config = {}

    # Valores padrão
    default_config = {
        "enabled": True,
        "notification_whatsapp_number": None,
        "notify_all_stages": True,
        "stage_rules": [],
        "default_message_template": "🎯 *Prospect Avançou de Etapa!*\n\n👤 *Nome:* {prospect_name}\n📱 *Telefone:* {prospect_phone}\n\n📊 *Etapa Anterior:* {old_stage_name}\n📊 *Nova Etapa:* {stage_name}\n⏰ *Horário:* {timestamp}"
    }

    # Merge com valores padrão
    if isinstance(raw_config, dict):
        for key, value in default_config.items():
            if key not in raw_config:
                raw_config[key] = value
        return raw_config

    return default_config


async def set_stage_change_notification_config(config_data: Dict[str, Any]) -> bool:
    """
    Salva a configuração de notificação para mudança de etapa.
    """
    logger.debug(f"db_operations.config_crud: Setting stage change notification config: {config_data}")
    return await set_config_value("stage_change_notification_config", config_data)


logger.info("db_operations.config_crud: Module loaded.")
