# -*- coding: utf-8 -*-
"""
Automation Engine - Motor de Fluxos de Automação baseados em Tags

Este módulo processa eventos e executa fluxos de automação baseados em:
- Adição/remoção de tags
- Inatividade do prospect
- Mudança de estágio
- Eventos customizados

Fluxos são configuráveis via frontend e armazenados no banco de dados.
"""
import logging
import asyncio
import json
import re
from typing import Dict, Any, Optional, List, Literal
from datetime import datetime, timedelta
import pytz

from src.core.config import settings

# Timezone padrão: America/Sao_Paulo (GMT-3)
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

def _now() -> datetime:
    """Retorna datetime atual no timezone de São Paulo (GMT-3)."""
    return datetime.now(SAO_PAULO_TZ)
from src.core.db_operations import tags_crud

logger = logging.getLogger(__name__)

# ==================== TRIGGER TYPES ====================

TRIGGER_TYPES = {
    'tag_added': 'Quando uma tag é adicionada',
    'tag_removed': 'Quando uma tag é removida',
    'inactivity': 'Quando o prospect fica inativo por X tempo',
    'stage_change': 'Quando o prospect muda de estágio',
    'message_received': 'Quando recebe mensagem do prospect',
    'keyword_detected': 'Quando detecta palavra-chave na mensagem',
    'ai_semantic': 'Quando a IA detecta uma intenção/sentimento na conversa',
    'schedule': 'Em horário programado'
}

# ==================== AI SEMANTIC DETECTION TYPES ====================

AI_SEMANTIC_INTENTS = {
    'interesse': 'Prospect demonstra interesse no produto/serviço',
    'objecao': 'Prospect apresenta objeção ou resistência',
    'urgencia': 'Prospect demonstra urgência ou necessidade imediata',
    'duvida': 'Prospect tem dúvidas que precisam ser esclarecidas',
    'preco': 'Prospect menciona preço, valor ou orçamento',
    'agendamento': 'Prospect quer agendar reunião ou demonstração',
    'cancelamento': 'Prospect menciona cancelar ou desistir',
    'satisfacao': 'Prospect demonstra satisfação ou feedback positivo',
    'insatisfacao': 'Prospect demonstra insatisfação ou reclamação',
    'comparacao': 'Prospect compara com concorrentes',
    'decisor': 'Prospect menciona precisar consultar decisor',
    'trial': 'Prospect quer testar ou fazer trial',
    'suporte': 'Prospect precisa de suporte técnico',
    'indicacao': 'Prospect quer indicar ou foi indicado',
    'custom': 'Intenção customizada (configurável)'
}

# ==================== ACTION TYPES ====================

ACTION_TYPES = {
    'send_message': 'Enviar mensagem de texto',
    'send_audio': 'Enviar áudio',
    'add_tag': 'Adicionar tag',
    'remove_tag': 'Remover tag',
    'change_stage': 'Mudar estágio',
    'change_funnel': 'Mudar de funil',
    'pause_llm': 'Pausar respostas do LLM',
    'resume_llm': 'Retomar respostas do LLM',
    'notify_team': 'Notificar equipe',
    'assign_professional': 'Atribuir profissional',
    'schedule_followup': 'Agendar follow-up',
    'mark_status': 'Marcar status do prospect'
}


# ==================== EVENT PROCESSORS ====================

async def process_tag_event(jid: str, tag: str, event_type: str, instance_id: str):
    """
    Processa evento de tag (adição ou remoção) e executa fluxos correspondentes.

    Args:
        jid: Identificador do prospect
        tag: Nome da tag envolvida
        event_type: 'tag_added' ou 'tag_removed'
        instance_id: ID da instância
    """
    start_time = _now()
    request_id = f"proc_tag_{_now().timestamp()}"

    logger.info(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] Iniciando processamento - JID: '{jid}', Tag: '{tag}', Evento: '{event_type}'")

    try:
        # Buscar fluxos de automação configurados
        flows = await tags_crud.get_automation_flows(instance_id)

        if not flows:
            logger.info(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] Nenhum fluxo de automação configurado")
            return

        # Filtrar fluxos que correspondem ao evento
        matching_flows = []
        logger.info(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] Analisando {len(flows)} fluxos de automação...")

        for flow in flows:
            flow_id = flow.get('id', 'N/A')
            flow_name = flow.get('name', 'Sem nome')
            flow_enabled = flow.get('enabled', True)

            if not flow_enabled:
                logger.debug(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] Fluxo '{flow_name}' (ID: {flow_id}) está DESABILITADO, ignorando")
                continue

            trigger = flow.get('trigger', {})
            trigger_type = trigger.get('type')
            trigger_tag = trigger.get('tag')

            logger.info(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] "
                       f"Fluxo '{flow_name}' (ID: {flow_id}): trigger_type='{trigger_type}', trigger_tag='{trigger_tag}' | "
                       f"Evento recebido: type='{event_type}', tag='{tag}'")

            if trigger_type == event_type:
                # Verificar se a tag corresponde
                if trigger_tag == tag or trigger_tag == '*':  # '*' = qualquer tag
                    matching_flows.append(flow)
                    logger.info(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] "
                               f"✅ MATCH! Fluxo '{flow_name}' será executado")
                else:
                    logger.info(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] "
                               f"❌ Tag não corresponde: esperado='{trigger_tag}', recebido='{tag}'")
            else:
                logger.debug(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] "
                           f"Tipo de trigger não corresponde: esperado='{trigger_type}', recebido='{event_type}'")

        logger.info(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] {len(matching_flows)} fluxos correspondem ao evento")

        # Executar fluxos correspondentes
        for flow in matching_flows:
            await _execute_automation_flow(jid, flow, event_type, tag, instance_id)

        duration = (_now() - start_time).total_seconds() * 1000
        logger.info(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] Processamento concluído em {duration:.2f}ms")

    except Exception as e:
        duration = (_now() - start_time).total_seconds() * 1000
        logger.error(f"[{_now().isoformat()}] [PROCESS_TAG_EVENT] [{request_id}] ERRO após {duration:.2f}ms: {e}", exc_info=True)


async def process_inactivity_event(jid: str, inactivity_minutes: int, instance_id: str):
    """
    Processa evento de inatividade e executa fluxos correspondentes.

    Args:
        jid: Identificador do prospect
        inactivity_minutes: Minutos de inatividade
        instance_id: ID da instância
    """
    start_time = _now()
    request_id = f"proc_inact_{_now().timestamp()}"

    logger.info(f"[{_now().isoformat()}] [PROCESS_INACTIVITY_EVENT] [{request_id}] JID: '{jid}', Inatividade: {inactivity_minutes}min")

    try:
        flows = await tags_crud.get_automation_flows(instance_id)

        if not flows:
            return

        matching_flows = []
        for flow in flows:
            if not flow.get('enabled', True):
                continue

            trigger = flow.get('trigger', {})
            if trigger.get('type') == 'inactivity':
                trigger_minutes = trigger.get('minutes', 0)
                if inactivity_minutes >= trigger_minutes:
                    matching_flows.append(flow)

        for flow in matching_flows:
            await _execute_automation_flow(jid, flow, 'inactivity', str(inactivity_minutes), instance_id)

        duration = (_now() - start_time).total_seconds() * 1000
        logger.info(f"[{_now().isoformat()}] [PROCESS_INACTIVITY_EVENT] [{request_id}] Concluído em {duration:.2f}ms")

    except Exception as e:
        logger.error(f"[{_now().isoformat()}] [PROCESS_INACTIVITY_EVENT] [{request_id}] ERRO: {e}", exc_info=True)


async def process_stage_change_event(jid: str, old_stage: int, new_stage: int, instance_id: str):
    """
    Processa evento de mudança de estágio e executa fluxos correspondentes.

    Args:
        jid: Identificador do prospect
        old_stage: Estágio anterior
        new_stage: Novo estágio
        instance_id: ID da instância
    """
    start_time = _now()
    request_id = f"proc_stage_{_now().timestamp()}"

    logger.info(f"[{_now().isoformat()}] [PROCESS_STAGE_CHANGE_EVENT] [{request_id}] JID: '{jid}', {old_stage} -> {new_stage}")

    try:
        flows = await tags_crud.get_automation_flows(instance_id)

        if not flows:
            return

        matching_flows = []
        for flow in flows:
            if not flow.get('enabled', True):
                continue

            trigger = flow.get('trigger', {})
            if trigger.get('type') == 'stage_change':
                trigger_from = trigger.get('from_stage')
                trigger_to = trigger.get('to_stage')

                # Verificar se corresponde (None = qualquer estágio)
                from_match = trigger_from is None or trigger_from == old_stage or trigger_from == '*'
                to_match = trigger_to is None or trigger_to == new_stage or trigger_to == '*'

                if from_match and to_match:
                    matching_flows.append(flow)

        for flow in matching_flows:
            await _execute_automation_flow(jid, flow, 'stage_change', f"{old_stage}->{new_stage}", instance_id)

        duration = (_now() - start_time).total_seconds() * 1000
        logger.info(f"[{_now().isoformat()}] [PROCESS_STAGE_CHANGE_EVENT] [{request_id}] Concluído em {duration:.2f}ms")

    except Exception as e:
        logger.error(f"[{_now().isoformat()}] [PROCESS_STAGE_CHANGE_EVENT] [{request_id}] ERRO: {e}", exc_info=True)


async def process_ai_semantic_event(jid: str, user_message: str, llm_response: str, instance_id: str):
    """
    Processa evento de detecção semântica pela IA usando instruções customizadas.

    Usa a LLM para analisar semanticamente se a mensagem do usuário corresponde
    às instruções configuradas no frontend para cada tag.

    Args:
        jid: Identificador do prospect
        user_message: Mensagem enviada pelo usuário
        llm_response: Resposta gerada pelo LLM (usada para contexto)
        instance_id: ID da instância
    """
    start_time = _now()
    request_id = f"proc_ai_semantic_{_now().timestamp()}"

    logger.info(f"[{_now().isoformat()}] [PROCESS_AI_SEMANTIC_EVENT] [{request_id}] JID: '{jid}', Msg: '{user_message[:50]}...'")

    try:
        flows = await tags_crud.get_automation_flows(instance_id)
        tag_definitions = await tags_crud.get_tag_definitions(instance_id)

        user_message_only = user_message.strip()

        # Obter histórico da conversa para contexto
        conversation_context = None
        try:
            from src.core.prospect_management.state import get_prospect
            prospect = await get_prospect(jid)
            if prospect and prospect.history:
                # Pegar últimas mensagens para contexto
                conversation_context = prospect.history[-10:] if len(prospect.history) > 10 else prospect.history
                logger.debug(f"[{request_id}] Contexto da conversa carregado: {len(conversation_context)} mensagens")
        except Exception as e:
            logger.warning(f"[{request_id}] Não foi possível obter contexto da conversa: {e}")

        logger.info(f"[{_now().isoformat()}] [PROCESS_AI_SEMANTIC_EVENT] [{request_id}] "
                   f"Analisando com LLM - Mensagem: '{user_message_only[:100]}' | Contexto: {len(conversation_context) if conversation_context else 0} msgs")

        # Processar gatilhos de tags com ai_semantic
        tags_applied = []
        tags_rejected = []

        for tag_def in tag_definitions:
            auto_triggers = tag_def.get('auto_triggers', [])
            for trigger in auto_triggers:
                if trigger.get('type') == 'ai_semantic':
                    custom_instruction = trigger.get('custom_instruction', '')
                    if custom_instruction:
                        tag_name = tag_def.get('name')
                        # Usar análise semântica com LLM
                        match_result = await _check_custom_instruction_match(
                            user_message_only,
                            custom_instruction,
                            tag_name=tag_name,
                            request_id=request_id,
                            conversation_context=conversation_context
                        )

                        if match_result['matched']:
                            logger.info(f"[{_now().isoformat()}] [PROCESS_AI_SEMANTIC_EVENT] [{request_id}] "
                                       f"✅ Aplicando tag '{tag_name}' - Confidence: {match_result['ratio']:.0%} "
                                       f"- Reason: {match_result.get('reason', 'N/A')}")
                            await tags_crud.add_tag_to_prospect(jid, tag_name, instance_id)
                            tags_applied.append(tag_name)
                        else:
                            tags_rejected.append({
                                'tag': tag_name,
                                'ratio': match_result['ratio'],
                                'reason': match_result.get('reason', 'not_matched')
                            })

        # Log de tags rejeitadas para debug
        if tags_rejected:
            for t in tags_rejected:
                logger.debug(f"[{request_id}] Tag '{t['tag']}' rejeitada - Confidence: {t['ratio']:.0%}, Reason: {t['reason']}")

        # Processar fluxos de automação com gatilho ai_semantic
        matching_flows = []
        for flow in flows:
            if not flow.get('enabled', True):
                continue

            trigger = flow.get('trigger', {})
            if trigger.get('type') == 'ai_semantic':
                custom_instruction = trigger.get('custom_instruction', '')
                if custom_instruction:
                    match_result = await _check_custom_instruction_match(
                        user_message_only,
                        custom_instruction,
                        tag_name=flow.get('name', 'flow'),
                        request_id=request_id,
                        conversation_context=conversation_context
                    )
                    if match_result['matched']:
                        matching_flows.append(flow)

        logger.info(f"[{_now().isoformat()}] [PROCESS_AI_SEMANTIC_EVENT] [{request_id}] {len(matching_flows)} fluxos correspondem")

        for flow in matching_flows:
            await _execute_automation_flow(jid, flow, 'ai_semantic', user_message[:100], instance_id)

        duration = (_now() - start_time).total_seconds() * 1000
        logger.info(f"[{_now().isoformat()}] [PROCESS_AI_SEMANTIC_EVENT] [{request_id}] "
                   f"Concluído em {duration:.2f}ms - Tags aplicadas: {tags_applied if tags_applied else 'nenhuma'}")

    except Exception as e:
        logger.error(f"[{_now().isoformat()}] [PROCESS_AI_SEMANTIC_EVENT] [{request_id}] ERRO: {e}", exc_info=True)


async def _check_custom_instruction_match(
    user_message: str,
    instruction: str,
    tag_name: str = None,
    request_id: str = None,
    conversation_context: list = None
) -> dict:
    """
    Verifica se a mensagem do usuário corresponde à instrução customizada usando análise semântica com LLM.

    Esta função usa a LLM para fazer análise semântica REAL da intenção do usuário,
    comparando com a instrução customizada definida no frontend.

    Args:
        user_message: Mensagem enviada pelo usuário
        instruction: Instrução customizada definida pelo usuário no frontend
        tag_name: Nome da tag para logging
        request_id: ID da requisição para logging
        conversation_context: Lista de mensagens anteriores para contexto

    Returns:
        dict com:
            - matched: bool indicando se houve correspondência
            - ratio: float com a confiança da correspondência (0 a 1)
            - matched_words: int (mantido para compatibilidade, será 1 se matched)
            - total_keywords: int (mantido para compatibilidade, será 1)
            - reason: str com motivo da decisão
    """
    result = {
        'matched': False,
        'ratio': 0.0,
        'matched_words': 0,
        'total_keywords': 1,
        'reason': 'not_evaluated'
    }

    try:
        user_message_clean = user_message.strip()
        instruction_clean = instruction.strip()

        # Validação básica
        if not user_message_clean:
            result['reason'] = 'empty_user_message'
            return result

        if not instruction_clean:
            result['reason'] = 'empty_instruction'
            return result

        # Usar análise semântica com LLM
        from src.core.llm import analyze_semantic_intent_with_llm

        llm_result = await analyze_semantic_intent_with_llm(
            user_message=user_message_clean,
            custom_instruction=instruction_clean,
            conversation_context=conversation_context,
            tag_name=tag_name
        )

        # Converter resultado da LLM para formato compatível
        result['matched'] = llm_result.get('matched', False)
        result['ratio'] = llm_result.get('confidence', 0.0)
        result['matched_words'] = 1 if result['matched'] else 0
        result['reason'] = llm_result.get('reason', 'llm_analysis_completed')

        # Log do resultado
        logger.info(f"[CHECK_INSTRUCTION_LLM] Tag '{tag_name}': "
                   f"Matched: {result['matched']}, "
                   f"Confidence: {result['ratio']:.2f}, "
                   f"Reason: {result['reason']}")

        return result

    except Exception as e:
        logger.error(f"[CHECK_CUSTOM_INSTRUCTION] Erro na análise semântica com LLM: {e}", exc_info=True)
        result['reason'] = f'error: {str(e)}'
        return result


async def process_message_event(jid: str, message: str, instance_id: str):
    """
    Processa evento de mensagem recebida e executa fluxos correspondentes.
    Inclui detecção de palavras-chave.

    Args:
        jid: Identificador do prospect
        message: Conteúdo da mensagem
        instance_id: ID da instância
    """
    start_time = _now()
    request_id = f"proc_msg_{_now().timestamp()}"

    logger.info(f"[{_now().isoformat()}] [PROCESS_MESSAGE_EVENT] [{request_id}] JID: '{jid}', Msg: '{message[:50]}...'")

    try:
        flows = await tags_crud.get_automation_flows(instance_id)

        if not flows:
            return

        matching_flows = []
        for flow in flows:
            if not flow.get('enabled', True):
                continue

            trigger = flow.get('trigger', {})
            trigger_type = trigger.get('type')

            if trigger_type == 'message_received':
                matching_flows.append(flow)

            elif trigger_type == 'keyword_detected':
                keywords = trigger.get('keywords', [])
                case_sensitive = trigger.get('case_sensitive', False)

                msg_to_check = message if case_sensitive else message.lower()

                for keyword in keywords:
                    kw_to_check = keyword if case_sensitive else keyword.lower()
                    if kw_to_check in msg_to_check:
                        matching_flows.append(flow)
                        break

        for flow in matching_flows:
            trigger_type = flow.get('trigger', {}).get('type')
            await _execute_automation_flow(jid, flow, trigger_type, message[:100], instance_id)

        duration = (_now() - start_time).total_seconds() * 1000
        logger.info(f"[{_now().isoformat()}] [PROCESS_MESSAGE_EVENT] [{request_id}] Concluído em {duration:.2f}ms")

    except Exception as e:
        logger.error(f"[{_now().isoformat()}] [PROCESS_MESSAGE_EVENT] [{request_id}] ERRO: {e}", exc_info=True)


# ==================== FLOW EXECUTOR ====================

async def _execute_automation_flow(
    jid: str,
    flow: Dict[str, Any],
    trigger_type: str,
    trigger_value: str,
    instance_id: str
):
    """
    Executa um fluxo de automação específico.

    Args:
        jid: Identificador do prospect
        flow: Configuração do fluxo
        trigger_type: Tipo de gatilho que disparou
        trigger_value: Valor do gatilho
        instance_id: ID da instância
    """
    start_time = _now()
    flow_id = flow.get('id', 'unknown')
    flow_name = flow.get('name', 'Unnamed Flow')
    request_id = f"exec_flow_{flow_id}_{_now().timestamp()}"

    logger.info(f"[{_now().isoformat()}] [EXECUTE_AUTOMATION_FLOW] [{request_id}] Iniciando fluxo '{flow_name}' para JID '{jid}'")

    actions_executed: List[Dict[str, Any]] = []
    status = 'success'
    error_message = None

    try:
        # Verificar condições do fluxo (se houver)
        conditions = flow.get('conditions', [])
        if conditions and not await _check_conditions(jid, conditions, instance_id):
            logger.info(f"[{_now().isoformat()}] [EXECUTE_AUTOMATION_FLOW] [{request_id}] Condições não atendidas, fluxo não executado")
            return

        # Executar ações do fluxo
        actions = flow.get('actions', [])

        for i, action in enumerate(actions):
            action_start = _now()
            action_type = action.get('type')
            action_result = {
                'index': i,
                'type': action_type,
                'status': 'pending',
                'timestamp': action_start.isoformat()
            }

            try:
                logger.info(f"[{_now().isoformat()}] [EXECUTE_AUTOMATION_FLOW] [{request_id}] Executando ação {i+1}/{len(actions)}: {action_type}")

                # Verificar delay antes da ação
                delay_ms = action.get('delay_ms', 0)
                if delay_ms > 0:
                    logger.info(f"[{_now().isoformat()}] [EXECUTE_AUTOMATION_FLOW] [{request_id}] Aguardando delay de {delay_ms}ms")
                    await asyncio.sleep(delay_ms / 1000)

                # Executar ação
                success = await _execute_action(jid, action, instance_id)

                action_result['status'] = 'success' if success else 'failed'
                action_result['duration_ms'] = (_now() - action_start).total_seconds() * 1000

                if not success:
                    status = 'partial'
                    logger.warning(f"[{_now().isoformat()}] [EXECUTE_AUTOMATION_FLOW] [{request_id}] Ação {action_type} falhou")

            except Exception as e:
                action_result['status'] = 'error'
                action_result['error'] = str(e)
                status = 'partial'
                logger.error(f"[{_now().isoformat()}] [EXECUTE_AUTOMATION_FLOW] [{request_id}] Erro na ação {action_type}: {e}", exc_info=True)

            actions_executed.append(action_result)

    except Exception as e:
        status = 'failed'
        error_message = str(e)
        logger.error(f"[{_now().isoformat()}] [EXECUTE_AUTOMATION_FLOW] [{request_id}] ERRO CRÍTICO: {e}", exc_info=True)

    finally:
        # Registrar execução no histórico
        await tags_crud.log_automation_execution(
            jid=jid,
            flow_id=flow_id,
            flow_name=flow_name,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            actions_executed=actions_executed,
            status=status,
            error_message=error_message,
            instance_id=instance_id
        )

        duration = (_now() - start_time).total_seconds() * 1000
        logger.info(f"[{_now().isoformat()}] [EXECUTE_AUTOMATION_FLOW] [{request_id}] Fluxo '{flow_name}' concluído - Status: {status}, Duração: {duration:.2f}ms")


async def _check_conditions(jid: str, conditions: List[Dict[str, Any]], instance_id: str) -> bool:
    """
    Verifica se as condições do fluxo são atendidas.

    Args:
        jid: Identificador do prospect
        conditions: Lista de condições
        instance_id: ID da instância

    Returns:
        True se todas as condições são atendidas
    """
    logger.debug(f"[AUTOMATION_ENGINE] Verificando {len(conditions)} condições para JID '{jid}'")

    try:
        from src.core.prospect_management.state import get_prospect
        prospect = await get_prospect(jid)

        if not prospect:
            logger.warning(f"[AUTOMATION_ENGINE] Prospect '{jid}' não encontrado para verificação de condições")
            return False

        current_tags = await tags_crud.get_prospect_tags(jid, instance_id)

        for condition in conditions:
            condition_type = condition.get('type')
            operator = condition.get('operator', 'equals')
            value = condition.get('value')

            if condition_type == 'has_tag':
                if value not in current_tags:
                    return False

            elif condition_type == 'not_has_tag':
                if value in current_tags:
                    return False

            elif condition_type == 'stage':
                if operator == 'equals' and prospect.stage != int(value):
                    return False
                elif operator == 'greater_than' and prospect.stage <= int(value):
                    return False
                elif operator == 'less_than' and prospect.stage >= int(value):
                    return False

            elif condition_type == 'llm_paused':
                expected = value.lower() == 'true' if isinstance(value, str) else bool(value)
                if prospect.llm_paused != expected:
                    return False

        return True

    except Exception as e:
        logger.error(f"[AUTOMATION_ENGINE] Erro ao verificar condições: {e}", exc_info=True)
        return False


async def _execute_action(jid: str, action: Dict[str, Any], instance_id: str) -> bool:
    """
    Executa uma ação específica.

    Args:
        jid: Identificador do prospect
        action: Configuração da ação
        instance_id: ID da instância

    Returns:
        True se a ação foi executada com sucesso
    """
    action_type = action.get('type')

    logger.info(f"[{_now().isoformat()}] [EXECUTE_ACTION] Executando '{action_type}' para JID '{jid}'")

    try:
        if action_type == 'send_message':
            return await _action_send_message(jid, action.get('text', ''), instance_id)

        elif action_type == 'send_audio':
            return await _action_send_audio(jid, action.get('audio_file', ''), instance_id)

        elif action_type == 'add_tag':
            tag = action.get('tag')
            return await tags_crud.add_tag_to_prospect(jid, tag, instance_id)

        elif action_type == 'remove_tag':
            tag = action.get('tag')
            return await tags_crud.remove_tag_from_prospect(jid, tag, instance_id)

        elif action_type == 'change_stage':
            stage = int(action.get('stage', 1))
            return await _action_change_stage(jid, stage, instance_id)

        elif action_type == 'change_funnel':
            funnel_id = action.get('funnel_id', '')
            reset_stage = action.get('reset_stage', True)
            logger.info(f"[EXECUTE_ACTION] change_funnel - Dados da ação: {action}")
            logger.info(f"[EXECUTE_ACTION] change_funnel - funnel_id extraído: '{funnel_id}', reset_stage: {reset_stage}")
            return await _action_change_funnel(jid, funnel_id, reset_stage, instance_id)

        elif action_type == 'pause_llm':
            logger.info(f"[EXECUTE_ACTION] 🔴 PAUSE_LLM - JID: '{jid}' - Dados da ação: {action}")
            result = await _action_set_llm_pause(jid, True, instance_id)
            logger.info(f"[EXECUTE_ACTION] 🔴 PAUSE_LLM - Resultado: {result}")
            return result

        elif action_type == 'resume_llm':
            logger.info(f"[EXECUTE_ACTION] 🟢 RESUME_LLM - JID: '{jid}' - Dados da ação: {action}")
            result = await _action_set_llm_pause(jid, False, instance_id)
            logger.info(f"[EXECUTE_ACTION] 🟢 RESUME_LLM - Resultado: {result}")
            return result

        elif action_type == 'mark_status':
            status = action.get('status', 'active')
            return await _action_mark_status(jid, status, instance_id)

        elif action_type == 'notify_team':
            notify_number = action.get('notify_number', '')
            message = action.get('message', '')
            logger.info(f"[EXECUTE_ACTION] 📢 NOTIFY_TEAM - JID: '{jid}', Number: '{notify_number}', Msg: '{message[:50] if message else 'N/A'}' - Dados da ação: {action}")
            result = await _action_notify_team(jid, notify_number, message, instance_id)
            logger.info(f"[EXECUTE_ACTION] 📢 NOTIFY_TEAM - Resultado: {result}")
            return result

        elif action_type == 'schedule_followup':
            delay_minutes = action.get('delay_minutes', 60)
            message = action.get('message', '')
            return await _action_schedule_followup(jid, delay_minutes, message, instance_id)

        else:
            logger.warning(f"[EXECUTE_ACTION] Tipo de ação desconhecido: '{action_type}'")
            return False

    except Exception as e:
        logger.error(f"[EXECUTE_ACTION] Erro ao executar ação '{action_type}': {e}", exc_info=True)
        return False


# ==================== ACTION IMPLEMENTATIONS ====================

async def _action_send_message(jid: str, text: str, instance_id: str) -> bool:
    """Envia mensagem de texto para o prospect."""
    try:
        from src.core.prospect_management.state import get_prospect, add_message_to_history_state
        from src.core.prospect_management.message_handling import _send_text_message_mh

        # Substituir placeholders
        prospect = await get_prospect(jid)
        if prospect and prospect.name:
            text = text.replace('[NOME]', prospect.name)
        else:
            text = text.replace('[NOME]', 'Olá')

        # Enviar mensagem
        success = await _send_text_message_mh(jid, text)

        if success:
            await add_message_to_history_state(
                jid,
                'assistant',
                f"[AUTOMAÇÃO] {text}",
                conversation_initiator_override=prospect.conversation_initiator if prospect else None
            )

        return success

    except Exception as e:
        logger.error(f"[ACTION_SEND_MESSAGE] Erro: {e}", exc_info=True)
        return False


async def _action_send_audio(jid: str, audio_file: str, instance_id: str) -> bool:
    """Envia áudio para o prospect."""
    try:
        from src.core.config import settings
        from src.core.prospect_management.state import get_prospect, add_message_to_history_state
        from src.core.prospect_management.message_handling import _send_audio_message_mh

        if not audio_file:
            logger.warning(f"[ACTION_SEND_AUDIO] Nenhum arquivo de áudio especificado para JID '{jid}'")
            return False

        # Construir caminho do áudio
        audio_path = settings.FLOW_AUDIO_DIR / audio_file

        if not audio_path.is_file():
            logger.error(f"[ACTION_SEND_AUDIO] Arquivo de áudio '{audio_file}' não encontrado em '{settings.FLOW_AUDIO_DIR}'")
            return False

        # Enviar áudio
        success = await _send_audio_message_mh(jid, str(audio_path), None)

        if success:
            prospect = await get_prospect(jid)
            await add_message_to_history_state(
                jid,
                'assistant',
                f"[AUTOMAÇÃO] [ÁUDIO: {audio_file}]",
                conversation_initiator_override=prospect.conversation_initiator if prospect else None
            )

        return success

    except Exception as e:
        logger.error(f"[ACTION_SEND_AUDIO] Erro: {e}", exc_info=True)
        return False


async def _action_change_stage(jid: str, stage: int, instance_id: str) -> bool:
    """Muda o estágio do prospect."""
    try:
        from src.core.prospect_management.state import update_prospect_stage_state
        await update_prospect_stage_state(jid, stage)
        return True
    except Exception as e:
        logger.error(f"[ACTION_CHANGE_STAGE] Erro: {e}", exc_info=True)
        return False


async def _action_change_funnel(jid: str, funnel_id: str, reset_stage: bool, instance_id: str) -> bool:
    """Muda o funil do prospect."""
    try:
        from src.core.db_operations.prospect_crud import update_prospect_funnel_db, get_prospect_funnel_id
        from src.core.prospect_management.state import get_prospect, update_prospect_stage_state

        logger.info(f"[ACTION_CHANGE_FUNNEL] === INÍCIO === JID: '{jid}', funnel_id: '{funnel_id}', reset_stage: {reset_stage}")

        # Verificar funnel_id atual antes da mudança
        current_funnel = await get_prospect_funnel_id(jid, instance_id)
        logger.info(f"[ACTION_CHANGE_FUNNEL] Funil atual do prospect '{jid}': '{current_funnel}'")

        if not funnel_id:
            logger.error(f"[ACTION_CHANGE_FUNNEL] ❌ ERRO: funnel_id vazio/None para JID '{jid}'. Ação ABORTADA.")
            return False

        if funnel_id == current_funnel:
            logger.info(f"[ACTION_CHANGE_FUNNEL] Prospect '{jid}' já está no funil '{funnel_id}'. Nenhuma mudança necessária.")
            return True

        # Atualizar o funil do prospect no banco
        logger.info(f"[ACTION_CHANGE_FUNNEL] Chamando update_prospect_funnel_db para '{jid}' -> funil '{funnel_id}'")
        success = await update_prospect_funnel_db(jid, funnel_id, instance_id)

        if not success:
            logger.error(f"[ACTION_CHANGE_FUNNEL] ❌ ERRO: update_prospect_funnel_db retornou False para '{jid}'")
            return False

        # Verificar se a mudança foi persistida
        new_funnel = await get_prospect_funnel_id(jid, instance_id)
        logger.info(f"[ACTION_CHANGE_FUNNEL] Verificação pós-update: funil atual = '{new_funnel}'")

        if new_funnel != funnel_id:
            logger.error(f"[ACTION_CHANGE_FUNNEL] ❌ ERRO: Funil não foi persistido! Esperado: '{funnel_id}', Atual: '{new_funnel}'")
            return False

        # Se reset_stage é True, voltar para estágio 1
        if reset_stage:
            logger.info(f"[ACTION_CHANGE_FUNNEL] Resetando estágio para 1...")
            await update_prospect_stage_state(jid, 1)

        logger.info(f"[ACTION_CHANGE_FUNNEL] ✅ SUCESSO: Prospect '{jid}' movido de '{current_funnel}' para '{funnel_id}' (reset_stage={reset_stage})")
        return True

    except Exception as e:
        logger.error(f"[ACTION_CHANGE_FUNNEL] ❌ EXCEÇÃO: {e}", exc_info=True)
        return False


async def _action_set_llm_pause(jid: str, paused: bool, instance_id: str) -> bool:
    """Define status de pausa do LLM."""
    action_name = "PAUSE_LLM" if paused else "RESUME_LLM"
    logger.info(f"[ACTION_SET_LLM_PAUSE] Iniciando ação '{action_name}' para JID: '{jid}'")

    try:
        from src.core.prospect_management.state import get_prospect, save_prospect
        from src.core.db_operations.prospect_crud import update_prospect_llm_pause_status_db

        prospect = await get_prospect(jid)
        if prospect:
            old_status = prospect.llm_paused
            prospect.llm_paused = paused
            await save_prospect(prospect)
            await update_prospect_llm_pause_status_db(jid, paused, instance_id)
            logger.info(f"[ACTION_SET_LLM_PAUSE] ✅ Sucesso - JID: '{jid}' - Status LLM: {old_status} → {paused}")
            return True
        else:
            logger.warning(f"[ACTION_SET_LLM_PAUSE] ⚠️ Prospect não encontrado na memória para JID: '{jid}' - Tentando atualizar apenas no DB")
            # Mesmo sem o prospect em memória, tenta atualizar no banco
            try:
                await update_prospect_llm_pause_status_db(jid, paused, instance_id)
                logger.info(f"[ACTION_SET_LLM_PAUSE] ✅ Sucesso (DB only) - JID: '{jid}' - Status LLM atualizado para: {paused}")
                return True
            except Exception as db_err:
                logger.error(f"[ACTION_SET_LLM_PAUSE] ❌ Falha ao atualizar DB para JID '{jid}': {db_err}")
                return False

    except Exception as e:
        logger.error(f"[ACTION_SET_LLM_PAUSE] ❌ Erro crítico para JID '{jid}': {e}", exc_info=True)
        return False


async def _action_mark_status(jid: str, status: str, instance_id: str) -> bool:
    """Marca o status do prospect."""
    try:
        from src.core.db_operations.prospect_crud import update_prospect_status_db
        await update_prospect_status_db(jid, status, instance_id)
        return True
    except Exception as e:
        logger.error(f"[ACTION_MARK_STATUS] Erro: {e}", exc_info=True)
        return False


async def _action_notify_team(jid: str, notify_number: str, message: str, instance_id: str) -> bool:
    """Envia notificação para a equipe via WhatsApp e WebSocket."""
    logger.info(f"[ACTION_NOTIFY_TEAM] Iniciando notificação - JID: '{jid}', Notify: '{notify_number}', Msg: '{message[:50] if message else 'N/A'}...'")

    try:
        from src.core.websocket_manager import manager
        from src.core.prospect_management.state import get_prospect
        from src.core.prospect_management.message_handling import _send_text_message_mh
        from src.utils.formatting import clean_phone_number

        prospect = await get_prospect(jid)
        prospect_name = prospect.name if prospect else jid
        logger.info(f"[ACTION_NOTIFY_TEAM] Prospect: '{prospect_name}'")

        # Preparar mensagem de notificação
        notification_text = f"🔔 *Notificação de Automação*\n\n"
        notification_text += f"📱 Prospect: {prospect_name}\n"
        notification_text += f"📞 Número: {jid}\n"
        notification_text += f"💬 {message}" if message else ""

        # Enviar via WhatsApp se número foi fornecido
        whatsapp_sent = False
        if notify_number:
            logger.info(f"[ACTION_NOTIFY_TEAM] Número de notificação fornecido: '{notify_number}'")
            cleaned_number = clean_phone_number(notify_number)
            logger.info(f"[ACTION_NOTIFY_TEAM] Número limpo: '{cleaned_number}'")

            if cleaned_number:
                logger.info(f"[ACTION_NOTIFY_TEAM] Enviando WhatsApp para '{cleaned_number}'...")
                whatsapp_sent = await _send_text_message_mh(cleaned_number, notification_text)
                if whatsapp_sent:
                    logger.info(f"[ACTION_NOTIFY_TEAM] ✅ Notificação enviada via WhatsApp para {cleaned_number}")
                else:
                    logger.warning(f"[ACTION_NOTIFY_TEAM] ❌ Falha ao enviar notificação via WhatsApp para {cleaned_number}")
            else:
                logger.warning(f"[ACTION_NOTIFY_TEAM] ⚠️ Número de notificação inválido após limpeza: original='{notify_number}'")
        else:
            logger.info(f"[ACTION_NOTIFY_TEAM] ⚠️ Nenhum número de notificação fornecido, pulando WhatsApp")

        # Também enviar via WebSocket para o dashboard
        logger.info(f"[ACTION_NOTIFY_TEAM] Enviando broadcast WebSocket 'team_notification'...")
        await manager.broadcast('team_notification', {
            'type': 'automation_alert',
            'jid': jid,
            'prospect_name': prospect_name,
            'message': message,
            'notify_number': notify_number,
            'whatsapp_sent': whatsapp_sent,
            'timestamp': _now().isoformat()
        })
        logger.info(f"[ACTION_NOTIFY_TEAM] ✅ Broadcast WebSocket enviado com sucesso")

        logger.info(f"[ACTION_NOTIFY_TEAM] ✅ Ação concluída - WhatsApp: {whatsapp_sent}, WebSocket: True")
        return True

    except Exception as e:
        logger.error(f"[ACTION_NOTIFY_TEAM] ❌ Erro crítico: {e}", exc_info=True)
        return False


async def _action_schedule_followup(jid: str, delay_minutes: int, message: str, instance_id: str) -> bool:
    """Agenda um follow-up para o prospect."""
    try:
        # Criar uma task assíncrona para executar o follow-up após o delay
        async def delayed_followup():
            await asyncio.sleep(delay_minutes * 60)
            await _action_send_message(jid, message, instance_id)

        asyncio.create_task(delayed_followup())

        logger.info(f"[ACTION_SCHEDULE_FOLLOWUP] Follow-up agendado para JID '{jid}' em {delay_minutes} minutos")
        return True

    except Exception as e:
        logger.error(f"[ACTION_SCHEDULE_FOLLOWUP] Erro: {e}", exc_info=True)
        return False


# ==================== INACTIVITY CHECKER ====================

async def check_inactivity_for_all_prospects(instance_id: str):
    """
    Verifica inatividade de todos os prospects ativos e dispara eventos.
    Esta função deve ser chamada periodicamente por um scheduler.
    """
    start_time = _now()
    request_id = f"check_inact_{_now().timestamp()}"

    logger.info(f"[{_now().isoformat()}] [CHECK_INACTIVITY] [{request_id}] Iniciando verificação de inatividade")

    try:
        from src.core.db_operations.prospect_crud import get_prospects_list
        from src.core.prospect_management.state import get_prospect

        # Buscar prospects ativos
        prospects, _ = await get_prospects_list(status='active', limit=1000)

        now = _now()

        for prospect_data in prospects:
            jid = prospect_data.get('jid')

            # Buscar estado completo do Redis
            prospect = await get_prospect(jid)
            if not prospect or not prospect.last_outgoing_message_at:
                continue

            # Calcular inatividade
            last_interaction = prospect.last_outgoing_message_at
            if not last_interaction.tzinfo:
                last_interaction = SAO_PAULO_TZ.localize(last_interaction)

            inactivity_delta = now - last_interaction
            inactivity_minutes = int(inactivity_delta.total_seconds() / 60)

            # Processar evento de inatividade (apenas se > 30 minutos)
            if inactivity_minutes >= 30:
                await process_inactivity_event(jid, inactivity_minutes, instance_id)

        duration = (_now() - start_time).total_seconds() * 1000
        logger.info(f"[{_now().isoformat()}] [CHECK_INACTIVITY] [{request_id}] Concluído em {duration:.2f}ms - {len(prospects)} prospects verificados")

    except Exception as e:
        logger.error(f"[{_now().isoformat()}] [CHECK_INACTIVITY] [{request_id}] ERRO: {e}", exc_info=True)


logger.info("automation_engine: Module loaded.")
