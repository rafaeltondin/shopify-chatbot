# -*- coding: utf-8 -*-
"""
Message handling simplificado para chatbot de atendimento e-commerce.
Fluxo: Receber mensagem → LLM com contexto Shopify → Responder.
Sem funil de vendas, sem estágios, sem prospecção ativa.
"""
import logging
import asyncio
import json
import re
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
import httpx
import pytz

from src.core.config import settings, logger
from src.core.shopify import (
    search_products_for_chat,
    get_order_status_for_chat,
    get_customer_orders_for_chat,
    get_order_tracking_for_chat,
    get_all_customer_orders_for_chat,
    generate_checkout_link,
    get_shopify_client,
    get_customer_context_for_llm,
    get_popular_products_for_chat,
    check_stock_for_chat,
    get_store_policies_for_chat,
    recommend_products_for_chat,
    verify_customer_for_chat,
    get_shop_info_for_chat,
)
from src.core.prospect_management.state import (
    ProspectState, get_prospect, add_prospect_state,
    add_message_to_history_state, save_prospect,
)
from src.core.db_operations import prospect_crud
from src.core import llm, evolution
from src.core.wallet_manager import debit_llm_token_usage
from src.utils import formatting, message_utils, audio_utils
from src.utils.llm_utils import TaskType
from pathlib import Path

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Cache de contexto do cliente — Redis com fallback em memória
# ─────────────────────────────────────────────
import time as _time

# Fallback em memória (usado quando Redis não está disponível)
_customer_context_cache: Dict[str, Tuple[str, float]] = {}  # jid → (context_str, timestamp)
_customer_interests: Dict[str, List[str]] = {}  # jid → [interesses detectados]
_verified_customers: Dict[str, float] = {}  # jid → timestamp da verificação
CONTEXT_CACHE_TTL = 600  # 10 minutos
VERIFICATION_TTL = 1800  # 30 minutos — após verificar, não pede de novo por 30min

# Regex para detectar email e número de pedido nas mensagens
_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
_ORDER_RE = re.compile(r'#?\s*(\d{3,6})\b')  # #1001 ou 1001


def _extract_verification_data(text: str) -> dict:
    """Extrai email e/ou número de pedido de uma mensagem de texto."""
    data = {}
    email_match = _EMAIL_RE.search(text)
    if email_match:
        data['email'] = email_match.group(0)
    order_match = _ORDER_RE.search(text)
    if order_match:
        num = order_match.group(1)
        # Ignorar anos (4 dígitos acima de 2000) e números muito curtos
        if 100 <= int(num) <= 99999:
            data['order_number'] = f'#{num}'
    return data


async def _redis_get(key: str) -> Optional[str]:
    """Busca valor no Redis. Retorna None se ausente ou Redis indisponível."""
    try:
        redis = settings.redis_client
        if redis:
            return await redis.get(key)
    except Exception:
        pass
    return None


async def _redis_set(key: str, value: str, ttl: int) -> None:
    """Salva valor no Redis com TTL. Silencia erros (Redis opcional)."""
    try:
        redis = settings.redis_client
        if redis:
            await redis.setex(key, ttl, value)
    except Exception:
        pass


async def _redis_delete(key: str) -> None:
    """Remove chave do Redis. Silencia erros."""
    try:
        redis = settings.redis_client
        if redis:
            await redis.delete(key)
    except Exception:
        pass


def _is_customer_verified(phone: str) -> bool:
    """Verifica se o cliente já foi verificado recentemente (30min)."""
    if phone in _verified_customers:
        elapsed = _time.monotonic() - _verified_customers[phone]
        return elapsed < VERIFICATION_TTL
    return False


def _mark_customer_verified(phone: str):
    """Marca cliente como verificado."""
    _verified_customers[phone] = _time.monotonic()


async def _get_cached_customer_context(phone: str) -> str:
    """
    Busca contexto do cliente com cache de 10 minutos.
    Estratégia: Redis → memória → Shopify API.
    """
    redis_key = f"chatbot:ctx:{phone}"

    # 1. Tentar Redis
    cached_raw = await _redis_get(redis_key)
    if cached_raw:
        try:
            data = json.loads(cached_raw)
            interests = data.get("interests", [])
            # Atualizar interesses em memória se necessário
            if interests:
                _customer_interests[phone] = interests
            return data.get("context", "")
        except Exception:
            pass

    # 2. Fallback: cache em memória
    now = _time.monotonic()
    if phone in _customer_context_cache:
        cached_context, cached_at = _customer_context_cache[phone]
        if (now - cached_at) < CONTEXT_CACHE_TTL:
            return cached_context

    # 3. Buscar na Shopify
    interests = _customer_interests.get(phone, [])
    context = await get_customer_context_for_llm(phone, interests)

    # Salvar em Redis e memória
    payload = json.dumps({"context": context, "interests": interests}, ensure_ascii=False)
    await _redis_set(redis_key, payload, CONTEXT_CACHE_TTL)
    _customer_context_cache[phone] = (context, now)

    return context


def _track_customer_interests(phone: str, interests: List[str]):
    """Adiciona interesses detectados pelo LLM ao tracking do cliente."""
    if not interests:
        return
    existing = _customer_interests.get(phone, [])
    for interest in interests:
        if interest and interest not in existing:
            existing.append(interest)
    # Manter no máximo 20 interesses
    _customer_interests[phone] = existing[-20:]


def _invalidate_customer_cache(phone: str):
    """Invalida cache do cliente (chamado após ações que mudam o estado, ex: compra)."""
    _customer_context_cache.pop(phone, None)
    # Invalidar no Redis de forma assíncrona (fire-and-forget via task)
    import asyncio
    try:
        asyncio.create_task(_redis_delete(f"chatbot:ctx:{phone}"))
    except RuntimeError:
        pass  # Sem event loop ativo (contexto de teste)


# ─────────────────────────────────────────────
# Validação de pushName
# ─────────────────────────────────────────────
def _validate_push_name(push_name: str, phone_number: str = None) -> Optional[str]:
    """Valida se um pushName do WhatsApp parece ser um nome de pessoa válido."""
    if not push_name or not isinstance(push_name, str):
        return None

    name = push_name.strip()
    if len(name) < 2 or len(name) > 50:
        return None
    if name.replace(" ", "").isdigit():
        return None

    invalid_patterns = [
        "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite",
        "sim", "não", "nao", "ok", "okay", "quero", "preciso",
        "obrigado", "obrigada", "valeu",
    ]
    if name.lower() in invalid_patterns:
        return None

    starts_invalid = ["oi ", "olá ", "bom ", "boa ", "quero ", "preciso ", "quanto "]
    if any(name.lower().startswith(p) for p in starts_invalid):
        return None

    letter_count = sum(1 for c in name if c.isalpha())
    if letter_count < 2:
        return None

    return name


# ─────────────────────────────────────────────
# Limpeza de histórico para LLM
# ─────────────────────────────────────────────
def _clean_history_for_llm(raw_history: List[Dict[str, Any]], phone_number: str) -> List[Dict[str, str]]:
    """Limpa e formata o histórico para envio ao LLM."""
    if not raw_history:
        return []

    cleaned = []
    skip_patterns = ["[ERROR]", "[WAIT_LLM]", "[AUDIO:", "[Falha na transcrição", "[SYSTEM]"]

    for item in raw_history:
        role = item.get("role", "").strip()
        content = item.get("content", "").strip()

        if not role or not content:
            continue
        if role == "system":
            continue
        if any(p in content for p in skip_patterns):
            continue
        if role not in ["user", "assistant"]:
            continue

        content = " ".join(content.split())
        if len(content) > 2000:
            content = content[:1900] + "..."

        cleaned.append({"role": role, "content": content})

    # Manter apenas as últimas 30 mensagens
    if len(cleaned) > 30:
        cleaned = cleaned[-30:]

    return cleaned


# ─────────────────────────────────────────────
# Buffer de mensagens (agrupa msgs rápidas)
# ─────────────────────────────────────────────
_message_buffer_timers: Dict[str, asyncio.TimerHandle] = {}
_message_buffer_pending: Dict[str, Tuple[str, str, str]] = {}
_message_buffer_lock: asyncio.Lock = asyncio.Lock()
BUFFER_SECONDS = getattr(settings, "MESSAGE_BUFFER_SECONDS", 15)
MESSAGE_PROCESSING_TIMEOUT = getattr(settings, "MESSAGE_PROCESSING_TIMEOUT", 120)

incoming_message_queue: asyncio.Queue = asyncio.Queue()
is_processing_messages: bool = False
message_processor_task: Optional[asyncio.Task] = None

AUDIO_FALLBACK_MESSAGE = """Desculpe, não consegui processar seu áudio. 😔

Por favor, tente:
• Enviar o áudio novamente
• Ou envie sua mensagem por texto

Estou aqui para ajudar! 🙂"""


# ─────────────────────────────────────────────
# Entrada principal de mensagens
# ─────────────────────────────────────────────
async def handle_incoming_message_logic(message_data: Any, instance_id: str):
    """Processa mensagem recebida do webhook da Evolution API."""
    try:
        push_name = None
        if hasattr(message_data, 'model_dump'):
            all_fields = message_data.model_dump()
            push_name = all_fields.get('pushName')

        key_from_me = getattr(message_data.key, 'fromMe', False) if hasattr(message_data, 'key') else False
        top_level_from_me = getattr(message_data, 'fromMe', False)

        if not hasattr(message_data, 'key') or not hasattr(message_data.key, 'remoteJid') or key_from_me or top_level_from_me:
            return

        # Resolver LID (Evolution API v2)
        raw_jid = message_data.key.remoteJid
        if raw_jid and raw_jid.endswith('@lid'):
            remote_jid_alt = getattr(message_data.key, 'remoteJidAlt', None)
            if remote_jid_alt and not remote_jid_alt.endswith('@lid'):
                raw_jid = remote_jid_alt
            else:
                logger.warning(f"[MSG_HANDLER] LID detectado ({raw_jid}) sem remoteJidAlt disponível")

        phone_number = formatting.clean_phone_number(raw_jid)
        if not phone_number:
            return

        # Extrair conteúdo da mensagem
        extracted = message_utils.extract_message_text(message_data)
        if not extracted:
            return

        message_for_processing = None

        if extracted["type"] == "text":
            message_for_processing = extracted["content"]

        elif extracted["type"] == "audio":
            import time
            audio_start = time.monotonic()
            audio_data = extracted["data"]
            audio_mimetype = extracted.get("mimetype", "audio/ogg")

            if extracted["content_type"] == "url":
                message_key = None
                if hasattr(message_data, 'key'):
                    key_obj = message_data.key
                    message_key = {
                        "remoteJid": raw_jid,
                        "fromMe": getattr(key_obj, 'fromMe', False),
                        "id": getattr(key_obj, 'id', None),
                    }

                if message_key and message_key.get("id"):
                    media_response = await evolution.get_base64_from_media_message(message_key, instance_name=instance_id)
                    if media_response and media_response.get("base64"):
                        audio_data = media_response["base64"]
                        audio_mimetype = media_response.get("mimetype", audio_mimetype)
                        transcribed_text = await audio_utils.transcribe_audio_from_base64(audio_data, audio_mimetype)
                    else:
                        await _send_text_message(phone_number, AUDIO_FALLBACK_MESSAGE)
                        return
                else:
                    await _send_text_message(phone_number, AUDIO_FALLBACK_MESSAGE)
                    return
            else:
                transcribed_text = await audio_utils.transcribe_audio_from_base64(audio_data, audio_mimetype)

            if transcribed_text and not transcribed_text.startswith("[Erro"):
                message_for_processing = transcribed_text
            else:
                await _send_text_message(phone_number, AUDIO_FALLBACK_MESSAGE)
                return

        if message_for_processing:
            await incoming_message_queue.put((phone_number, message_for_processing, instance_id, push_name))
            start_message_processor()

    except Exception as e:
        logger.error(f"[MSG_HANDLER] Erro crítico: {e}", exc_info=True)


def start_message_processor():
    global message_processor_task, is_processing_messages
    if not is_processing_messages:
        is_processing_messages = True
        message_processor_task = asyncio.create_task(_message_processor_loop())


async def stop_message_processor():
    global is_processing_messages, message_processor_task
    is_processing_messages = False
    if message_processor_task:
        message_processor_task.cancel()
        try:
            await message_processor_task
        except asyncio.CancelledError:
            pass
        message_processor_task = None


async def _message_processor_loop():
    while is_processing_messages:
        try:
            phone_number, new_text, instance_id, push_name = await asyncio.wait_for(
                incoming_message_queue.get(), timeout=1.0
            )

            async with _message_buffer_lock:
                if phone_number in _message_buffer_pending:
                    existing_text, existing_instance, existing_push = _message_buffer_pending[phone_number]
                    _message_buffer_pending[phone_number] = (
                        f"{existing_text}\n{new_text}",
                        existing_instance,
                        existing_push or push_name,
                    )
                else:
                    _message_buffer_pending[phone_number] = (new_text, instance_id, push_name)

                timer = _message_buffer_timers.pop(phone_number, None)
                if timer:
                    timer.cancel()

                loop = asyncio.get_running_loop()
                _message_buffer_timers[phone_number] = loop.call_later(
                    BUFFER_SECONDS,
                    lambda pn=phone_number: asyncio.create_task(_process_buffered_message(pn)),
                )

            incoming_message_queue.task_done()
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break


async def _process_buffered_message(phone_number: str):
    message_text = None
    instance_id = None
    push_name = None

    async with _message_buffer_lock:
        if phone_number in _message_buffer_pending:
            message_text, instance_id, push_name = _message_buffer_pending.pop(phone_number)
            _message_buffer_timers.pop(phone_number, None)

    if message_text:
        try:
            await asyncio.wait_for(
                _process_message(phone_number, message_text, instance_id, push_name),
                timeout=MESSAGE_PROCESSING_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(f"[{phone_number}] TIMEOUT no processamento ({MESSAGE_PROCESSING_TIMEOUT}s)")


# ─────────────────────────────────────────────
# Processamento principal da mensagem
# ─────────────────────────────────────────────
async def _process_message(phone_number: str, message_text: str, instance_id: str, push_name: str = None):
    """
    Fluxo personalizado:
    1. Buscar/criar prospect (cliente)
    2. Salvar mensagem no histórico
    3. Enriquecer com dados da Shopify (perfil, pedidos, interesses)
    4. Chamar LLM com contexto rico
    5. Executar ação + salvar interesses detectados
    """
    effective_instance_id = settings.INSTANCE_ID
    validated_push_name = _validate_push_name(push_name, phone_number)

    try:
        # 1. Buscar ou criar cliente
        prospect = await get_prospect(phone_number)
        if not prospect:
            prospect = await add_prospect_state(
                phone_number,
                initial_stage=1,
                conversation_initiator='user',
                instance_id=effective_instance_id,
                name=validated_push_name,
            )
        elif validated_push_name and not prospect.name:
            prospect.name = validated_push_name
            await save_prospect(prospect)
            await prospect_crud.add_or_update_prospect_db(
                jid=phone_number,
                instance_id=effective_instance_id,
                name=validated_push_name,
            )

        if not prospect:
            logger.error(f"[{phone_number}] Falha ao obter/criar prospect")
            return

        # 2. Salvar mensagem do cliente no histórico
        await add_message_to_history_state(phone_number, "user", message_text, conversation_initiator_override='user')
        prospect.history.append({"role": "user", "content": message_text})

        # 3. Verificar se LLM está pausado
        if prospect.llm_paused:
            logger.info(f"[{phone_number}] LLM pausado para este cliente")
            return

        # 4. Enriquecer com perfil Shopify (cached, 10min TTL)
        logger.info(f"[{phone_number}] Buscando contexto personalizado do cliente...")
        customer_context = await _get_cached_customer_context(phone_number)

        # 5. Montar histórico com contexto injetado
        # O contexto do cliente vai como primeira mensagem de sistema,
        # para que o LLM personalize a resposta com os dados reais
        enriched_messages = [
            {"role": "system", "content": customer_context},
        ] + prospect.history

        # ── INTERCEPTAÇÃO DE VERIFICAÇÃO DE IDENTIDADE ──────────────────────────
        # Se o cliente não está verificado E a mensagem contém email ou número de pedido,
        # não chamar o LLM — processar verify_identity diretamente.
        if not _is_customer_verified(phone_number):
            last_user_msg = ""
            for msg in reversed(prospect.history):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "")
                    break
            verif_data = _extract_verification_data(last_user_msg)
            if verif_data:
                logger.info(f"[{phone_number}] INTERCEPTAÇÃO: dados de verificação detectados na mensagem, chamando verify_identity diretamente. Dados: {verif_data}")
                fake_action = {"action": "verify_identity", "arguments": verif_data}
                await _handle_verify_identity(fake_action, prospect)
                if _is_customer_verified(phone_number):
                    order_number = verif_data.get("order_number", "")
                    logger.info(f"[{phone_number}] Verificacao OK - consultando pedido automaticamente")
                    chk = {"action": "check_order_status", "arguments": {"order_number": order_number} if order_number else {}}
                    await _handle_check_order(chk, prospect)
                return
        # ── FIM DA INTERCEPTAÇÃO ─────────────────────────────────────────────

        logger.info(f"[{phone_number}] Chamando LLM com {len(prospect.history)} msgs + contexto Shopify")

        llm_response = await llm.get_llm_response(
            messages=enriched_messages,
            task_type=TaskType.CONVERSATION,
            chat_id=prospect.jid,
            current_stage_definition={"objective": "Atendimento personalizado ao cliente - usar dados do perfil para personalizar respostas, buscar produtos, consultar pedidos"},
            next_stage_definition=None,
            prospect_name=prospect.name,
            prospect_jid=prospect.jid,
            conversation_initiator=prospect.conversation_initiator,
            instance_id=prospect.instance_id,
        )

        if not llm_response or not llm_response.get("action_data"):
            await _send_text_message(phone_number, "Desculpe, não consegui processar sua mensagem. Pode tentar novamente?")
            return

        # 6. Processar resposta + salvar interesses detectados
        await _process_llm_response(prospect, llm_response)

    except Exception as e:
        logger.error(f"[{phone_number}] Erro no processamento: {e}", exc_info=True)


async def _process_llm_response(prospect: ProspectState, response: Dict[str, Any]):
    """Processa a resposta do LLM e executa a ação correspondente."""
    phone_number = prospect.jid
    action_data = response.get("action_data", {})
    token_usage = response.get("token_usage", {})
    action = action_data.get("action", "send_text")

    logger.info(f"[{phone_number}] Ação do LLM: {action}")

    # Coletar dados do cliente e interesses se disponíveis
    if "collected_data" in action_data and isinstance(action_data["collected_data"], dict):
        collected = action_data["collected_data"]
        updated = False

        if collected.get("name") and not prospect.name:
            prospect.name = collected["name"].strip()
            updated = True
        if collected.get("email") and not getattr(prospect, 'email', None):
            prospect.email = collected["email"].strip()
            updated = True

        # Salvar interesses detectados pelo LLM
        detected_interests = collected.get("interests", [])
        if isinstance(detected_interests, list) and detected_interests:
            _track_customer_interests(phone_number, detected_interests)
            logger.info(f"[{phone_number}] Interesses detectados: {detected_interests}")

        if updated:
            await save_prospect(prospect)
            await prospect_crud.add_or_update_prospect_db(
                jid=prospect.jid, instance_id=prospect.instance_id,
                name=prospect.name, email=getattr(prospect, 'email', None),
            )
            # Invalidar cache do contexto (dados mudaram)
            _invalidate_customer_cache(phone_number)

    # Debitar tokens
    if token_usage.get("total_tokens", 0) > 0:
        await debit_llm_token_usage(
            instance_id=settings.INSTANCE_ID,
            total_tokens_used=token_usage["total_tokens"],
            llm_model_name=token_usage.get("model", "N/A"),
            prospect_jid=prospect.jid,
        )

    # Ferramentas que executam ações — NÃO enviar o campo "text" do LLM
    # (senão manda "vou buscar pra você" + os resultados = duplicação)
    tool_actions = {
        "search_products": _handle_search_products,
        "check_order_status": _handle_check_order,
        "get_my_orders": _handle_get_my_orders,
        "get_order_tracking": _handle_get_order_tracking,
        "verify_identity": _handle_verify_identity,
        "send_checkout_link": _handle_checkout_link,
        "get_popular_products": _handle_popular_products,
        "recommend_products": _handle_recommend_products,
        "check_stock": _handle_check_stock,
        "get_store_policies": _handle_store_policies,
        "get_business_hours": _handle_business_hours,
        "get_shop_info": _handle_shop_info,
    }

    if action in tool_actions:
        # Executar ferramenta diretamente — sem enviar texto prévio
        await tool_actions[action](action_data, prospect)

    elif action == "send_text":
        text = action_data.get("text", "").strip()
        if text:
            await _send_text_message(phone_number, text, token_usage, prospect.conversation_initiator)
        else:
            await _send_text_message(phone_number, "Entendido! Como posso ajudar?")

    elif action == "collect_user_data":
        text = action_data.get("text", "Para te ajudar melhor, preciso de algumas informações.").strip()
        await _send_text_message(phone_number, text, token_usage, prospect.conversation_initiator)

    elif action == "wait":
        await add_message_to_history_state(
            phone_number, "system",
            f"[WAIT] {action_data.get('reason', 'Aguardando')}",
            conversation_initiator_override=prospect.conversation_initiator,
        )

    else:
        text = action_data.get("text", "").strip()
        if text:
            await _send_text_message(phone_number, text, token_usage, prospect.conversation_initiator)


# ─────────────────────────────────────────────
# Ações Shopify
# ─────────────────────────────────────────────
async def _handle_search_products(action_data: Dict, prospect: ProspectState):
    """Busca produtos na Shopify e envia ao cliente — formato natural, humanizado."""
    import random
    import re
    args = action_data.get("arguments", {})
    query = args.get("query", args.get("search_term", ""))

    if not query:
        fallbacks = [
            "O que você tá procurando? Me conta que eu busco!",
            "Me fala o que precisa que eu dou uma olhada no catálogo!",
            "Pode me dizer o que você quer? Busco aqui pra você!",
        ]
        await _send_text_message(prospect.jid, random.choice(fallbacks))
        return

    products = await search_products_for_chat(query, limit=5)

    if not products:
        fallbacks = [
            f"Não encontrei nada com \"{query}\" 😕 Tenta descrever de outro jeito?",
            f"Hmm, não achei resultados pra \"{query}\". Quer tentar com outros termos?",
            f"Poxa, não encontrei \"{query}\" no catálogo. Me descreve melhor o que você procura?",
        ]
        await _send_text_message(prospect.jid, random.choice(fallbacks))
        return

    client = get_shopify_client()
    if not client:
        return

    # Formato natural: nome + preço + tamanhos/cores + descrição (para poucos produtos)
    lines = []
    single_product = len(products) == 1

    for i, product in enumerate(products[:5], 1):
        title = product.get("title", "")
        price_range = product.get("priceRangeV2", {})
        price = price_range.get("minVariantPrice", {}).get("amount", "0")
        inventory = product.get("totalInventory", 0)
        url = product.get("onlineStoreUrl", "")

        # Descrição limpa (remover HTML)
        description = product.get("description", "") or ""
        if not description:
            desc_html = product.get("descriptionHtml", "") or ""
            description = re.sub(r'<[^>]+>', ' ', desc_html).strip()
        # Limitar descrição
        if len(description) > 300:
            description = description[:297].rsplit(' ', 1)[0] + "..."

        # Extrair tamanhos e cores separadamente
        variants = product.get("variants", {}).get("edges", [])
        sizes = set()
        colors = set()
        if variants and len(variants) > 1:
            for v in variants:
                node = v["node"]
                if not node.get("availableForSale"):
                    continue
                for opt in node.get("selectedOptions", []):
                    name_lower = opt.get("name", "").lower()
                    if name_lower in ("tamanho", "size"):
                        sizes.add(opt["value"])
                    elif name_lower in ("cor", "color"):
                        colors.add(opt["value"])

        status = "✅ Disponível" if inventory > 0 else "❌ Esgotado"

        if single_product:
            lines.append(f"*{title}*")
            lines.append(f"R$ {float(price):.2f} — {status}")
        else:
            lines.append(f"*{i}. {title}*")
            lines.append(f"   R$ {float(price):.2f} — {status}")

        # Mostrar tamanhos e cores de forma natural (só disponíveis)
        if sizes:
            sorted_sizes = sorted(sizes, key=lambda x: (not x.replace("/", "").isdigit(), x))
            prefix = "   " if not single_product else ""
            lines.append(f"{prefix}Tamanhos: {', '.join(sorted_sizes)}")
        if colors:
            prefix = "   " if not single_product else ""
            lines.append(f"{prefix}Cores: {', '.join(sorted(colors))}")

        # Descrição do produto (só para 1-2 produtos)
        if description and len(products) <= 2:
            lines.append("")
            lines.append(f"📋 {description}")

        # URL só na primeira vez, e só se for produto único ou poucos resultados
        if url and (single_product or len(products) <= 2):
            lines.append(f"\n{url}")
        lines.append("")

    # Fechamento variado e natural
    if single_product:
        closings = [
            "Ficou com alguma dúvida? É só perguntar! 😊",
            "Curtiu? Qualquer dúvida é só mandar!",
            "Quer ver tamanhos e cores disponíveis?",
        ]
    else:
        closings = [
            "Algum te interessou? 😊",
            "Curtiu algum? Me avisa que mando mais detalhes!",
            "Quer saber mais sobre algum desses?",
            "Qual chamou sua atenção?",
        ]
    lines.append(random.choice(closings))

    # Enviar mensagem ao cliente
    await _send_text_message(prospect.jid, "\n".join(lines))

    # Salvar contexto dos produtos no histórico para o LLM usar em follow-ups
    if True:  # Sempre salvar contexto
        context_parts = []
        for product in products[:5]:
            p_title = product.get("title", "")
            p_desc = product.get("description", "") or ""
            p_url = product.get("onlineStoreUrl", "")
            p_type = product.get("productType", "")
            p_tags = product.get("tags", [])
            context_parts.append(
                f"[PRODUTO: {p_title} | Tipo: {p_type} | Tags: {', '.join(p_tags) if isinstance(p_tags, list) else p_tags} | "
                f"Descrição: {p_desc[:500]} | URL: {p_url}]"
            )
        context_msg = "[CONTEXTO_PRODUTO] " + " ".join(context_parts)
        await add_message_to_history_state(
            prospect.jid, "system", context_msg,
            conversation_initiator_override=prospect.conversation_initiator,
        )


async def _handle_check_order(action_data: Dict, prospect: ProspectState):
    """Consulta status de pedido — EXIGE verificação de identidade."""
    phone = prospect.jid

    # SEGURANÇA: Exigir verificação antes de mostrar dados de pedido
    if not _is_customer_verified(phone):
        await _send_text_message(
            phone,
            "Para sua seguranca, preciso confirmar sua identidade antes de compartilhar dados do pedido.\n\n"
            "Me informe uma dessas informacoes:\n"
            "- Seu *email* cadastrado\n"
            "- O *numero do pedido* (ex: #1001)",
        )
        await add_message_to_history_state(
            phone, "system",
            "[SECURITY] Verificacao de identidade solicitada para consulta de pedido",
            conversation_initiator_override=prospect.conversation_initiator,
        )
        return

    args = action_data.get("arguments", {})
    order_number = args.get("order_number", args.get("order_name", ""))

    if order_number:
        logger.info(f"[{phone}] Consultando pedido: {order_number}")
        order_text = await get_order_status_for_chat(order_number)
        if order_text:
            await _send_text_message(phone, order_text)
        else:
            await _send_text_message(phone, f"Nao encontrei o pedido {order_number}. Confere o numero e tenta de novo?")
    else:
        logger.info(f"[{phone}] Buscando pedidos pelo telefone")
        orders_text = await get_customer_orders_for_chat(phone, limit=3)
        if orders_text:
            await _send_text_message(phone, f"Encontrei {len(orders_text)} pedido(s) recente(s):")
            for msg in orders_text:
                await asyncio.sleep(1)
                await _send_text_message(phone, msg)
        else:
            await _send_text_message(phone, "Nao encontrei pedidos associados ao seu numero. Pode me informar o numero do pedido? (ex: #1001)")



async def _handle_get_my_orders(action_data: Dict, prospect: ProspectState):
    phone = prospect.jid
    if not _is_customer_verified(phone):
        msg = ("Para sua seguranca, confirme sua identidade antes de ver seus pedidos." + chr(10) +
               "Me informe: *email* cadastrado ou *numero do pedido* (ex: #1001)")
        await _send_text_message(phone, msg)
        await add_message_to_history_state(phone, "system", "[SECURITY] Verificacao para pedidos", conversation_initiator_override=prospect.conversation_initiator)
        return
    limit = int(action_data.get("arguments", {}).get("limit", 5))
    summary = await get_all_customer_orders_for_chat(phone, limit=limit)
    if summary:
        await _send_text_message(phone, summary)
        await add_message_to_history_state(phone, "system", f"[SHOPIFY] Pedidos enviados ({limit})", conversation_initiator_override=prospect.conversation_initiator)
    else:
        await _send_text_message(phone, "Nao encontrei pedidos no seu numero. Me informe o numero do pedido (ex: #1001)!")



async def _handle_get_order_tracking(action_data: Dict, prospect: ProspectState):
    phone = prospect.jid
    if not _is_customer_verified(phone):
        msg = ("Para sua seguranca, confirme sua identidade antes de ver o rastreio." + chr(10) +
               "Me informe: *email* cadastrado ou *numero do pedido* (ex: #1001)")
        await _send_text_message(phone, msg)
        await add_message_to_history_state(phone, "system", "[SECURITY] Verificacao para rastreio", conversation_initiator_override=prospect.conversation_initiator)
        return
    order_number = action_data.get("arguments", {}).get("order_number", action_data.get("arguments", {}).get("order_name", "")).strip()
    if not order_number:
        await _send_text_message(phone, "Qual o numero do pedido? Ex: *#1001*")
        return
    tracking_text = await get_order_tracking_for_chat(order_number)
    if tracking_text:
        await _send_text_message(phone, tracking_text)
        await add_message_to_history_state(phone, "system", f"[SHOPIFY] Rastreio {order_number} enviado", conversation_initiator_override=prospect.conversation_initiator)
    else:
        await _send_text_message(phone, f"Nao encontrei o pedido *{order_number}*. Confere o numero!")



async def _handle_checkout_link(action_data: Dict, prospect: ProspectState):
    """Gera e envia link de checkout direto."""
    args = action_data.get("arguments", {})
    variant_id = args.get("variant_id", "")
    quantity = args.get("quantity", 1)

    if not variant_id:
        await _send_text_message(prospect.jid, "Qual produto você quer comprar? Me diz que eu gero o link! 🛒")
        return

    checkout_url = await generate_checkout_link(variant_id, quantity)
    if checkout_url:
        await _send_text_message(
            prospect.jid,
            f"Aqui está o link para finalizar sua compra! 🛒\n\n🔗 {checkout_url}\n\nÉ só clicar e seguir os passos!",
        )
    else:
        await _send_text_message(prospect.jid, "Não consegui gerar o link agora. Tenta de novo em instantes!")


# ─────────────────────────────────────────────
# Verificação de identidade
# ─────────────────────────────────────────────
async def _handle_verify_identity(action_data: Dict, prospect: ProspectState):
    """Verifica identidade do cliente antes de compartilhar dados sensíveis."""
    args = action_data.get("arguments", {})
    phone = prospect.jid

    # Se já verificado nos últimos 30min, pular
    if _is_customer_verified(phone):
        await _send_text_message(phone, "Identidade já verificada! Como posso ajudar?")
        return

    verification_data = {}
    if args.get("email"):
        verification_data["email"] = args["email"]
    if args.get("order_number"):
        verification_data["order_number"] = args["order_number"]
    if args.get("name"):
        verification_data["name"] = args["name"]

    if not verification_data:
        await _send_text_message(
            phone,
            "Para sua seguranca, preciso verificar sua identidade.\n\n"
            "Por favor, me informe uma dessas informacoes:\n"
            "- Seu *email* cadastrado na loja\n"
            "- O *numero do pedido* (ex: #1001)\n"
            "- Seu *nome completo* cadastrado",
        )
        return

    result = await verify_customer_for_chat(phone, verification_data)

    if result.get("verified"):
        _mark_customer_verified(phone)
        _invalidate_customer_cache(phone)  # Recarregar contexto completo
        await _send_text_message(phone, f"Identidade verificada! {result.get('message', '')} Agora posso te ajudar com seus pedidos.")
        await add_message_to_history_state(
            phone, "system",
            f"[SECURITY] Identidade verificada via {result.get('match_type')}",
            conversation_initiator_override=prospect.conversation_initiator,
        )
    else:
        await _send_text_message(phone, f"{result.get('message', 'Nao consegui verificar.')} Tente novamente com outro dado.")


# ─────────────────────────────────────────────
# Ferramentas extras
# ─────────────────────────────────────────────
async def _handle_popular_products(action_data: Dict, prospect: ProspectState):
    """Mostra produtos populares/mais vendidos."""
    import random
    client = get_shopify_client()
    if not client:
        await _send_text_message(prospect.jid, "Tô com dificuldade de acessar o catálogo agora. Tenta de novo em um minutinho!")
        return

    products = await get_popular_products_for_chat(limit=4)
    if not products:
        await _send_text_message(prospect.jid, "Não encontrei produtos no momento 😕")
        return

    # Filtrar esgotados dos destaques
    available = [p for p in products if p.get("totalInventory", 0) > 0][:4]
    if not available:
        available = products[:3]

    intros = [
        "Olha os que tão fazendo mais sucesso! 🔥\n",
        "Esses aqui são os queridinhos do momento:\n",
        "Separei os mais vendidos pra você:\n",
    ]
    lines = [random.choice(intros)]
    for i, product in enumerate(available, 1):
        title = product.get("title", "")
        price = product.get("priceRangeV2", {}).get("minVariantPrice", {}).get("amount", "0")
        lines.append(f"*{i}. {title}* — R$ {float(price):.2f}")
        lines.append("")

    closings = [
        "Curtiu algum? 😊",
        "Algum chamou sua atenção?",
        "Quer saber mais sobre algum desses?",
    ]
    lines.append(random.choice(closings))
    await _send_text_message(prospect.jid, "\n".join(lines))


async def _handle_recommend_products(action_data: Dict, prospect: ProspectState):
    """Recomenda produtos — formato natural sem links repetitivos."""
    import random
    client = get_shopify_client()
    if not client:
        return

    args = action_data.get("arguments", {})
    product_ids = args.get("product_ids", [])

    products = await recommend_products_for_chat(product_ids, limit=3)
    if not products:
        await _send_text_message(prospect.jid, "Não encontrei recomendações agora. Quer ver os mais vendidos?")
        return

    # Filtrar esgotados
    available = [p for p in products if p.get("totalInventory", 0) > 0]
    if not available:
        available = products[:3]

    intros = [
        "Acho que você vai curtir esses aqui:\n",
        "Olha o que separei pra você:\n",
        "Com base no que você gostou, recomendo:\n",
    ]
    lines = [random.choice(intros)]
    for i, product in enumerate(available[:3], 1):
        title = product.get("title", "")
        price = product.get("priceRangeV2", {}).get("minVariantPrice", {}).get("amount", "0")
        lines.append(f"*{i}. {title}* — R$ {float(price):.2f}")
        lines.append("")

    closings = [
        "Algum te interessou?",
        "Curtiu algum? Me avisa que mando mais detalhes!",
        "Quer saber mais sobre algum?",
    ]
    lines.append(random.choice(closings))
    await _send_text_message(prospect.jid, "\n".join(lines))


async def _handle_check_stock(action_data: Dict, prospect: ProspectState):
    """Verifica estoque — busca variantes do produto se não tiver variant_id."""
    args = action_data.get("arguments", {})
    variant_id = args.get("variant_id", "")
    product_query = args.get("query", args.get("product_name", ""))

    # Se não tem variant_id mas tem query, buscar produto e mostrar variantes
    if not variant_id or variant_id == "gid://shopify/ProductVariant/12345":
        if product_query:
            products = await search_products_for_chat(product_query, limit=1)
            if products:
                product = products[0]
                title = product.get("title", "")
                variants = product.get("variants", {}).get("edges", [])
                url = product.get("onlineStoreUrl", "")
                if variants:
                    available_variants = []
                    unavailable_variants = []
                    for v in variants:
                        node = v["node"]
                        opts = [f"{o['value']}" for o in node.get("selectedOptions", []) if o.get("name", "").lower() != "title"]
                        opt_str = " / ".join(opts) if opts else node.get("title", "")
                        price = node.get("price", "0")
                        is_available = node.get("availableForSale") and node.get("inventoryQuantity", 0) > 0
                        entry = f"  • {opt_str} — R$ {float(price):.2f}"
                        if is_available:
                            available_variants.append(entry)
                        else:
                            unavailable_variants.append(f"  • ~{opt_str}~ (esgotado)")

                    lines = [f"*{title}*\n"]
                    if available_variants:
                        lines.append("✅ *Disponíveis:*")
                        lines.extend(available_variants)
                    if unavailable_variants:
                        lines.append("\n❌ *Esgotados:*")
                        lines.extend(unavailable_variants)
                    if url:
                        lines.append(f"\n{url}")
                    lines.append("\nQual você quer?")
                    await _send_text_message(prospect.jid, "\n".join(lines))
                    return
        await _send_text_message(prospect.jid, "Qual produto você quer verificar? Me diz o nome que eu busco!")
        return

    stock = await check_stock_for_chat(variant_id)
    if not stock:
        await _send_text_message(prospect.jid, "Não encontrei essa variante. Me diz o nome do produto que eu busco as opções!")
        return

    product_title = stock.get("product", {}).get("title", "Produto")
    variant_title = stock.get("title", "")
    qty = stock.get("inventoryQuantity", 0)
    available = stock.get("availableForSale", False)
    price = stock.get("price", "0")

    if available and qty > 0:
        msg = f"*{product_title}*"
        if variant_title and variant_title != "Default Title":
            msg += f" — {variant_title}"
        msg += f"\n\n✅ Em estoque ({qty} un.)\nR$ {float(price):.2f}\n\nQuer comprar?"
    else:
        msg = f"*{product_title}* — Infelizmente está esgotado no momento 😕 Quer que eu te avise quando voltar?"

    await _send_text_message(prospect.jid, msg)


async def _handle_store_policies(action_data: Dict, prospect: ProspectState):
    """Busca política da loja e salva como contexto para o LLM responder naturalmente."""
    args = action_data.get("arguments", {})
    policy_type = args.get("type", "refundPolicy")

    policies = await get_store_policies_for_chat()
    if not policies:
        await _send_text_message(
            prospect.jid,
            "Não consegui acessar as políticas agora. Entre em contato com nosso suporte para mais detalhes!",
        )
        return

    # Mapear tipo solicitado
    type_map = {
        "refund": "refundPolicy", "troca": "refundPolicy", "devolucao": "refundPolicy",
        "shipping": "shippingPolicy", "frete": "shippingPolicy", "envio": "shippingPolicy",
        "privacy": "privacyPolicy", "privacidade": "privacyPolicy",
        "terms": "termsOfService", "termos": "termsOfService",
    }
    key = type_map.get(policy_type.lower(), policy_type)

    if key in policies:
        policy = policies[key]
        body = policy.get("body", "")
        # Limpar HTML
        import re as _re
        body = _re.sub(r'<[^>]*>', ' ', body)
        body = _re.sub(r'&nbsp;', ' ', body)
        body = _re.sub(r'&amp;', '&', body)
        body = _re.sub(r'&lt;', '<', body)
        body = _re.sub(r'&gt;', '>', body)
        body = _re.sub(r'&#\d+;', '', body)
        body = _re.sub(r'&\w+;', '', body)
        body = _re.sub(r'\s+', ' ', body).strip()
        if len(body) > 1500:
            body = body[:1500]

        # Salvar política como contexto no histórico para o LLM usar na próxima resposta
        title_map = {
            "refundPolicy": "Trocas e Devoluções",
            "shippingPolicy": "Envio e Frete",
            "privacyPolicy": "Privacidade",
            "termsOfService": "Termos de Serviço",
        }
        title = title_map.get(key, key)
        context_msg = f"[CONTEXTO_POLITICA: {title}] {body}"
        await add_message_to_history_state(
            prospect.jid, "system", context_msg,
            conversation_initiator_override=prospect.conversation_initiator,
        )

        # Resposta natural e curta baseada no tipo
        policy_responses = {
            "shippingPolicy": "O frete é calculado no carrinho com base no seu CEP. Coloca o produto lá que já aparece o valor certinho! Se quiser, me passa seu CEP que eu te ajudo 😊",
            "refundPolicy": "Temos política de troca e devolução! Se precisar trocar ou devolver, é só entrar em contato com nosso suporte. Quer que eu te passe mais detalhes?",
            "privacyPolicy": "Seus dados estão seguros com a gente! Usamos as informações apenas para processar seus pedidos e melhorar sua experiência. Quer saber algo específico?",
            "termsOfService": "Nossos termos de serviço cobrem tudo sobre compras, entregas e responsabilidades. Quer saber sobre algum ponto específico?",
        }
        response = policy_responses.get(key, f"Encontrei a política de *{title}*. Quer que eu resuma algum ponto específico?")
        await _send_text_message(prospect.jid, response)
    else:
        # Enviar resumo de todas as políticas disponíveis
        msg = "Temos informações sobre:\n\n"
        name_map = {
            "refundPolicy": "Trocas e Devoluções",
            "shippingPolicy": "Envio e Frete",
            "privacyPolicy": "Privacidade",
            "termsOfService": "Termos de Serviço",
        }
        for k, v in policies.items():
            msg += f"• *{name_map.get(k, k)}*\n"
        msg += "\nSobre qual delas você quer saber?"
        await _send_text_message(prospect.jid, msg)


async def _handle_business_hours(action_data: Dict, prospect: ProspectState):
    """Retorna horário de atendimento configurado no banco."""
    from src.core.db_operations.config_crud import get_config_value

    hours_config = await get_config_value("store_business_hours", None, instance_id=settings.INSTANCE_ID)

    if hours_config and isinstance(hours_config, dict):
        weekdays = hours_config.get("weekdays", "Segunda a Sexta")
        weekday_hours = hours_config.get("weekday_hours", "8h às 18h")
        saturday = hours_config.get("saturday_hours", "")
        sunday = hours_config.get("sunday_hours", "")
        extra = hours_config.get("extra_info", "")

        lines = [f"Nosso horário de atendimento:\n"]
        lines.append(f"📅 *{weekdays}:* {weekday_hours}")
        if saturday:
            lines.append(f"📅 *Sábado:* {saturday}")
        if sunday:
            lines.append(f"📅 *Domingo:* {sunday}")
        if extra:
            lines.append(f"\n{extra}")
        lines.append("\nPosso ajudar com mais alguma coisa? 😊")
        await _send_text_message(prospect.jid, "\n".join(lines))
    elif hours_config and isinstance(hours_config, str):
        await _send_text_message(prospect.jid, hours_config)
    else:
        await _send_text_message(
            prospect.jid,
            "Não tenho essa informação no momento. Você pode conferir direto no site: www.fiberoficial.com.br 😊"
        )


async def _handle_shop_info(action_data: Dict, prospect: ProspectState):
    """Busca e envia informações da loja (endereço, contato, moeda) via Shopify API."""
    info_text = await get_shop_info_for_chat()
    await _send_text_message(prospect.jid, info_text)


# ─────────────────────────────────────────────
# Funções de envio
# ─────────────────────────────────────────────
async def _send_text_message(phone_number: str, text: str, token_usage: Dict = None, conversation_initiator: str = None, max_retries: int = 3) -> bool:
    """Envia mensagem de texto via Evolution API com retry."""
    for attempt in range(max_retries):
        try:
            formatted_jid = formatting.format_number_for_evolution(phone_number)
            if not formatted_jid:
                return False

            segments = message_utils.split_message(text)
            success_count = 0

            for idx, segment in enumerate(segments):
                response = await evolution.send_text_message(jid=formatted_jid, text=segment)
                if bool(response):
                    await add_message_to_history_state(
                        phone_number, "assistant", segment,
                        token_usage if idx == 0 else None,
                        conversation_initiator_override=conversation_initiator,
                    )
                    success_count += 1
                    if idx < len(segments) - 1:
                        await asyncio.sleep(message_utils.calculate_delay(segment) / 1000.0)
                else:
                    break

            if success_count == len(segments):
                return True

            if attempt < max_retries - 1:
                import random
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

        except Exception as e:
            logger.error(f"[{phone_number}] Erro envio tentativa {attempt+1}: {e}", exc_info=True)
            if attempt < max_retries - 1:
                import random
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

    logger.error(f"[{phone_number}] Falha definitiva no envio após {max_retries} tentativas")
    return False


async def _send_audio_message(phone_number: str, audio_path_str: str, caption: str = "", max_retries: int = 3) -> bool:
    """Envia áudio via Evolution API com retry."""
    try:
        audio_path = Path(audio_path_str)
        if not audio_path.exists() or audio_path.stat().st_size == 0:
            return False

        formatted_jid = formatting.format_number_for_evolution(phone_number)
        if not formatted_jid:
            return False

        duration_sec = await audio_utils.get_audio_duration(audio_path_str)
        audio_b64 = await audio_utils.encode_audio_base64(audio_path_str)
        if not duration_sec or not audio_b64:
            return False

        for attempt in range(max_retries):
            response = await evolution.send_whatsapp_audio(
                jid=formatted_jid, audio_base64=audio_b64, duration_seconds=duration_sec,
            )
            if response:
                return True
            if attempt < max_retries - 1:
                import random
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

    except Exception as e:
        logger.error(f"[{phone_number}] Erro envio áudio: {e}", exc_info=True)

    return False


# Aliases para compatibilidade com outros módulos
_send_text_message_mh = _send_text_message
_send_audio_message_mh = _send_audio_message


logger.info("message_handling.py: Módulo carregado (modo atendimento e-commerce simplificado).")
