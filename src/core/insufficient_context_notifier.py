# -*- coding: utf-8 -*-
"""
Insufficient Context Notifier Module

Este módulo é responsável por:
1. Detectar quando o LLM não possui contexto suficiente para responder
2. Notificar via WhatsApp um número configurado
3. Opcionalmente suprimir a resposta ao cliente ou enviar uma mensagem de fallback
"""
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
import pytz

from src.core.config import settings
from src.core.db_operations.config_crud import get_insufficient_context_notification_config
from src.core import evolution

logger = logging.getLogger(__name__)

# =============================================================================
# KEYWORDS E PADRÕES PARA DETECÇÃO DE CONTEXTO INSUFICIENTE
# =============================================================================

import re

# Frases FORTES que indicam claramente que o LLM não sabe responder
STRONG_INSUFFICIENT_INDICATORS = [
    # Frases diretas de desconhecimento
    "não tenho informações sobre",
    "não possuo informações sobre",
    "não encontrei informações sobre",
    "não tenho dados sobre",
    "não tenho acesso a essa informação",
    "não consigo encontrar essa informação",
    "não sei informar sobre",
    "não tenho essa informação",
    "não consta no meu contexto",
    "desconheço essa informação",
    "não foi informado no contexto",
    "não há informações sobre isso",
    "informação não disponível",
    "não está no meu conhecimento",
    "não tenho conhecimento sobre",
    "fora do meu conhecimento",
    "além do meu contexto",
    "não faz parte do contexto fornecido",
    "não possuo detalhes sobre",
    "não tenho detalhes sobre",
    "essa informação não foi fornecida",
    "não me foi passada essa informação",
    "não constam esses dados",
    "não disponho dessa informação",
    # Marcador explícito do LLM (o LLM foi instruído a usar estes marcadores)
    "[contexto_insuficiente]",
    "[insufficient_context]",
    "::contexto_insuficiente::",
]

# Marcadores que devem ser removidos da resposta final ao cliente
MARKERS_TO_REMOVE = [
    "[CONTEXTO_INSUFICIENTE]",
    "[contexto_insuficiente]",
    "[INSUFFICIENT_CONTEXT]",
    "[insufficient_context]",
    "::CONTEXTO_INSUFICIENTE::",
    "::contexto_insuficiente::",
]

# Frases MÉDIAS que podem indicar falta de contexto (precisam de confirmação)
MEDIUM_INSUFFICIENT_INDICATORS = [
    "não tenho certeza sobre",
    "não posso confirmar",
    "não tenho como confirmar",
    "seria necessário verificar",
    "precisaria confirmar",
    "não sei ao certo",
    "infelizmente não sei",
    "lamento, mas não sei",
    "desculpe, não tenho",
]

# Frases que indicam que vai verificar depois (promessa de retorno)
WILL_CHECK_INDICATORS = [
    "vou verificar e te retorno",
    "vou checar isso",
    "vou confirmar essa informação",
    "preciso consultar internamente",
    "deixa eu verificar isso",
    "vou buscar essa informação",
    "preciso buscar isso",
    "vou conferir e volto",
    "vou pesquisar sobre",
]

# Padrões REGEX para detecção mais precisa
INSUFFICIENT_REGEX_PATTERNS = [
    # "não tenho/possuo X sobre Y"
    r"não\s+(tenho|possuo|encontrei|há)\s+\w+\s+(sobre|para|dessa?|desse?)",
    # "essa informação não X"
    r"essa\s+informaç[ãa]o\s+n[ãa]o\s+(foi|está|consta|me)",
    # "não sei X sobre"
    r"n[ãa]o\s+sei\s+\w+\s+sobre",
    # "fora/além do meu X"
    r"(fora|al[ée]m|acima)\s+d[oa]\s+meu\s+(contexto|conhecimento|alcance)",
    # "preciso verificar/checar X"
    r"preciso\s+(verificar|checar|conferir|buscar)\s+\w+",
    # "não consta/existe X"
    r"n[ãa]o\s+(consta|existe|aparece)\s+\w+\s+(no|na|nos|nas)\s+(contexto|informa)",
]

# Palavras-chave que, se aparecerem junto com negações, indicam problema
CONTEXT_KEYWORDS = [
    "preço", "valor", "custo", "promoção", "desconto",
    "endereço", "localização", "horário", "funcionamento",
    "prazo", "entrega", "frete", "disponibilidade",
    "garantia", "especificação", "técnico", "detalhe",
    "pagamento", "parcela", "condição", "plano",
]

# Frases que NÃO indicam contexto insuficiente (falsos positivos)
FALSE_POSITIVE_INDICATORS = [
    "não tenho dúvidas",
    "não tenho mais perguntas",
    "não tenho interesse",
    "não preciso",
    "não quero",
    "não tenho tempo",
    "não tenho disponibilidade",
    "não sei seu nome",
    "não sei como você se chama",
    "não tenho seu email",
    "não tenho seu contato",
    "me diga seu",
    "qual seu",
    "pode me informar seu",
]

# Palavras-chave relacionadas a agenda/agendamento (NÃO devem disparar contexto insuficiente)
# O sistema TEM acesso a agenda via Google Calendar API
AGENDA_RELATED_KEYWORDS = [
    "agenda",
    "horário",
    "horarios",
    "agendar",
    "agendamento",
    "disponibilidade",
    "disponível",
    "disponivel",
    "consulta",
    "marcar",
    "reservar",
    "semana",
    "dia",
    "segunda",
    "terça",
    "quarta",
    "quinta",
    "sexta",
    "sábado",
    "domingo",
]


def clean_response_markers(response_text: str) -> str:
    """
    Remove marcadores de contexto insuficiente da resposta final.

    Args:
        response_text: Texto da resposta do LLM

    Returns:
        Texto limpo sem os marcadores
    """
    if not response_text:
        return response_text

    cleaned = response_text
    for marker in MARKERS_TO_REMOVE:
        cleaned = cleaned.replace(marker, "")

    # Limpar espaços extras e quebras de linha no início
    cleaned = cleaned.strip()

    return cleaned


def is_agenda_related_query(customer_message: str) -> bool:
    """
    Verifica se a mensagem do cliente é relacionada a agenda/agendamento.

    Perguntas sobre agenda NÃO devem disparar "contexto insuficiente" porque
    o sistema TEM acesso à agenda via Google Calendar API.

    Args:
        customer_message: Mensagem original do cliente

    Returns:
        True se a mensagem é sobre agenda/horários
    """
    if not customer_message:
        return False

    message_lower = customer_message.lower()

    for keyword in AGENDA_RELATED_KEYWORDS:
        if keyword in message_lower:
            logger.debug(f"[InsufficientContext] Mensagem relacionada a agenda detectada: '{keyword}'")
            return True

    return False


def detect_insufficient_context(llm_response_text: str, customer_message: str = None) -> Tuple[bool, str]:
    """
    Detecta se a resposta do LLM indica falta de contexto suficiente.

    Usa múltiplas estratégias:
    - Indicadores fortes (match direto)
    - Indicadores médios (requer contexto)
    - Padrões regex
    - Análise semântica básica

    Args:
        llm_response_text: Texto da resposta do LLM
        customer_message: Mensagem original do cliente (opcional, para verificar se é sobre agenda)

    Returns:
        Tuple (is_insufficient, reason)
        - is_insufficient: True se detectado falta de contexto
        - reason: Motivo da detecção
    """
    if not llm_response_text:
        return False, ""

    text_lower = llm_response_text.lower().strip()

    # IMPORTANTE: Se a mensagem do cliente é sobre agenda, NÃO marcar como contexto insuficiente
    # O sistema tem acesso à agenda via Google Calendar API
    if customer_message and is_agenda_related_query(customer_message):
        logger.info(f"[InsufficientContext] Ignorando detecção - pergunta sobre agenda (sistema tem acesso via API)")
        return False, ""

    # Primeiro: verificar falsos positivos para evitar detecção incorreta
    for false_positive in FALSE_POSITIVE_INDICATORS:
        if false_positive in text_lower:
            logger.debug(f"[InsufficientContext] Falso positivo evitado: '{false_positive}'")
            return False, ""

    # 1. Verificar marcadores explícitos do LLM (maior prioridade)
    if "[contexto_insuficiente]" in text_lower or "[insufficient_context]" in text_lower:
        logger.info("[InsufficientContext] Marcador explícito do LLM detectado")
        return True, "Marcador explícito do LLM"

    # 2. Verificar indicadores FORTES (alta confiança)
    for indicator in STRONG_INSUFFICIENT_INDICATORS:
        if indicator in text_lower:
            logger.info(f"[InsufficientContext] Indicador forte detectado: '{indicator}'")
            return True, f"Indicador forte: '{indicator}'"

    # 3. Verificar padrões REGEX (alta precisão)
    for pattern in INSUFFICIENT_REGEX_PATTERNS:
        if re.search(pattern, text_lower):
            match = re.search(pattern, text_lower)
            logger.info(f"[InsufficientContext] Padrão regex detectado: '{match.group()}'")
            return True, f"Padrão detectado: '{match.group()}'"

    # 4. Verificar indicadores MÉDIOS com análise contextual
    for indicator in MEDIUM_INSUFFICIENT_INDICATORS:
        if indicator in text_lower:
            # Verificar se está relacionado a produto/serviço
            has_context_keyword = any(kw in text_lower for kw in CONTEXT_KEYWORDS)
            if has_context_keyword:
                logger.info(f"[InsufficientContext] Indicador médio + contexto: '{indicator}'")
                return True, f"Indicador médio com contexto: '{indicator}'"

    # 5. Verificar indicadores de "vou verificar" (promessa de retorno)
    for indicator in WILL_CHECK_INDICATORS:
        if indicator in text_lower:
            logger.info(f"[InsufficientContext] Indicador de verificação: '{indicator}'")
            return True, f"Promessa de verificação: '{indicator}'"

    # 6. Análise de negação + keyword de contexto
    negation_pattern = r"n[ãa]o\s+(tenho|possuo|sei|encontrei|há|existe|consta)"
    if re.search(negation_pattern, text_lower):
        for keyword in CONTEXT_KEYWORDS:
            if keyword in text_lower:
                # Verificar se a negação está próxima da keyword
                neg_match = re.search(negation_pattern, text_lower)
                kw_pos = text_lower.find(keyword)
                if neg_match and abs(neg_match.start() - kw_pos) < 50:
                    logger.info(f"[InsufficientContext] Negação + keyword '{keyword}' detectado")
                    return True, f"Negação relacionada a '{keyword}'"

    return False, ""


async def send_insufficient_context_notification(
    customer_phone: str,
    customer_message: str,
    llm_response: str,
    customer_name: str = None,
    detection_reason: str = None,
    instance_id: str = None
) -> bool:
    """
    Envia notificação via WhatsApp quando contexto insuficiente é detectado.

    Args:
        customer_phone: Número do cliente (JID ou número limpo)
        customer_message: Mensagem original do cliente
        llm_response: Resposta do LLM
        customer_name: Nome do cliente (opcional)
        detection_reason: Motivo da detecção (opcional)
        instance_id: ID da instância (opcional, usa settings.INSTANCE_ID se não fornecido)

    Returns:
        True se notificação enviada com sucesso, False caso contrário
    """
    try:
        # Obter configuração
        config = await get_insufficient_context_notification_config(instance_id=instance_id or settings.INSTANCE_ID)

        # Verificar se está habilitado
        if not config.get("enabled", True):
            logger.debug("[InsufficientContext] Notificação desabilitada nas configurações.")
            return False

        # Verificar se tem número configurado
        notification_number = config.get("notification_whatsapp_number")
        if not notification_number:
            logger.warning("[InsufficientContext] Número de WhatsApp para notificação não configurado.")
            return False

        # Preparar variáveis para o template
        sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
        now = datetime.now(sao_paulo_tz)

        # Limpar número do cliente para exibição
        clean_customer_phone = customer_phone.replace("@s.whatsapp.net", "").replace("@c.us", "")

        # Truncar mensagem do cliente se muito longa
        truncated_customer_message = customer_message[:300] + "..." if len(customer_message) > 300 else customer_message

        template_vars = {
            "customer_phone": clean_customer_phone,
            "customer_message": truncated_customer_message,
            "timestamp": now.strftime("%d/%m/%Y às %H:%M"),
            "customer_name": customer_name or "Não identificado",
            "detection_reason": detection_reason or "Análise automática",
            "llm_response": llm_response[:200] + "..." if len(llm_response) > 200 else llm_response
        }

        # Formatar mensagem usando o template
        message_template = config.get(
            "notification_message_template",
            "⚠️ *Contexto Insuficiente Detectado*\n\n📱 *Cliente:* {customer_phone}\n💬 *Mensagem:* {customer_message}\n\n❓ O agente de IA não encontrou informações suficientes no contexto para responder esta pergunta.\n\n⏰ *Horário:* {timestamp}"
        )

        try:
            notification_message = message_template.format(**template_vars)
        except KeyError as e:
            logger.warning(f"[InsufficientContext] Erro ao formatar template: {e}. Usando template básico.")
            notification_message = f"⚠️ *Contexto Insuficiente*\n\n📱 Cliente: {clean_customer_phone}\n💬 Mensagem: {truncated_customer_message}\n⏰ Horário: {template_vars['timestamp']}"

        # Enviar notificação via Evolution API
        logger.info(f"[InsufficientContext] Enviando notificação para {notification_number}...")

        result = await evolution.send_text_message(
            jid=notification_number,
            text=notification_message
        )

        if result:
            logger.info(f"[InsufficientContext] Notificação enviada com sucesso para {notification_number}")
            return True
        else:
            logger.error(f"[InsufficientContext] Falha ao enviar notificação para {notification_number}")
            return False

    except Exception as e:
        logger.error(f"[InsufficientContext] Erro ao enviar notificação: {e}", exc_info=True)
        return False


async def get_customer_fallback_response(instance_id: str = None) -> Tuple[bool, str]:
    """
    Obtém a resposta de fallback para o cliente quando contexto insuficiente é detectado.

    Args:
        instance_id: ID da instância

    Returns:
        Tuple (suppress_response, fallback_message)
        - suppress_response: Se True, não deve enviar nenhuma resposta ao cliente
        - fallback_message: Mensagem de fallback para enviar ao cliente
    """
    try:
        config = await get_insufficient_context_notification_config(instance_id=instance_id or settings.INSTANCE_ID)

        suppress = config.get("suppress_response_to_customer", False)
        fallback = config.get(
            "customer_fallback_message",
            "Entendi sua dúvida. Vou verificar essa informação e retorno em breve!"
        )

        return suppress, fallback

    except Exception as e:
        logger.error(f"[InsufficientContext] Erro ao obter resposta de fallback: {e}", exc_info=True)
        # Em caso de erro, retorna valores padrão seguros
        return False, "Entendi sua dúvida. Vou verificar essa informação e retorno em breve!"


async def handle_insufficient_context(
    customer_phone: str,
    customer_message: str,
    llm_response: str,
    customer_name: str = None,
    instance_id: str = None
) -> Dict[str, Any]:
    """
    Handler principal para quando contexto insuficiente é detectado.

    Args:
        customer_phone: Número do cliente
        customer_message: Mensagem original do cliente
        llm_response: Resposta original do LLM
        customer_name: Nome do cliente (opcional)
        instance_id: ID da instância (opcional)

    Returns:
        Dict com:
        - detected: bool - Se contexto insuficiente foi detectado
        - notification_sent: bool - Se notificação foi enviada
        - action: str - Ação a ser tomada ("send_text", "suppress", etc.)
        - response_text: str - Texto de resposta para o cliente (se aplicável)
        - reason: str - Motivo da detecção
        - cleaned_response: str - Resposta limpa (sem marcadores) para usar se não suprimir
    """
    # Limpar marcadores da resposta original para caso precise usar
    cleaned_llm_response = clean_response_markers(llm_response)

    result = {
        "detected": False,
        "notification_sent": False,
        "action": "send_text",
        "response_text": cleaned_llm_response,  # Usar resposta limpa por padrão
        "reason": "",
        "cleaned_response": cleaned_llm_response
    }

    try:
        # Detectar se há contexto insuficiente
        # Passa a mensagem do cliente para verificar se é sobre agenda (não deve disparar)
        is_insufficient, reason = detect_insufficient_context(llm_response, customer_message)

        if not is_insufficient:
            # Mesmo que não detecte, retorna resposta limpa
            result["response_text"] = cleaned_llm_response
            return result

        result["detected"] = True
        result["reason"] = reason

        logger.info(f"[InsufficientContext] Contexto insuficiente detectado para {customer_phone}. Razão: {reason}")

        # Enviar notificação em background (não bloqueia a resposta)
        asyncio.create_task(
            send_insufficient_context_notification(
                customer_phone=customer_phone,
                customer_message=customer_message,
                llm_response=llm_response,
                customer_name=customer_name,
                detection_reason=reason,
                instance_id=instance_id
            )
        )
        result["notification_sent"] = True  # Marcamos como True pois foi agendada

        # Obter configuração de resposta ao cliente
        suppress_response, fallback_message = await get_customer_fallback_response(instance_id)

        if suppress_response:
            result["action"] = "suppress"
            result["response_text"] = ""
            logger.info(f"[InsufficientContext] Resposta ao cliente suprimida conforme configuração.")
        else:
            # Decidir se usa fallback configurado ou resposta do LLM limpa
            # Se o LLM deu uma resposta decente (sem apenas o marcador), usar ela
            if cleaned_llm_response and len(cleaned_llm_response) > 20:
                result["action"] = "send_text"
                result["response_text"] = cleaned_llm_response
                logger.info(f"[InsufficientContext] Usando resposta do LLM limpa (sem marcadores).")
            else:
                result["action"] = "send_text"
                result["response_text"] = fallback_message
                logger.info(f"[InsufficientContext] Usando mensagem de fallback configurada.")

        return result

    except Exception as e:
        logger.error(f"[InsufficientContext] Erro no handler: {e}", exc_info=True)
        # Em caso de erro, retorna a resposta limpa
        result["response_text"] = cleaned_llm_response
        return result


logger.info("insufficient_context_notifier: Módulo de notificação de contexto insuficiente carregado.")
