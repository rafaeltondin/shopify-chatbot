# -*- coding: utf-8 -*-
import logging
import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from decimal import Decimal # Adicionado para o encoder customizado
from datetime import datetime # Adicionado para o encoder customizado
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form, Query, status as http_status
from pydantic import ValidationError

from src.core import prospect as prospect_manager
from src.core.config import settings
from src.core.database import (
    get_config_value, set_config_value,
    get_evolution_config, set_evolution_config,
    get_product_context, set_product_context,
    get_llm_system_prompt, set_llm_system_prompt,
    get_sales_flow_stages, set_sales_flow_stages,
)
from src.core import evolution, llm
from datetime import datetime
from fastapi.responses import JSONResponse

from src.core.db_connector import execute_sql_query
from src.core.database import get_all_configs_as_dict

from src.api.routes.config_models import (
    ProspectingConfigRequest, ProspectingConfigResponse,
    FollowUpRule, FollowUpConfigRequest, FollowUpConfigResponse,
    EvolutionConfigRequest, EvolutionConfigResponse,
    ProductContextRequest, ProductContextResponse,
    SystemPromptRequest, SystemPromptResponse,
    SalesFlowConfigRequest, SalesFlowConfigResponse,
    GenerateSalesFlowRequest,
    FirstMessageConfig,
    FirstMessageConfigResponse,
    InsufficientContextNotificationRequest,
    InsufficientContextNotificationResponse,
    StageChangeNotificationRequest,
    StageChangeNotificationResponse,
    # Sales Funnels (Multiple Funnels Support)
    SalesFunnel,
    SalesFunnelSummary,
    FunnelListResponse,
    CreateFunnelRequest,
    UpdateFunnelRequest,
    FunnelResponse
)
from src.api.routes.wallet_models import GenericResponse
from src.api.routes.config_models import LLMConfigRequest, LLMConfigResponse

logger = logging.getLogger(__name__)
router = APIRouter()

FLOW_AUDIO_DIR = settings.FLOW_AUDIO_DIR

# Encoder JSON customizado para lidar com objetos Decimal
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj) # Converte Decimal para string
        if isinstance(obj, datetime):
            return obj.isoformat() # Converte datetime para string ISO
        return super().default(obj)

# --- Configuration Endpoints ---
@router.get("/config/prospecting", response_model=ProspectingConfigResponse, tags=["Configuration"])
async def get_prospecting_config():
    logger.info("[API_CONFIG_PROSPECTING_GET] Buscando config de prospecção...")
    schedule = await prospect_manager.get_schedule_times()
    delays = await prospect_manager.get_prospecting_delays()
    weekdays = await prospect_manager.get_allowed_weekdays()
    config_data = ProspectingConfigResponse(
        start_time=schedule.get("start_time"),
        end_time=schedule.get("end_time"),
        min_delay=delays.get("min_delay"),
        max_delay=delays.get("max_delay"),
        allowed_weekdays=weekdays
    )
    logger.debug(f"[API_CONFIG_PROSPECTING_GET] Config retornada: {config_data.model_dump_json(indent=2)}")
    return config_data

@router.post("/config/prospecting", response_model=ProspectingConfigResponse, tags=["Configuration"])
async def set_prospecting_config(config_data: ProspectingConfigRequest):
    logger.info(f"[API_CONFIG_PROSPECTING_POST] Atualizando config de prospecção: {config_data.model_dump_json(indent=2)}")
    if config_data.min_delay > config_data.max_delay:
        logger.warning("[API_CONFIG_PROSPECTING_POST] Erro: Atraso mínimo maior que máximo.")
        raise HTTPException(status_code=400, detail="Min delay cannot be greater than max delay.")
    
    s1 = await prospect_manager.set_schedule_times(config_data.start_time, config_data.end_time)
    s2 = await prospect_manager.set_prospecting_delays(config_data.min_delay, config_data.max_delay)
    s3 = await prospect_manager.set_allowed_weekdays(config_data.allowed_weekdays)
    
    if not (s1 and s2 and s3):
        err_msg = f"[API_CONFIG_PROSPECTING_POST] Falha ao salvar uma ou mais configs: schedule_ok={s1}, delays_ok={s2}, weekdays_ok={s3}"
        logger.error(err_msg)
        raise HTTPException(status_code=500, detail="Falha ao salvar uma ou mais configurações de prospecção.")
    
    logger.info("[API_CONFIG_PROSPECTING_POST] Config de prospecção salva. Retornando config atualizada.")
    return await get_prospecting_config()

# --- Sales Flow Config ---
@router.post("/config/sales-flow", response_model=SalesFlowConfigResponse, tags=["Configuration"])
async def set_sales_flow_endpoint(
    stages_json: str = Form(..., description="JSON string of the sales flow stages."),
    files: Optional[List[UploadFile]] = File(None, description="Audio files for Stage 1 sequence actions.")
):
    num_files = len(files) if files else 0
    logger.info(f"[API_CONFIG_SALESFLOW_POST] Atualizando fluxo de vendas. Arquivos recebidos: {num_files}.")
    logger.debug(f"[API_CONFIG_SALESFLOW_POST] JSON bruto recebido: {stages_json[:500]}...") 
    file_map: Dict[str, UploadFile] = {f.filename: f for f in files if f.filename} if files else {}
    processed_files_info = [] 
    validated_stages_to_save = []

    try:
        try:
            stages_data_list = json.loads(stages_json)
            logger.debug(f"[API_CONFIG_SALESFLOW_POST] JSON parseado para lista de dados: {json.dumps(stages_data_list, indent=2)[:500]}...") 
            validated_config = SalesFlowConfigRequest(stages=stages_data_list)
            validated_stages_to_save = validated_config.model_dump()['stages']
            logger.info(f"[API_CONFIG_SALESFLOW_POST] JSON do fluxo de vendas parseado e validado ({len(validated_stages_to_save)} etapas).")
            logger.debug(f"[API_CONFIG_SALESFLOW_POST] Estágios validados para salvar: {json.dumps(validated_stages_to_save, indent=2)[:500]}...") 
        except json.JSONDecodeError as json_err:
            logger.error(f"[API_CONFIG_SALESFLOW_POST] Erro ao decodificar JSON do fluxo: {json_err}. JSON recebido (início): {stages_json[:200]}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Invalid JSON format for sales flow stages: {json_err}")
        except ValidationError as val_err:
            logger.error(f"[API_CONFIG_SALESFLOW_POST] Erro de validação Pydantic para o fluxo: {val_err.errors()}. JSON recebido (início): {stages_json[:200]}", exc_info=True)
            detail_msg = f"Validation error in sales flow: {val_err.errors()}"
            raise HTTPException(status_code=400, detail=detail_msg)
        except Exception as e:
            logger.error(f"[API_CONFIG_SALESFLOW_POST] Erro inesperado na validação/parsing do JSON: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal error processing sales flow JSON: {e}")
        
        # --- INÍCIO DA CORREÇÃO DO BUG DE TRANSIÇÃO ---
        
        # Ordenar os estágios pelo número para garantir a lógica sequencial correta
        validated_stages_to_save.sort(key=lambda s: s.get('stage_number', float('inf')))

        # Adicionar a lógica de transição automática
        for i, stage in enumerate(validated_stages_to_save):
            # Se não for o último estágio, defina o próximo estágio
            if i < len(validated_stages_to_save) - 1:
                next_stage = validated_stages_to_save[i+1]
                stage['next_stage_after_sequence'] = next_stage.get('stage_number')
                logger.info(f"Adicionando transição para o Estágio {stage.get('stage_number')}: next_stage_after_sequence = {stage['next_stage_after_sequence']}")
            else:
                # Garante que o último estágio não tenha uma transição automática
                stage['next_stage_after_sequence'] = None
                logger.info(f"Estágio {stage.get('stage_number')} é o último, sem transição automática.")

        # --- FIM DA CORREÇÃO ---

        FLOW_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"[API_CONFIG_SALESFLOW_POST] Diretório de áudio '{FLOW_AUDIO_DIR}' verificado/criado.")

        for stage_idx, stage_data in enumerate(validated_stages_to_save):
            if stage_data.get('action_type') == 'sequence' and isinstance(stage_data.get('action_sequence'), list):
                for seq_index, seq_action in enumerate(stage_data['action_sequence']):
                    if isinstance(seq_action, dict) and seq_action.get("type") == "send_audio":
                        original_filename = seq_action.get("audio_file")
                        if not original_filename: 
                            logger.warning(f"[API_CONFIG_SALESFLOW_POST] Ação de áudio na sequência do Estágio {stage_data.get('stage_number')} sem nome de arquivo. Seq Index: {seq_index}. Ignorando salvamento de arquivo.")
                            continue

                        if original_filename in file_map:
                            audio_file_to_save = file_map[original_filename]
                            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                            file_extension = Path(original_filename).suffix
                            saved_filename = f"stage_{stage_data.get('stage_number')}_seq_action_{seq_index+1}_{timestamp}{file_extension}"
                            save_path = FLOW_AUDIO_DIR / saved_filename
                            try:
                                audio_file_to_save.file.seek(0) 
                                with save_path.open("wb") as buffer: shutil.copyfileobj(audio_file_to_save.file, buffer)
                                processed_files_info.append({"original_name": original_filename, "saved_name": saved_filename})
                                seq_action["audio_file"] = saved_filename 
                                logger.info(f"[API_CONFIG_SALESFLOW_POST] Áudio '{original_filename}' salvo com sucesso como '{saved_filename}'.")
                            except Exception as save_err:
                                logger.error(f"[API_CONFIG_SALESFLOW_POST] Erro ao salvar áudio '{original_filename}' para '{save_path}': {save_err}", exc_info=True)
                                raise HTTPException(status_code=500, detail=f"Error saving audio file '{original_filename}'. Check server logs for details.")
                            finally:
                                try: audio_file_to_save.file.close()
                                except Exception: pass
                        else:
                            logger.warning(f"[API_CONFIG_SALESFLOW_POST] Arquivo '{original_filename}' para ação de áudio na Etapa {stage_data.get('stage_number')} não encontrado nos arquivos enviados. Seq Index: {seq_index}. O arquivo pode já existir ou não foi enviado.")
        
        logger.info("[API_CONFIG_SALESFLOW_POST] Tentando salvar fluxo de vendas no DB...")
        success_db = await set_sales_flow_stages(validated_stages_to_save)
        if not success_db:
            logger.error("[API_CONFIG_SALESFLOW_POST] Falha ao salvar fluxo no DB. Nenhuma exceção lançada pelo DB, mas o retorno foi False.")
            raise HTTPException(status_code=500, detail="Failed to save sales flow to database. Check server logs.")

        logger.info("[API_CONFIG_SALESFLOW_POST] Fluxo de vendas salvo com sucesso. Retornando dados atualizados.")
        return SalesFlowConfigResponse(stages=validated_stages_to_save)

    except HTTPException as http_exc:
        for f in file_map.values():
            try: f.file.close()
            except Exception: pass
        raise http_exc
    except Exception as e:
        for f in file_map.values():
            try: f.file.close()
            except Exception: pass
        logger.error(f"[API_CONFIG_SALESFLOW_POST] Erro inesperado: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error setting sales flow: {e}")

@router.get("/config/sales-flow", response_model=SalesFlowConfigResponse, tags=["Configuration"])
async def get_sales_flow_endpoint():
    logger.info("[API_CONFIG_SALESFLOW_GET] Buscando fluxo de vendas...")
    try:
        stages = await get_sales_flow_stages()
        logger.debug(f"[API_CONFIG_SALESFLOW_GET] Fluxo de vendas retornado: {stages}")

        # Normalizar dados legados que não possuem os campos novos
        normalized_stages = []
        for stage in stages:
            if isinstance(stage, dict):
                # Adicionar campos obrigatórios faltantes para compatibilidade com dados antigos
                if 'action_type' not in stage:
                    stage['action_type'] = 'ask_llm'
                if 'trigger_description' not in stage:
                    stage['trigger_description'] = stage.get('objective', '')
                if 'action_sequence' not in stage:
                    stage['action_sequence'] = None
                if 'action_llm_prompt' not in stage:
                    stage['action_llm_prompt'] = None
                # Remover campos obsoletos que não existem no modelo novo
                stage.pop('automated_message', None)
                stage.pop('sequence_actions', None)
            normalized_stages.append(stage)

        return SalesFlowConfigResponse(stages=normalized_stages)
    except Exception as e:
        logger.error(f"[API_CONFIG_SALESFLOW_GET] Erro ao buscar fluxo de vendas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error fetching sales flow.")

# Modelo GenerateSalesFlowRequest movido para src/api/models.py

@router.post("/sales-flow/generate-template", response_model=GenericResponse, tags=["Sales Flow"])
async def generate_sales_flow_template_endpoint(request_data: GenerateSalesFlowRequest):
    logger.info("[API_SALESFLOW_GENERATE] Recebida requisição para gerar template de funil de vendas.")
    try:
        product_context_obj = await get_product_context(instance_id=settings.INSTANCE_ID)

        if not product_context_obj.context and not product_context_obj.db_data:
            raise HTTPException(status_code=400, detail="Contexto do produto não definido.")

        logger.info("[API_SALESFLOW_GENERATE] Solicitando geração de funil ao LLM...")
        
        generated_stages = await llm.generate_sales_flow_from_context(
            product_context_obj=product_context_obj,
            ai_funnel_tips=request_data.ai_funnel_tips
        )

        if not generated_stages:
            raise HTTPException(status_code=500, detail="Falha ao gerar template do funil de vendas.")

        logger.info(f"[API_SALESFLOW_GENERATE] {len(generated_stages)} estágios gerados.")

        # ✅ VALIDAÇÃO FINAL CRÍTICA NO BACKEND
        if generated_stages and len(generated_stages) > 0:
            first_stage = generated_stages[0]
            
            # ✅ VERIFICAÇÃO ABSOLUTA
            critical_errors = []
            
            if first_stage.get("stage_number") != 1:
                critical_errors.append(f"stage_number é {first_stage.get('stage_number')}, deveria ser 1")
            
            if first_stage.get("action_type") != "sequence":
                critical_errors.append(f"action_type é '{first_stage.get('action_type')}', deveria ser 'sequence'")
            
            if not isinstance(first_stage.get("action_sequence"), list):
                critical_errors.append("action_sequence não é uma lista")
            elif len(first_stage.get("action_sequence", [])) == 0:
                critical_errors.append("action_sequence está vazia")
            else:
                has_send_text = any(action.get("type") == "send_text" for action in first_stage.get("action_sequence", []))
                if not has_send_text:
                    critical_errors.append("action_sequence não tem nenhuma ação 'send_text'")
            
            if first_stage.get("action_llm_prompt") is not None:
                critical_errors.append(f"action_llm_prompt é '{first_stage.get('action_llm_prompt')}', deveria ser null")
            
            if critical_errors:
                error_details = "; ".join(critical_errors)
                logger.error(f"[API_SALESFLOW_GENERATE] ❌ VALIDAÇÃO FALHOU: {error_details}")
                logger.error(f"[API_SALESFLOW_GENERATE] Primeiro estágio problemático: {json.dumps(first_stage, indent=2)}")
                
                # ✅ APLICAR CORREÇÃO FORÇADA DE EMERGÊNCIA
                logger.warning("[API_SALESFLOW_GENERATE] Aplicando correção de emergência...")
                first_stage["stage_number"] = 1
                first_stage["action_type"] = "sequence"
                first_stage["action_llm_prompt"] = None
                
                if not isinstance(first_stage.get("action_sequence"), list):
                    first_stage["action_sequence"] = []
                
                has_send_text = any(action.get("type") == "send_text" for action in first_stage.get("action_sequence", []))
                if not has_send_text:
                    first_stage["action_sequence"].insert(0, {
                        "type": "send_text",
                        "delay_ms": 0,
                        "text": "Olá! 👋 Sou da nossa equipe. Como posso ajudar você hoje?"
                    })
                
                generated_stages[0] = first_stage
                logger.info("[API_SALESFLOW_GENERATE] ✅ Correção de emergência aplicada!")
            else:
                logger.info("[API_SALESFLOW_GENERATE] ✅ Primeiro estágio passou na validação crítica!")

        # ✅ VALIDAÇÃO PYDANTIC (vai falhar se ainda houver problema)
        try:
            validated_config = SalesFlowConfigRequest(stages=generated_stages)
            stages_to_save = validated_config.model_dump()['stages']
            logger.info("[API_SALESFLOW_GENERATE] ✅ Validação Pydantic bem-sucedida!")
        except ValidationError as val_err:
            logger.error(f"[API_SALESFLOW_GENERATE] ❌ ERRO Pydantic: {val_err.errors()}")
            # Se chegou aqui, algo está muito errado. Usar funil padrão.
            logger.warning("[API_SALESFLOW_GENERATE] Usando funil padrão devido a erro Pydantic...")
            default_stages = [
                {
                    "stage_number": 1,
                    "objective": "Apresentação inicial",
                    "trigger_description": "Novo contato",
                    "action_type": "sequence",
                    "action_sequence": [
                        {
                            "type": "send_text",
                            "delay_ms": 0,
                            "text": "Olá! 👋 Sou da nossa equipe. Como posso ajudar?"
                        }
                    ],
                    "action_llm_prompt": None
                }
            ]
            validated_config = SalesFlowConfigRequest(stages=default_stages)
            stages_to_save = validated_config.model_dump()['stages']

        success_db = await set_sales_flow_stages(stages_to_save)
        if not success_db:
            raise HTTPException(status_code=500, detail="Falha ao salvar no banco de dados.")

        logger.info("[API_SALESFLOW_GENERATE] ✅ Template gerado e salvo com sucesso!")
        return GenericResponse(success=True, message="Template de funil gerado e salvo com sucesso!")
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"[API_SALESFLOW_GENERATE] Erro geral: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno ao gerar template.")

# --- Agent IA Config (REMOVED - Configs now via .env) ---
# Os endpoints @router.get("/config/agent-ia", ...) e @router.post("/config/agent-ia", ...) foram removidos.

# --- Evolution Config ---
@router.get("/config/evolution", response_model=EvolutionConfigResponse, tags=["Configuration"])
async def get_evolution_config_endpoint():
    logger.info("[API_CONFIG_EVO_GET] Buscando config da Evolution API...")
    config = await get_evolution_config()
    # Retorna a chave completa para preencher o formulário de edição no frontend
    response_data = EvolutionConfigResponse(
        url=config.get("url"),
        api_key=config.get("api_key"),
        instance_name=config.get("instance_name")
    )
    logger.debug(f"[API_CONFIG_EVO_GET] Config Evolution retornada (chave não mascarada para UI).")
    return response_data

@router.post("/config/evolution", response_model=GenericResponse, tags=["Configuration"])
async def set_evolution_config_endpoint(config_data: EvolutionConfigRequest):
    logger.info(f"[API_CONFIG_EVO_POST] Atualizando config da Evolution API: URL='{config_data.url}', Instance='{config_data.instance_name}', KeyProvided={'Sim' if config_data.api_key else 'Não'}")
    
    # Lógica para preservar a chave se não for fornecida uma nova
    api_key_to_save = config_data.api_key
    if not api_key_to_save:
        logger.info("[API_CONFIG_EVO_POST] Nenhuma nova chave de API fornecida. Preservando a chave existente.")
        current_config = await get_evolution_config()
        api_key_to_save = current_config.get("api_key")

    success = await set_evolution_config(config_data.url, api_key_to_save, config_data.instance_name)
    if not success: 
        logger.error("[API_CONFIG_EVO_POST] Falha ao salvar config da Evolution API no DB.")
        raise HTTPException(status_code=500, detail="Failed to save Evolution API settings.")
    
    message = "Configurações da Evolution API salvas."
    container_public_url = settings.SITE_URL # Use settings.SITE_URL directly
    if container_public_url:
        webhook_target_url = f"{container_public_url.rstrip('/')}/api/webhook"
        logger.info(f"[API_CONFIG_EVO_POST] Tentando reconfigurar webhook para: {webhook_target_url}")
        webhook_set = await evolution.set_webhook_url(webhook_target_url)
        if webhook_set:
            message += " Webhook reconfigurado com sucesso."
            logger.info("[API_CONFIG_EVO_POST] Webhook reconfigurado.")
        else:
            message += " Falha ao reconfigurar webhook (verifique logs da Evolution API)."
            logger.warning("[API_CONFIG_EVO_POST] Falha ao reconfigurar webhook.")
    else:
        message += " (Webhook não reconfigurado automaticamente - URL pública do container não disponível)."
        logger.info("[API_CONFIG_EVO_POST] URL do container não disponível, webhook não reconfigurado.")
    
    return GenericResponse(success=True, message=message)

# --- Follow-up Config ---
@router.get("/config/follow-up", response_model=FollowUpConfigResponse, tags=["Configuration"])
async def get_follow_up_rules_endpoint():
    logger.info("[API_CONFIG_FOLLOWUP_GET] Buscando regras de follow-up...")
    try:
        rules = await prospect_manager.get_follow_up_rules()
        validated_rules = [FollowUpRule(**rule) for rule in rules]
        logger.debug(f"[API_CONFIG_FOLLOWUP_GET] {len(validated_rules)} regras de follow-up retornadas.")
        return FollowUpConfigResponse(rules=validated_rules)
    except ValidationError as e:
        logger.error(f"[API_CONFIG_FOLLOWUP_GET] Erro de validação Pydantic: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Invalid follow-up rule format in DB.")
    except Exception as e:
        logger.error(f"[API_CONFIG_FOLLOWUP_GET] Erro ao buscar regras: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error fetching follow-up rules.")

@router.post("/config/follow-up", response_model=FollowUpConfigResponse, tags=["Configuration"])
async def set_follow_up_rules_endpoint(config_data: FollowUpConfigRequest):
    logger.info(f"[API_CONFIG_FOLLOWUP_POST] Atualizando {len(config_data.rules)} regras de follow-up.")
    logger.debug(f"[API_CONFIG_FOLLOWUP_POST] Dados recebidos: {config_data.model_dump_json(indent=2)}")
    try:
        rules_to_save = [rule.model_dump() for rule in config_data.rules]
        success = await prospect_manager.set_follow_up_rules(rules_to_save)
        if not success: 
            logger.error("[API_CONFIG_FOLLOWUP_POST] Falha ao salvar regras no DB.")
            raise HTTPException(status_code=500, detail="Failed to save follow-up rules.")
        logger.info("[API_CONFIG_FOLLOWUP_POST] Regras de follow-up salvas com sucesso.")
        return FollowUpConfigResponse(rules=config_data.rules) 
    except Exception as e:
        logger.error(f"[API_CONFIG_FOLLOWUP_POST] Erro ao definir regras: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error setting follow-up rules.")

# --- Product Context Config ---
@router.get("/config/product-context", response_model=ProductContextResponse, tags=["Configuration"])
async def get_product_context_endpoint():
    logger.info("[API_CONFIG_PRODCONTEXT_GET] Buscando contexto do produto...")
    product_context_obj = await get_product_context(instance_id=settings.INSTANCE_ID)
    logger.debug(f"[API_CONFIG_PRODCONTEXT_GET] Contexto do produto carregado: {product_context_obj.model_dump_json(indent=2)}")
    return product_context_obj

@router.post("/config/product-context", response_model=GenericResponse, tags=["Configuration"])
async def set_product_context_endpoint(context_data: ProductContextRequest):
    logger.info(f"[API_CONFIG_PRODCONTEXT_POST] Atualizando contexto do produto.")
    
    # Descomentado e ajustado para popular context_data.db_data
    # Este campo não existe no ProductContextRequest, mas será adicionado dinamicamente
    # ao objeto context_data (que é uma instância de ProductContextRequest) antes de ser salvo.
    # O modelo ProductContextResponse (usado em get_product_context) já espera db_data.
    # A função set_product_context em config_crud.py salva o model_dump_json(), então
    # se db_data estiver presente em context_data, será salvo.
    
    retrieved_db_data = None # Para armazenar os dados do DB
    if context_data.db_url and context_data.sql_query:
        logger.info(f"[API_CONFIG_PRODCONTEXT_POST] db_url e sql_query fornecidos. Tentando buscar dados do DB externo.")
        db_data_from_connector = await execute_sql_query(context_data.db_url, context_data.sql_query)
        if db_data_from_connector is None: # execute_sql_query retorna None em caso de erro
            logger.error("[API_CONFIG_PRODCONTEXT_POST] Falha ao buscar dados do DB externo (execute_sql_query retornou None).")
            raise HTTPException(status_code=500, detail="Falha ao buscar dados do banco de dados externo. Verifique a URL, a query e os logs do servidor.")
        
        retrieved_db_data = db_data_from_connector # Armazena os dados recuperados
        logger.info(f"[API_CONFIG_PRODCONTEXT_POST] Dados do DB externo obtidos com sucesso. {len(retrieved_db_data)} registros.")
        
    if context_data.context:
        logger.info(f"[API_CONFIG_PRODCONTEXT_POST] Contexto de texto livre fornecido. Tamanho: {len(context_data.context)} chars.")
        logger.debug(f"[API_CONFIG_PRODCONTEXT_POST] Contexto (início): '{context_data.context[:200]}...'")
    
    # Validação ajustada: Pelo menos um dos contextos deve ser fornecido
    if not context_data.context and not (context_data.db_url and context_data.sql_query):
        logger.warning("[API_CONFIG_PRODCONTEXT_POST] Nenhuma informação de contexto (texto ou DB) fornecida.")
        raise HTTPException(status_code=400, detail="Forneça um Contexto de Texto ou uma URL de Banco de Dados com uma Query SQL.")

    # Prepara o payload final para salvar, incluindo db_data se recuperado
    payload_to_save = context_data.model_dump()
    if retrieved_db_data is not None:
        payload_to_save['db_data'] = retrieved_db_data
        logger.debug(f"[API_CONFIG_PRODCONTEXT_POST] Adicionando 'db_data' ao payload para salvar. Número de registros: {len(retrieved_db_data)}")
    else:
        # Se não houve tentativa de buscar dados do DB ou se falhou e não queremos salvar db_data antigo,
        # podemos garantir que db_data não esteja no payload ou seja None.
        # Se context_data já tem um db_data de uma carga anterior e não foi sobrescrito,
        # model_dump() o incluiria. Para garantir que apenas dados recém-buscados (ou nenhum) sejam salvos:
        payload_to_save['db_data'] = None # Garante que db_data seja None se não foi buscado agora
        if context_data.db_url and context_data.sql_query and retrieved_db_data is None:
             logger.warning("[API_CONFIG_PRODCONTEXT_POST] URL/Query do DB fornecidos, mas dados não foram recuperados (ou houve erro). 'db_data' será salvo como None.")


    success = await set_product_context(json.dumps(payload_to_save, cls=CustomJSONEncoder, ensure_ascii=False)) # Salva o dicionário como string JSON usando o encoder customizado
    if not success: 
        logger.error("[API_CONFIG_PRODCONTEXT_POST] Falha ao salvar contexto do produto no DB.")
        raise HTTPException(status_code=500, detail="Failed to save product context.")
    logger.info("[API_CONFIG_PRODCONTEXT_POST] Contexto do produto salvo com sucesso.")
    return GenericResponse(success=True, message="Contexto do produto salvo.")

# --- System Prompt Config ---
@router.get("/config/system-prompt", response_model=SystemPromptResponse, tags=["Configuration"])
async def get_system_prompt_endpoint():
    logger.info("[API_CONFIG_SYSPROMPT_GET] Buscando prompt do sistema...")
    prompt = await get_llm_system_prompt()
    logger.debug(f"[API_CONFIG_SYSPROMPT_GET] Prompt do sistema (início): '{prompt[:150]}...'")
    return SystemPromptResponse(system_prompt=prompt)

@router.post("/config/system-prompt", response_model=GenericResponse, tags=["Configuration"])
async def set_system_prompt_endpoint(prompt_data: SystemPromptRequest):
    logger.info(f"[API_CONFIG_SYSPROMPT_POST] Atualizando prompt do sistema. Tamanho: {len(prompt_data.system_prompt)} chars.")
    logger.debug(f"[API_CONFIG_SYSPROMPT_POST] Prompt (início): '{prompt_data.system_prompt[:200]}...'")
    success = await set_llm_system_prompt(prompt_data.system_prompt)
    if not success: 
        logger.error("[API_CONFIG_SYSPROMPT_POST] Falha ao salvar prompt do sistema no DB.")
        raise HTTPException(status_code=500, detail="Failed to save system prompt.")
    logger.info("[API_CONFIG_SYSPROMPT_POST] Prompt do sistema salvo com sucesso.")
    return GenericResponse(success=True, message="Prompt do sistema salvo.")

# --- LLM Model Config ---
@router.get("/config/llm", response_model=LLMConfigResponse, tags=["Configuration"])
async def get_llm_config_endpoint():
    logger.info("[API_CONFIG_LLM_GET] Buscando configuração do modelo de LLM...")
    model = await get_config_value("llm_model_preference")
    temperature = await get_config_value("llm_temperature")
    response_data = LLMConfigResponse(
        llm_model_preference=model or settings.LLM_MODEL_PREFERENCE,
        llm_temperature=float(temperature or settings.LLM_TEMPERATURE)
    )
    logger.debug(f"[API_CONFIG_LLM_GET] Config LLM retornada: {response_data.model_dump_json(indent=2)}")
    return response_data

@router.post("/config/llm", response_model=GenericResponse, tags=["Configuration"])
async def set_llm_config_endpoint(config_data: LLMConfigRequest):
    logger.info(f"[API_CONFIG_LLM_POST] Atualizando config do LLM: {config_data.model_dump_json(indent=2)}")
    s1 = await set_config_value("llm_model_preference", config_data.llm_model_preference)
    s2 = await set_config_value("llm_temperature", str(config_data.llm_temperature))
    if not (s1 and s2):
        logger.error("[API_CONFIG_LLM_POST] Falha ao salvar uma ou mais configs do LLM.")
        raise HTTPException(status_code=500, detail="Falha ao salvar configurações do LLM.")
    logger.info("[API_CONFIG_LLM_POST] Config do LLM salva com sucesso.")
    return GenericResponse(success=True, message="Configurações do LLM salvas com sucesso.")

# --- First Message Config ---
@router.get("/config/first-message", response_model=FirstMessageConfigResponse, tags=["Configuration"])
async def get_first_message_config_endpoint():
    logger.info("[API_CONFIG_FIRST_MESSAGE_GET] Buscando configuração de mensagens iniciais...")
    try:
        config = await prospect_manager.get_first_message_config()
        logger.debug(f"[API_CONFIG_FIRST_MESSAGE_GET] Configuração de mensagens iniciais retornada: {config.model_dump_json(indent=2)}")
        return FirstMessageConfigResponse(**config.model_dump())
    except Exception as e:
        logger.error(f"[API_CONFIG_FIRST_MESSAGE_GET] Erro ao buscar configuração de mensagens iniciais: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar configuração de mensagens iniciais.")

@router.post("/config/first-message", response_model=GenericResponse, tags=["Configuration"])
async def set_first_message_config_endpoint(config_data: FirstMessageConfig):
    logger.info(f"[API_CONFIG_FIRST_MESSAGE_POST] Atualizando configuração de mensagens iniciais: {config_data.model_dump_json(indent=2)}")
    try:
        success = await prospect_manager.set_first_message_config(config_data)
        if not success:
            logger.error("[API_CONFIG_FIRST_MESSAGE_POST] Falha ao salvar configuração de mensagens iniciais no DB.")
            raise HTTPException(status_code=500, detail="Falha ao salvar configuração de mensagens iniciais.")
        logger.info("[API_CONFIG_FIRST_MESSAGE_POST] Configuração de mensagens iniciais salva com sucesso.")
        return GenericResponse(success=True, message="Configuração de mensagens iniciais salva com sucesso!")
    except Exception as e:
        logger.error(f"[API_CONFIG_FIRST_MESSAGE_POST] Erro ao salvar configuração de mensagens iniciais: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao salvar configuração de mensagens iniciais.")

# --- Backup and Restore Endpoints ---
@router.get("/config/export", tags=["Configuration"])
async def export_all_configs():
    """Exports all application configurations to a JSON file."""
    logger.info("[API_CONFIG_EXPORT] Iniciando exportação de todas as configurações.")
    try:
        all_configs = await get_all_configs_as_dict()
        
        # Adicionar metadados ao backup
        export_data = {
            "metadata": {
                "export_date": datetime.utcnow().isoformat() + "Z",
                "instance_id": settings.INSTANCE_ID,
                "version": "1.0"
            },
            "configurations": all_configs
        }
        
        # Definir nome do arquivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"innova_fluxo_backup_{settings.INSTANCE_ID}_{timestamp}.json"
        
        headers = {
            "Content-Disposition": f"attachment; filename=\"{filename}\""
        }
        
        logger.info(f"[API_CONFIG_EXPORT] Exportação concluída. {len(all_configs)} configurações exportadas no arquivo {filename}.")
        return JSONResponse(content=export_data, headers=headers)

    except Exception as e:
        logger.error(f"[API_CONFIG_EXPORT] Erro ao exportar configurações: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno ao gerar o arquivo de backup.")

@router.post("/config/import", response_model=GenericResponse, tags=["Configuration"])
async def import_all_configs(file: UploadFile = File(...)):
    """Imports application configurations from a JSON backup file."""
    logger.info(f"[API_CONFIG_IMPORT] Recebida requisição para importar configurações do arquivo: {file.filename}")
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="Formato de arquivo inválido. Apenas arquivos .json são permitidos.")

    try:
        contents = await file.read()
        backup_data = json.loads(contents)

        # Validação da estrutura do backup
        if "metadata" not in backup_data or "configurations" not in backup_data:
            raise HTTPException(status_code=400, detail="Arquivo de backup inválido: chaves 'metadata' ou 'configurations' ausentes.")
        
        configurations = backup_data["configurations"]
        if not isinstance(configurations, dict):
            raise HTTPException(status_code=400, detail="Arquivo de backup inválido: 'configurations' deve ser um dicionário.")

        logger.info(f"[API_CONFIG_IMPORT] Arquivo de backup validado. {len(configurations)} configurações encontradas. Iniciando importação...")
        
        success_count = 0
        fail_count = 0
        for key, value in configurations.items():
            # A função set_config_value já lida com a serialização de dict/list para JSON string
            success = await set_config_value(key, value)
            if success:
                success_count += 1
            else:
                fail_count += 1
                logger.error(f"[API_CONFIG_IMPORT] Falha ao importar a chave: '{key}'")

        message = f"Importação concluída. {success_count} configurações salvas com sucesso."
        if fail_count > 0:
            message += f" {fail_count} falharam."
            logger.error(f"[API_CONFIG_IMPORT] {fail_count} configurações falharam ao ser importadas.")
            # Mesmo com falhas, retornamos 200 OK com a mensagem de resumo
        
        logger.info(f"[API_CONFIG_IMPORT] {message}")
        return GenericResponse(success=True, message=message)

    except json.JSONDecodeError:
        logger.error("[API_CONFIG_IMPORT] Erro ao decodificar o arquivo JSON.", exc_info=True)
        raise HTTPException(status_code=400, detail="O arquivo fornecido não é um JSON válido.")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"[API_CONFIG_IMPORT] Erro inesperado durante a importação: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno ao processar o arquivo de backup: {e}")


# --- Insufficient Context Notification Config ---
@router.get("/config/insufficient-context-notification", response_model=InsufficientContextNotificationResponse, tags=["Configuration"])
async def get_insufficient_context_notification_config_endpoint():
    """
    Obtém a configuração de notificação para quando o LLM não tem contexto suficiente.
    """
    logger.info("[API_CONFIG_INSUFFICIENT_CONTEXT_GET] Buscando configuração de notificação de contexto insuficiente...")
    try:
        from src.core.db_operations.config_crud import get_insufficient_context_notification_config
        config = await get_insufficient_context_notification_config(instance_id=settings.INSTANCE_ID)
        logger.debug(f"[API_CONFIG_INSUFFICIENT_CONTEXT_GET] Configuração retornada: {config}")
        return InsufficientContextNotificationResponse(**config)
    except Exception as e:
        logger.error(f"[API_CONFIG_INSUFFICIENT_CONTEXT_GET] Erro ao buscar configuração: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar configuração de notificação de contexto insuficiente.")


@router.post("/config/insufficient-context-notification", response_model=GenericResponse, tags=["Configuration"])
async def set_insufficient_context_notification_config_endpoint(config_data: InsufficientContextNotificationRequest):
    """
    Salva a configuração de notificação para quando o LLM não tem contexto suficiente.
    """
    logger.info(f"[API_CONFIG_INSUFFICIENT_CONTEXT_POST] Atualizando configuração de notificação de contexto insuficiente: {config_data.model_dump_json(indent=2)}")
    try:
        from src.core.db_operations.config_crud import set_insufficient_context_notification_config

        # Validar se o número de notificação é obrigatório quando habilitado
        if config_data.enabled and not config_data.notification_whatsapp_number:
            raise HTTPException(
                status_code=400,
                detail="Número de WhatsApp para notificação é obrigatório quando a funcionalidade está habilitada."
            )

        success = await set_insufficient_context_notification_config(config_data.model_dump())
        if not success:
            logger.error("[API_CONFIG_INSUFFICIENT_CONTEXT_POST] Falha ao salvar configuração no DB.")
            raise HTTPException(status_code=500, detail="Falha ao salvar configuração de notificação.")

        logger.info("[API_CONFIG_INSUFFICIENT_CONTEXT_POST] Configuração salva com sucesso.")
        return GenericResponse(success=True, message="Configuração de notificação de contexto insuficiente salva com sucesso!")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"[API_CONFIG_INSUFFICIENT_CONTEXT_POST] Erro ao salvar configuração: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao salvar configuração de notificação de contexto insuficiente.")


# --- Stage Change Notification Config ---
@router.get("/config/stage-change-notification", response_model=StageChangeNotificationResponse, tags=["Configuration"])
async def get_stage_change_notification_config_endpoint():
    """
    Obtém a configuração de notificação para quando um prospect muda de etapa no funil.
    """
    logger.info("[API_CONFIG_STAGE_CHANGE_GET] Buscando configuração de notificação de mudança de etapa...")
    try:
        from src.core.db_operations.config_crud import get_stage_change_notification_config
        config = await get_stage_change_notification_config(instance_id=settings.INSTANCE_ID)
        logger.debug(f"[API_CONFIG_STAGE_CHANGE_GET] Configuração retornada: {config}")
        return StageChangeNotificationResponse(**config)
    except Exception as e:
        logger.error(f"[API_CONFIG_STAGE_CHANGE_GET] Erro ao buscar configuração: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar configuração de notificação de mudança de etapa.")


@router.post("/config/stage-change-notification", response_model=GenericResponse, tags=["Configuration"])
async def set_stage_change_notification_config_endpoint(config_data: StageChangeNotificationRequest):
    """
    Salva a configuração de notificação para quando um prospect muda de etapa no funil.
    """
    logger.info(f"[API_CONFIG_STAGE_CHANGE_POST] Atualizando configuração de notificação de mudança de etapa: {config_data.model_dump_json(indent=2)}")
    try:
        from src.core.db_operations.config_crud import set_stage_change_notification_config

        # Validar se o número de notificação é obrigatório quando habilitado
        if config_data.enabled and not config_data.notification_whatsapp_number:
            raise HTTPException(
                status_code=400,
                detail="Número de WhatsApp para notificação é obrigatório quando a funcionalidade está habilitada."
            )

        success = await set_stage_change_notification_config(config_data.model_dump())
        if not success:
            logger.error("[API_CONFIG_STAGE_CHANGE_POST] Falha ao salvar configuração no DB.")
            raise HTTPException(status_code=500, detail="Falha ao salvar configuração de notificação.")

        logger.info("[API_CONFIG_STAGE_CHANGE_POST] Configuração salva com sucesso.")
        return GenericResponse(success=True, message="Configuração de notificação de mudança de etapa salva com sucesso!")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"[API_CONFIG_STAGE_CHANGE_POST] Erro ao salvar configuração: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao salvar configuração de notificação de mudança de etapa.")


# --- Flow Audio Files ---
@router.get("/config/flow-audios", tags=["Configuration"])
async def list_flow_audio_files():
    """
    Lista todos os arquivos de áudio disponíveis no diretório de áudios de fluxo.
    Retorna nome do arquivo e tamanho.
    """
    logger.info("[API_CONFIG_FLOW_AUDIOS] Listando arquivos de áudio disponíveis...")
    try:
        FLOW_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

        audio_extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.opus'}
        audio_files = []

        for file_path in FLOW_AUDIO_DIR.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in audio_extensions:
                audio_files.append({
                    "filename": file_path.name,
                    "size_bytes": file_path.stat().st_size,
                    "size_display": f"{file_path.stat().st_size / 1024:.1f} KB"
                })

        audio_files.sort(key=lambda x: x["filename"].lower())

        logger.info(f"[API_CONFIG_FLOW_AUDIOS] {len(audio_files)} arquivos de áudio encontrados.")
        return {"audios": audio_files, "total": len(audio_files)}
    except Exception as e:
        logger.error(f"[API_CONFIG_FLOW_AUDIOS] Erro ao listar arquivos de áudio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao listar arquivos de áudio.")


# =============================================================================
# SALES FUNNELS ENDPOINTS (Multiple Funnels Support)
# =============================================================================

@router.get("/config/funnels", response_model=FunnelListResponse, tags=["Sales Funnels"])
async def list_funnels(include_inactive: bool = Query(False, description="Incluir funis inativos")):
    """
    Lista todos os funis de vendas da instância.
    """
    logger.info(f"[API_FUNNELS_LIST] Listando funis (include_inactive={include_inactive})")
    try:
        from src.core.db_operations.funnel_crud import get_all_funnels

        funnels = await get_all_funnels(instance_id=settings.INSTANCE_ID, include_inactive=include_inactive)

        # Convert to summary format
        funnel_summaries = [
            SalesFunnelSummary(
                funnel_id=f["funnel_id"],
                name=f["name"],
                description=f.get("description"),
                stages_count=f.get("stages_count", len(f.get("stages", []))),
                is_default=f.get("is_default", False),
                is_active=f.get("is_active", True),
                created_at=f.get("created_at"),
                updated_at=f.get("updated_at")
            )
            for f in funnels
        ]

        logger.info(f"[API_FUNNELS_LIST] Retornando {len(funnel_summaries)} funis")
        return FunnelListResponse(funnels=funnel_summaries, total=len(funnel_summaries))

    except Exception as e:
        logger.error(f"[API_FUNNELS_LIST] Erro ao listar funis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao listar funis de vendas.")


@router.get("/config/funnels/{funnel_id}", response_model=SalesFunnel, tags=["Sales Funnels"])
async def get_funnel(funnel_id: str):
    """
    Retorna um funil específico pelo ID.
    """
    logger.info(f"[API_FUNNELS_GET] Buscando funil '{funnel_id}'")
    try:
        from src.core.db_operations.funnel_crud import get_funnel_by_id

        funnel = await get_funnel_by_id(instance_id=settings.INSTANCE_ID, funnel_id=funnel_id)

        if not funnel:
            logger.warning(f"[API_FUNNELS_GET] Funil '{funnel_id}' não encontrado")
            raise HTTPException(status_code=404, detail=f"Funil '{funnel_id}' não encontrado.")

        logger.info(f"[API_FUNNELS_GET] Funil '{funnel_id}' encontrado com {len(funnel.get('stages', []))} estágios")
        return SalesFunnel(**funnel)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_FUNNELS_GET] Erro ao buscar funil '{funnel_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar funil de vendas.")


@router.post("/config/funnels", response_model=FunnelResponse, tags=["Sales Funnels"])
async def create_funnel(request: CreateFunnelRequest):
    """
    Cria um novo funil de vendas.
    """
    logger.info(f"[API_FUNNELS_CREATE] Criando funil '{request.name}'")
    try:
        from src.core.db_operations.funnel_crud import create_funnel as create_funnel_db, get_funnel_by_id

        # Determine stages
        stages = []

        if request.stages:
            # Use provided stages
            stages = [stage.model_dump() for stage in request.stages]
        elif request.copy_from_funnel_id:
            # Copy from existing funnel
            source_funnel = await get_funnel_by_id(settings.INSTANCE_ID, request.copy_from_funnel_id)
            if not source_funnel:
                raise HTTPException(
                    status_code=400,
                    detail=f"Funil de origem '{request.copy_from_funnel_id}' não encontrado."
                )
            stages = source_funnel.get("stages", [])
            logger.info(f"[API_FUNNELS_CREATE] Copiando {len(stages)} estágios do funil '{request.copy_from_funnel_id}'")
        else:
            # Create with default stage
            stages = [
                {
                    "stage_number": 1,
                    "objective": "Apresentação inicial",
                    "trigger_description": "Novo contato",
                    "action_type": "sequence",
                    "action_sequence": [
                        {
                            "type": "send_text",
                            "delay_ms": 0,
                            "text": "Olá! Como posso ajudar?"
                        }
                    ],
                    "action_llm_prompt": None
                }
            ]

        funnel = await create_funnel_db(
            instance_id=settings.INSTANCE_ID,
            name=request.name,
            description=request.description,
            stages=stages,
            set_as_default=request.set_as_default
        )

        if not funnel:
            raise HTTPException(status_code=500, detail="Falha ao criar funil de vendas.")

        logger.info(f"[API_FUNNELS_CREATE] Funil '{funnel['funnel_id']}' criado com sucesso")
        return FunnelResponse(
            success=True,
            message=f"Funil '{request.name}' criado com sucesso!",
            funnel=SalesFunnel(**funnel)
        )

    except HTTPException:
        raise
    except ValidationError as e:
        logger.error(f"[API_FUNNELS_CREATE] Erro de validação: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Erro de validação: {e.errors()}")
    except Exception as e:
        logger.error(f"[API_FUNNELS_CREATE] Erro ao criar funil: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao criar funil de vendas.")


@router.put("/config/funnels/{funnel_id}", response_model=FunnelResponse, tags=["Sales Funnels"])
async def update_funnel_endpoint(funnel_id: str, request: UpdateFunnelRequest):
    """
    Atualiza um funil existente.
    """
    logger.info(f"[API_FUNNELS_UPDATE] Atualizando funil '{funnel_id}'")
    try:
        from src.core.db_operations.funnel_crud import update_funnel, get_funnel_by_id

        # Check if funnel exists
        existing_funnel = await get_funnel_by_id(settings.INSTANCE_ID, funnel_id)
        if not existing_funnel:
            raise HTTPException(status_code=404, detail=f"Funil '{funnel_id}' não encontrado.")

        # Prepare stages if provided
        stages = None
        if request.stages:
            stages = [stage.model_dump() for stage in request.stages]

        funnel = await update_funnel(
            instance_id=settings.INSTANCE_ID,
            funnel_id=funnel_id,
            name=request.name,
            description=request.description,
            stages=stages,
            is_active=request.is_active
        )

        if not funnel:
            raise HTTPException(status_code=500, detail="Falha ao atualizar funil de vendas.")

        logger.info(f"[API_FUNNELS_UPDATE] Funil '{funnel_id}' atualizado com sucesso")
        return FunnelResponse(
            success=True,
            message=f"Funil '{funnel['name']}' atualizado com sucesso!",
            funnel=SalesFunnel(**funnel)
        )

    except HTTPException:
        raise
    except ValidationError as e:
        logger.error(f"[API_FUNNELS_UPDATE] Erro de validação: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Erro de validação: {e.errors()}")
    except Exception as e:
        logger.error(f"[API_FUNNELS_UPDATE] Erro ao atualizar funil: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao atualizar funil de vendas.")


@router.delete("/config/funnels/{funnel_id}", response_model=GenericResponse, tags=["Sales Funnels"])
async def delete_funnel_endpoint(funnel_id: str):
    """
    Remove um funil de vendas.

    Nota: Não é possível remover o funil padrão ou funis com prospects associados.
    """
    logger.info(f"[API_FUNNELS_DELETE] Removendo funil '{funnel_id}'")
    try:
        from src.core.db_operations.funnel_crud import delete_funnel, get_funnel_by_id, get_prospects_count_by_funnel

        # Check if funnel exists
        existing_funnel = await get_funnel_by_id(settings.INSTANCE_ID, funnel_id)
        if not existing_funnel:
            raise HTTPException(status_code=404, detail=f"Funil '{funnel_id}' não encontrado.")

        # Check if it's the default funnel
        if existing_funnel.get("is_default"):
            raise HTTPException(
                status_code=400,
                detail="Não é possível remover o funil padrão. Defina outro funil como padrão primeiro."
            )

        # Check for associated prospects
        prospects_count = await get_prospects_count_by_funnel(settings.INSTANCE_ID, funnel_id)
        if prospects_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Não é possível remover funil com {prospects_count} prospects associados. Mova os prospects para outro funil primeiro."
            )

        success = await delete_funnel(settings.INSTANCE_ID, funnel_id)

        if not success:
            raise HTTPException(status_code=500, detail="Falha ao remover funil de vendas.")

        logger.info(f"[API_FUNNELS_DELETE] Funil '{funnel_id}' removido com sucesso")
        return GenericResponse(success=True, message=f"Funil removido com sucesso!")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_FUNNELS_DELETE] Erro ao remover funil: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao remover funil de vendas.")


@router.post("/config/funnels/{funnel_id}/set-default", response_model=GenericResponse, tags=["Sales Funnels"])
async def set_default_funnel_endpoint(funnel_id: str):
    """
    Define um funil como padrão para a instância.
    """
    logger.info(f"[API_FUNNELS_SET_DEFAULT] Definindo funil '{funnel_id}' como padrão")
    try:
        from src.core.db_operations.funnel_crud import set_default_funnel, get_funnel_by_id

        # Check if funnel exists
        existing_funnel = await get_funnel_by_id(settings.INSTANCE_ID, funnel_id)
        if not existing_funnel:
            raise HTTPException(status_code=404, detail=f"Funil '{funnel_id}' não encontrado.")

        if not existing_funnel.get("is_active"):
            raise HTTPException(
                status_code=400,
                detail="Não é possível definir um funil inativo como padrão."
            )

        success = await set_default_funnel(settings.INSTANCE_ID, funnel_id)

        if not success:
            raise HTTPException(status_code=500, detail="Falha ao definir funil como padrão.")

        logger.info(f"[API_FUNNELS_SET_DEFAULT] Funil '{funnel_id}' definido como padrão")
        return GenericResponse(
            success=True,
            message=f"Funil '{existing_funnel['name']}' definido como padrão com sucesso!"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_FUNNELS_SET_DEFAULT] Erro ao definir funil como padrão: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao definir funil como padrão.")


@router.get("/config/funnels/default/current", response_model=SalesFunnel, tags=["Sales Funnels"])
async def get_default_funnel_endpoint():
    """
    Retorna o funil padrão da instância.
    """
    logger.info("[API_FUNNELS_GET_DEFAULT] Buscando funil padrão")
    try:
        from src.core.db_operations.funnel_crud import get_default_funnel

        funnel = await get_default_funnel(instance_id=settings.INSTANCE_ID)

        if not funnel:
            logger.warning("[API_FUNNELS_GET_DEFAULT] Nenhum funil padrão encontrado")
            raise HTTPException(status_code=404, detail="Nenhum funil padrão encontrado.")

        logger.info(f"[API_FUNNELS_GET_DEFAULT] Funil padrão: '{funnel['funnel_id']}'")
        return SalesFunnel(**funnel)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_FUNNELS_GET_DEFAULT] Erro ao buscar funil padrão: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao buscar funil padrão.")


@router.post("/config/funnels/migrate-legacy", response_model=GenericResponse, tags=["Sales Funnels"])
async def migrate_legacy_funnel_endpoint():
    """
    Migra o funil legado (armazenado em application_config) para a nova tabela sales_funnels.

    Só executa a migração se não existirem funis na nova tabela.
    """
    logger.info("[API_FUNNELS_MIGRATE] Iniciando migração de funil legado")
    try:
        from src.core.db_operations.funnel_crud import migrate_legacy_funnel

        funnel_id = await migrate_legacy_funnel(instance_id=settings.INSTANCE_ID)

        if funnel_id:
            logger.info(f"[API_FUNNELS_MIGRATE] Funil legado migrado como '{funnel_id}'")
            return GenericResponse(
                success=True,
                message=f"Funil legado migrado com sucesso! ID: {funnel_id}"
            )
        else:
            logger.info("[API_FUNNELS_MIGRATE] Nenhuma migração necessária")
            return GenericResponse(
                success=True,
                message="Nenhuma migração necessária. Já existem funis na nova tabela ou não há funil legado."
            )

    except Exception as e:
        logger.error(f"[API_FUNNELS_MIGRATE] Erro na migração: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao migrar funil legado.")