# -*- coding: utf-8 -*-
import re
import math
import random
import logging
from typing import List, Any, Optional

# Logger specific to this module
logger = logging.getLogger(__name__)

# --- Message Extraction ---
def extract_message_text(message_data: Any) -> Optional[dict]: # Return type changed to dict
    """
    Extracts the textual content or audio data from various Evolution API message types.
    Handles 'conversation', 'textMessage', 'extendedTextMessage', captions from media,
    and audio messages (base64 or URL).

    Args:
        message_data: The 'data' or 'message' object from the Evolution webhook.
                      It can be the direct 'data' field for 'messages.upsert'
                      or the 'message' field within that data.
    Returns:
        A dictionary like {"type": "text", "content": "..."} or 
        {"type": "audio", "content_type": "base64"|"url", "data": "...", "mimetype": "..."}
        or None if no processable content is found.
    """
    # logger.debug(f"[EXTRACT_MSG] Iniciando extração de conteúdo. Tipo de message_data: {type(message_data)}")
    if not message_data:
        logger.warning("[EXTRACT_MSG] message_data é None. Retornando None.")
        return None

    msg_content_obj = getattr(message_data, 'message', None)
    if not msg_content_obj:
        # logger.debug("[EXTRACT_MSG] 'message_data.message' é None. Verificando se message_data é o próprio objeto de conteúdo.")
        if hasattr(message_data, 'conversation') or \
           hasattr(message_data, 'textMessage') or \
           hasattr(message_data, 'extendedTextMessage') or \
           hasattr(message_data, 'imageMessage') or \
           hasattr(message_data, 'videoMessage') or \
           hasattr(message_data, 'audioMessage'): # Adicionado audioMessage aqui também
            msg_content_obj = message_data
            # logger.debug("[EXTRACT_MSG] message_data parece ser o objeto de conteúdo.")
        else:
            logger.warning(f"[EXTRACT_MSG] Não foi possível encontrar o objeto de conteúdo da mensagem em message_data (tipo: {type(message_data)}). Conteúdo (início): {str(message_data)[:200]}")
            return None
    
    # logger.debug(f"[EXTRACT_MSG] Objeto de conteúdo da mensagem (msg_content_obj) tipo: {type(msg_content_obj)}")

    # Prioridade para texto
    text_content = None
    if hasattr(msg_content_obj, 'conversation') and msg_content_obj.conversation:
        text_content = msg_content_obj.conversation
        # logger.info(f"[EXTRACT_MSG] Texto extraído de 'conversation': '{text_content[:70]}...'")
    elif hasattr(msg_content_obj, 'textMessage') and msg_content_obj.textMessage and hasattr(msg_content_obj.textMessage, 'text') and msg_content_obj.textMessage.text:
        text_content = msg_content_obj.textMessage.text
        logger.info(f"[EXTRACT_MSG] Texto extraído de 'textMessage.text': '{text_content[:70]}...'")
    elif hasattr(msg_content_obj, 'extendedTextMessage') and msg_content_obj.extendedTextMessage and hasattr(msg_content_obj.extendedTextMessage, 'text') and msg_content_obj.extendedTextMessage.text:
        text_content = msg_content_obj.extendedTextMessage.text
        # logger.info(f"[EXTRACT_MSG] Texto extraído de 'extendedTextMessage.text': '{text_content[:70]}...'")
    elif hasattr(msg_content_obj, 'imageMessage') and msg_content_obj.imageMessage and hasattr(msg_content_obj.imageMessage, 'caption') and msg_content_obj.imageMessage.caption:
        text_content = msg_content_obj.imageMessage.caption
        # logger.info(f"[EXTRACT_MSG] Legenda extraída de 'imageMessage.caption': '{text_content[:70]}...'")
    elif hasattr(msg_content_obj, 'videoMessage') and msg_content_obj.videoMessage and hasattr(msg_content_obj.videoMessage, 'caption') and msg_content_obj.videoMessage.caption:
        text_content = msg_content_obj.videoMessage.caption
        # logger.info(f"[EXTRACT_MSG] Legenda extraída de 'videoMessage.caption': '{text_content[:70]}...'")

    if text_content:
        # logger.info("[EXTRACT_MSG] Retornando conteúdo do tipo 'text'.")
        return {"type": "text", "content": text_content.strip()}

    # Checagem para áudio
    if hasattr(msg_content_obj, 'audioMessage') and msg_content_obj.audioMessage:
        audio_msg_details = msg_content_obj.audioMessage
        # logger.info("[EXTRACT_MSG] Mensagem de áudio detectada.")
        # logger.debug(f"[EXTRACT_MSG] Detalhes do audioMessage: {audio_msg_details}")

        audio_mimetype = getattr(audio_msg_details, 'mimetype', 'audio/ogg') # Padrão para ogg
        audio_mimetype = getattr(audio_msg_details, 'mimetype', 'audio/ogg') # Standard for ogg
        # logger.debug(f"[EXTRACT_MSG] Mimetype do áudio: {audio_mimetype}")

        # Checa por base64 primeiro, pois pode estar em audioMessage ou no nível de message
        # O briefing indica que o código atual prioriza base64 no nível de WebhookMessageContent (msg_content_obj aqui)
        
        # Cenário 1: Base64 no nível de WebhookMessageContent (msg_content_obj)
        if hasattr(msg_content_obj, 'base64') and msg_content_obj.base64:
            # logger.info("[EXTRACT_MSG] Áudio Base64 encontrado no nível de 'message' (WebhookMessageContent).")
            # logger.debug(f"[EXTRACT_MSG] Base64 (início): {msg_content_obj.base64[:60]}...")
            return {"type": "audio", "content_type": "base64", "data": msg_content_obj.base64, "mimetype": audio_mimetype}
        
        # Cenário 2: Base64 dentro de audioMessage
        if hasattr(audio_msg_details, 'base64') and audio_msg_details.base64:
            # logger.info("[EXTRACT_MSG] Áudio Base64 encontrado dentro de 'audioMessage'.")
            # logger.debug(f"[EXTRACT_MSG] Base64 (início): {audio_msg_details.base64[:60]}...")
            return {"type": "audio", "content_type": "base64", "data": audio_msg_details.base64, "mimetype": audio_mimetype}
        
        # Cenário 3: URL dentro de audioMessage
        if hasattr(audio_msg_details, 'url') and audio_msg_details.url:
            # logger.info(f"[EXTRACT_MSG] URL de áudio encontrada em 'audioMessage.url': {audio_msg_details.url}")
            return {"type": "audio", "content_type": "url", "data": audio_msg_details.url, "mimetype": audio_mimetype}
        
        logger.warning("[EXTRACT_MSG] audioMessage presente, mas sem 'base64' (em 'message' ou 'audioMessage') ou 'url' utilizável.")
        return None # Ou um tipo específico de erro/aviso se preferir

    # logger.info("[EXTRACT_MSG] Nenhum conteúdo textual direto ou mensagem de áudio processável encontrada nos campos conhecidos.")
    return None

# --- Constants for Message Splitting and Delay ---
MAX_SEGMENT_LENGTH = 10000
# Delays ajustados para parecer mais humanizado (simula tempo real de digitação/leitura)
MIN_DELAY_MS = 2000       # Mínimo 2 segundos entre mensagens
MS_PER_CHAR = 30          # 30ms por caractere (simula leitura + digitação)          

def split_message(text: str, max_length: int = 4000) -> List[str]:
    """
    Divide o texto APENAS se exceder o limite do WhatsApp (~4096 chars).
    Cada resposta do chatbot deve ser UMA mensagem — sem fragmentar por pontuação.
    """
    if not text or not isinstance(text, str):
        return []

    text = text.strip()

    # Se cabe em uma mensagem, enviar como está
    if len(text) <= max_length:
        return [text]

    # Só dividir se realmente exceder o limite
    segments = []
    while text:
        if len(text) <= max_length:
            segments.append(text)
            break
        # Encontrar ponto de quebra (parágrafo ou frase)
        cut = text.rfind('\n\n', 0, max_length)
        if cut < max_length // 2:
            cut = text.rfind('\n', 0, max_length)
        if cut < max_length // 2:
            cut = text.rfind('. ', 0, max_length)
        if cut < max_length // 2:
            cut = max_length
        segments.append(text[:cut + 1].strip())
        text = text[cut + 1:].strip()

    return [s for s in segments if s]

def calculate_delay(text_segment: str) -> int:
    """
    Calcula delay humanizado entre mensagens baseado na quantidade de caracteres.
    Simula tempo de leitura + digitação de uma pessoa real.
    Sem limite máximo - o delay é proporcional ao tamanho da mensagem.

    Args:
        text_segment: Texto do segmento para calcular delay

    Returns:
        Delay em milissegundos (int)
    """
    if not text_segment or not isinstance(text_segment, str):
        return MIN_DELAY_MS

    char_count = len(text_segment)

    # Base: mínimo + tempo por caractere (sem limite máximo)
    calculated_delay = MIN_DELAY_MS + (char_count * MS_PER_CHAR)

    # Jitter de 25% para variação mais natural (humanos não são consistentes)
    jitter = calculated_delay * 0.25
    final_delay = random.uniform(calculated_delay - jitter, calculated_delay + jitter)

    # Adiciona pausa aleatória extra ocasional (simula "pensar" antes de responder)
    # 30% de chance de adicionar 500-1500ms extras
    if random.random() < 0.30:
        extra_pause = random.randint(500, 1500)
        final_delay += extra_pause
        logger.debug(f"[CALC_DELAY] Pausa extra humanizada adicionada: +{extra_pause}ms")

    # Apenas garante o mínimo, sem limite máximo
    final_delay = max(MIN_DELAY_MS, final_delay)

    logger.debug(f"[CALC_DELAY] Segmento ({char_count} caracteres) -> Delay humanizado: {int(final_delay)}ms")
    return int(final_delay)

logger.info("Módulo message_utils.py carregado e logs configurados.")
