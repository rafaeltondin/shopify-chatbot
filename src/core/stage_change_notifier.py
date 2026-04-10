# -*- coding: utf-8 -*-
"""
Stage Change Notifier Module

Este modulo e responsavel por:
1. Verificar configuracao de notificacoes de mudanca de etapa
2. Enviar notificacao via WhatsApp quando um prospect muda de etapa no funil
"""
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
import pytz

from src.core.config import settings
from src.core.db_operations.config_crud import get_stage_change_notification_config, get_sales_flow_stages
from src.core import evolution

logger = logging.getLogger(__name__)


def get_stage_name_from_config(stage_number: int, stages_config: list) -> str:
    """
    Obtem o nome do estagio a partir da configuracao do funil.

    Args:
        stage_number: Numero do estagio
        stages_config: Lista de configuracoes de estagios

    Returns:
        Nome do estagio ou "Estagio X" como fallback
    """
    for stage in stages_config:
        if stage.get("stage_number") == stage_number:
            return stage.get("objective", f"Estagio {stage_number}")
    return f"Estagio {stage_number}"


async def should_notify_stage(
    new_stage: int,
    config: Dict[str, Any],
    prospect_funnel_id: Optional[str] = None
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Verifica se deve enviar notificacao para a etapa especificada.

    Args:
        new_stage: Numero da nova etapa
        config: Configuracao de notificacoes
        prospect_funnel_id: ID do funil do prospect (opcional)

    Returns:
        Tuple (deve_notificar, regra_especifica) - regra_especifica pode ser None se notify_all_stages=True
    """
    # Se nao esta habilitado, nao notifica
    if not config.get("enabled", True):
        logger.debug(f"[StageChangeNotifier] Notificacoes desabilitadas.")
        return False, None

    # Se nao tem numero configurado, nao notifica
    notification_number = config.get("notification_whatsapp_number")
    if not notification_number:
        logger.debug(f"[StageChangeNotifier] Numero de WhatsApp para notificacao nao configurado.")
        return False, None

    # Se notify_all_stages e notify_all_funnels estao ativos, notifica todas
    notify_all_stages = config.get("notify_all_stages", True)
    notify_all_funnels = config.get("notify_all_funnels", True)

    if notify_all_stages and notify_all_funnels:
        logger.debug(f"[StageChangeNotifier] notify_all_stages=True e notify_all_funnels=True, notificando estagio {new_stage}.")
        return True, None

    # Se notify_all_stages=True mas notify_all_funnels=False, precisamos verificar funil nas regras
    if notify_all_stages and not notify_all_funnels:
        # Verificar se existe alguma regra para o funil do prospect
        stage_rules = config.get("stage_rules", [])
        for rule in stage_rules:
            rule_funnel_id = rule.get("funnel_id")
            # Se a regra nao tem funnel_id (None), aplica a todos os funis
            # Se a regra tem funnel_id, verifica se bate com o funil do prospect
            if rule_funnel_id is None or rule_funnel_id == prospect_funnel_id:
                if rule.get("enabled", True):
                    logger.debug(f"[StageChangeNotifier] Regra para funil '{rule_funnel_id}' encontrada e habilitada.")
                    return True, rule

        # Se nao encontrou regra especifica para o funil, nao notifica
        logger.debug(f"[StageChangeNotifier] Nenhuma regra encontrada para funil '{prospect_funnel_id}'.")
        return False, None

    # Verificar nas stage_rules se a etapa especifica esta habilitada
    stage_rules = config.get("stage_rules", [])
    for rule in stage_rules:
        if rule.get("stage_number") == new_stage and rule.get("enabled", True):
            rule_funnel_id = rule.get("funnel_id")

            # Verificar filtro de funil
            # Se notify_all_funnels=True ou regra nao tem funnel_id, aceita qualquer funil
            # Se notify_all_funnels=False e regra tem funnel_id, verifica se bate
            if notify_all_funnels or rule_funnel_id is None or rule_funnel_id == prospect_funnel_id:
                logger.debug(f"[StageChangeNotifier] Estagio {new_stage} encontrado nas stage_rules e habilitado (funil: {rule_funnel_id}, prospect_funil: {prospect_funnel_id}).")
                return True, rule
            else:
                logger.debug(f"[StageChangeNotifier] Estagio {new_stage} encontrado mas funil nao corresponde (regra: {rule_funnel_id}, prospect: {prospect_funnel_id}).")

    logger.debug(f"[StageChangeNotifier] Estagio {new_stage} nao esta nas stage_rules habilitadas para o funil '{prospect_funnel_id}'.")
    return False, None


async def send_stage_change_notification(
    prospect_jid: str,
    prospect_name: Optional[str],
    old_stage: int,
    new_stage: int,
    instance_id: str = None,
    prospect_funnel_id: Optional[str] = None
) -> bool:
    """
    Envia notificacao via WhatsApp quando um prospect muda de etapa.

    Args:
        prospect_jid: JID do prospect
        prospect_name: Nome do prospect (opcional)
        old_stage: Estagio anterior
        new_stage: Novo estagio
        instance_id: ID da instancia (opcional, usa settings.INSTANCE_ID se nao fornecido)
        prospect_funnel_id: ID do funil do prospect (opcional)

    Returns:
        True se notificacao enviada com sucesso, False caso contrario
    """
    try:
        # Obter configuracao
        config = await get_stage_change_notification_config(instance_id=instance_id or settings.INSTANCE_ID)

        # Se prospect_funnel_id nao foi fornecido, buscar do banco
        if prospect_funnel_id is None:
            from src.core.db_operations.prospect_crud import get_prospect_funnel_id
            prospect_funnel_id = await get_prospect_funnel_id(prospect_jid, instance_id or settings.INSTANCE_ID)
            logger.debug(f"[StageChangeNotifier] Funil do prospect '{prospect_jid}' obtido do banco: {prospect_funnel_id}")

        # Verificar se deve notificar esta etapa (com filtro de funil)
        should_notify, matched_rule = await should_notify_stage(new_stage, config, prospect_funnel_id)
        if not should_notify:
            return False

        notification_number = config.get("notification_whatsapp_number")
        if not notification_number:
            logger.warning("[StageChangeNotifier] Numero de WhatsApp para notificacao nao configurado.")
            return False

        # Obter configuracao do funil para nomes das etapas
        stages_config = await get_sales_flow_stages(instance_id=instance_id or settings.INSTANCE_ID)

        # Preparar variaveis para o template
        sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
        now = datetime.now(sao_paulo_tz)

        # Limpar numero do prospect para exibicao
        clean_prospect_phone = prospect_jid.replace("@s.whatsapp.net", "").replace("@c.us", "")

        # Obter nomes das etapas
        old_stage_name = get_stage_name_from_config(old_stage, stages_config)
        new_stage_name = get_stage_name_from_config(new_stage, stages_config)

        template_vars = {
            "prospect_name": prospect_name or "Nao identificado",
            "prospect_phone": clean_prospect_phone,
            "stage_name": new_stage_name,
            "stage_number": new_stage,
            "old_stage_name": old_stage_name,
            "old_stage_number": old_stage,
            "timestamp": now.strftime("%d/%m/%Y as %H:%M"),
        }

        # Verificar se tem template especifico para a etapa/funil
        message_template = None

        # Primeiro, usar o template da regra que correspondeu (se houver)
        if matched_rule:
            message_template = matched_rule.get("message_template")
            logger.debug(f"[StageChangeNotifier] Usando template da regra correspondente.")

        # Se nao tem template da regra, buscar por stage_number nas regras
        if not message_template:
            stage_rules = config.get("stage_rules", [])
            for rule in stage_rules:
                if rule.get("stage_number") == new_stage:
                    rule_funnel_id = rule.get("funnel_id")
                    # Preferir regra que corresponde ao funil do prospect
                    if rule_funnel_id is None or rule_funnel_id == prospect_funnel_id:
                        message_template = rule.get("message_template")
                        break

        # Se nao tem template especifico, usa o padrao
        if not message_template:
            message_template = config.get(
                "default_message_template",
                "🎯 *Prospect Avancou de Etapa!*\n\n👤 *Nome:* {prospect_name}\n📱 *Telefone:* {prospect_phone}\n\n📊 *Etapa Anterior:* {old_stage_name}\n📊 *Nova Etapa:* {stage_name}\n⏰ *Horario:* {timestamp}"
            )

        try:
            notification_message = message_template.format(**template_vars)
        except KeyError as e:
            logger.warning(f"[StageChangeNotifier] Erro ao formatar template: {e}. Usando template basico.")
            notification_message = f"🎯 *Prospect Avancou de Etapa!*\n\n👤 Nome: {template_vars['prospect_name']}\n📱 Telefone: {template_vars['prospect_phone']}\n📊 Etapa: {template_vars['old_stage_name']} → {template_vars['stage_name']}\n⏰ Horario: {template_vars['timestamp']}"

        # Enviar notificacao via Evolution API
        logger.info(f"[StageChangeNotifier] Enviando notificacao para {notification_number}... Prospect: {prospect_jid}, Etapa: {old_stage} -> {new_stage}")

        result = await evolution.send_text_message(
            jid=notification_number,
            text=notification_message
        )

        if result:
            logger.info(f"[StageChangeNotifier] Notificacao enviada com sucesso para {notification_number}")
            return True
        else:
            logger.error(f"[StageChangeNotifier] Falha ao enviar notificacao para {notification_number}")
            return False

    except Exception as e:
        logger.error(f"[StageChangeNotifier] Erro ao enviar notificacao: {e}", exc_info=True)
        return False


async def notify_stage_change_async(
    prospect_jid: str,
    prospect_name: Optional[str],
    old_stage: int,
    new_stage: int,
    instance_id: str = None,
    prospect_funnel_id: Optional[str] = None
):
    """
    Envia notificacao de mudanca de etapa de forma assincrona (fire and forget).
    Esta funcao pode ser chamada sem aguardar o resultado.

    Args:
        prospect_jid: JID do prospect
        prospect_name: Nome do prospect
        old_stage: Estagio anterior
        new_stage: Novo estagio
        instance_id: ID da instancia
        prospect_funnel_id: ID do funil do prospect (opcional)
    """
    try:
        await send_stage_change_notification(
            prospect_jid=prospect_jid,
            prospect_name=prospect_name,
            old_stage=old_stage,
            new_stage=new_stage,
            instance_id=instance_id,
            prospect_funnel_id=prospect_funnel_id
        )
    except Exception as e:
        logger.error(f"[StageChangeNotifier] Erro na notificacao assincrona: {e}", exc_info=True)


logger.info("stage_change_notifier: Modulo de notificacao de mudanca de etapa carregado.")
