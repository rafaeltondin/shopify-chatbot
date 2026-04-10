# -*- coding: utf-8 -*-
"""
Sistema de Alertas para Erros Críticos
Envia notificações sobre problemas que requerem atenção imediata.
"""
import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
import pytz

from src.core.config import settings

logger = logging.getLogger(__name__)

# Timezone padrão
SAO_PAULO_TZ = pytz.timezone('America/Sao_Paulo')

# Histórico de alertas em memória (últimos 100)
_alert_history: List[Dict[str, Any]] = []
MAX_ALERT_HISTORY = 100

# Tipos de alertas suportados
ALERT_TYPES = {
    "EVOLUTION_API_DISCONNECTED": {
        "severity": "critical",
        "title_prefix": "🚨 CRÍTICO",
        "auto_pause_queue": True
    },
    "REDIS_DISCONNECTED": {
        "severity": "critical",
        "title_prefix": "🚨 CRÍTICO",
        "auto_pause_queue": True
    },
    "LLM_API_ERROR": {
        "severity": "high",
        "title_prefix": "⚠️ ALTO",
        "auto_pause_queue": False
    },
    "QUEUE_STUCK": {
        "severity": "high",
        "title_prefix": "⚠️ ALTO",
        "auto_pause_queue": False
    },
    "DATABASE_ERROR": {
        "severity": "critical",
        "title_prefix": "🚨 CRÍTICO",
        "auto_pause_queue": False
    },
    "DEAD_LETTER_QUEUE_FULL": {
        "severity": "medium",
        "title_prefix": "📋 MÉDIO",
        "auto_pause_queue": False
    },
    "WEBHOOK_TIMEOUT": {
        "severity": "medium",
        "title_prefix": "📋 MÉDIO",
        "auto_pause_queue": False
    },
    "AUDIO_TRANSCRIPTION_FAILURE": {
        "severity": "low",
        "title_prefix": "📝 INFO",
        "auto_pause_queue": False
    }
}


async def send_critical_alert(
    alert_type: str,
    title: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Envia um alerta crítico através de todos os canais configurados.

    Args:
        alert_type: Tipo do alerta (ver ALERT_TYPES)
        title: Título do alerta
        message: Mensagem detalhada
        metadata: Dados adicionais (jid, error_code, etc)

    Returns:
        True se o alerta foi enviado com sucesso em pelo menos um canal
    """
    logger.info(f"[ALERTS] Enviando alerta: type={alert_type}, title={title}")

    alert_config = ALERT_TYPES.get(alert_type, {
        "severity": "medium",
        "title_prefix": "📋",
        "auto_pause_queue": False
    })

    # Criar registro do alerta
    alert_record = {
        "id": f"alert_{datetime.now(SAO_PAULO_TZ).strftime('%Y%m%d%H%M%S%f')}",
        "type": alert_type,
        "severity": alert_config["severity"],
        "title": f"{alert_config['title_prefix']}: {title}",
        "message": message,
        "metadata": metadata or {},
        "timestamp": datetime.now(SAO_PAULO_TZ).isoformat(),
        "acknowledged": False,
        "channels_sent": []
    }

    success = False

    # 1. Enviar via WebSocket para UI
    try:
        from src.core.websocket_manager import manager
        await manager.broadcast("critical_alert", {
            "alert": alert_record
        })
        alert_record["channels_sent"].append("websocket")
        logger.info(f"[ALERTS] Alerta enviado via WebSocket")
        success = True
    except Exception as e:
        logger.error(f"[ALERTS] Erro ao enviar alerta via WebSocket: {e}")

    # 2. Salvar no Redis para persistência
    try:
        if settings.redis_client:
            alert_key = f"alerts:{settings.INSTANCE_ID}"
            await settings.redis_client.lpush(alert_key, json.dumps(alert_record))
            await settings.redis_client.ltrim(alert_key, 0, MAX_ALERT_HISTORY - 1)
            alert_record["channels_sent"].append("redis")
            logger.info(f"[ALERTS] Alerta salvo no Redis")
            success = True
    except Exception as e:
        logger.error(f"[ALERTS] Erro ao salvar alerta no Redis: {e}")

    # 3. Adicionar ao histórico em memória
    _alert_history.insert(0, alert_record)
    if len(_alert_history) > MAX_ALERT_HISTORY:
        _alert_history.pop()

    # 4. Log detalhado para arquivo
    log_message = f"""
================================================================================
ALERTA CRÍTICO - {alert_record['timestamp']}
================================================================================
Tipo: {alert_type}
Severidade: {alert_config['severity']}
Título: {alert_record['title']}
Mensagem: {message}
Metadados: {json.dumps(metadata or {}, indent=2, ensure_ascii=False)}
Canais: {', '.join(alert_record['channels_sent']) or 'nenhum'}
================================================================================
"""
    if alert_config["severity"] == "critical":
        logger.critical(log_message)
    else:
        logger.warning(log_message)

    return success


async def get_recent_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Retorna os alertas mais recentes.

    Args:
        limit: Número máximo de alertas a retornar

    Returns:
        Lista de alertas ordenados por timestamp (mais recentes primeiro)
    """
    # Tentar obter do Redis primeiro
    try:
        if settings.redis_client:
            alert_key = f"alerts:{settings.INSTANCE_ID}"
            alerts_json = await settings.redis_client.lrange(alert_key, 0, limit - 1)
            return [json.loads(a) for a in alerts_json]
    except Exception as e:
        logger.error(f"[ALERTS] Erro ao obter alertas do Redis: {e}")

    # Fallback para histórico em memória
    return _alert_history[:limit]


async def acknowledge_alert(alert_id: str) -> bool:
    """
    Marca um alerta como reconhecido/tratado.

    Args:
        alert_id: ID do alerta

    Returns:
        True se o alerta foi encontrado e atualizado
    """
    logger.info(f"[ALERTS] Reconhecendo alerta: {alert_id}")

    # Atualizar em memória
    for alert in _alert_history:
        if alert.get("id") == alert_id:
            alert["acknowledged"] = True
            alert["acknowledged_at"] = datetime.now(SAO_PAULO_TZ).isoformat()

            # Tentar atualizar no Redis também
            try:
                if settings.redis_client:
                    alert_key = f"alerts:{settings.INSTANCE_ID}"
                    alerts_json = await settings.redis_client.lrange(alert_key, 0, MAX_ALERT_HISTORY - 1)
                    for i, a_json in enumerate(alerts_json):
                        a = json.loads(a_json)
                        if a.get("id") == alert_id:
                            a["acknowledged"] = True
                            a["acknowledged_at"] = alert["acknowledged_at"]
                            await settings.redis_client.lset(alert_key, i, json.dumps(a))
                            break
            except Exception as e:
                logger.error(f"[ALERTS] Erro ao atualizar alerta no Redis: {e}")

            logger.info(f"[ALERTS] Alerta {alert_id} reconhecido")
            return True

    logger.warning(f"[ALERTS] Alerta {alert_id} não encontrado")
    return False


async def get_unacknowledged_count() -> int:
    """
    Retorna o número de alertas não reconhecidos.
    """
    try:
        alerts = await get_recent_alerts(MAX_ALERT_HISTORY)
        return sum(1 for a in alerts if not a.get("acknowledged", False))
    except Exception as e:
        logger.error(f"[ALERTS] Erro ao contar alertas não reconhecidos: {e}")
        return 0


async def clear_old_alerts(days: int = 7) -> int:
    """
    Remove alertas mais antigos que X dias.

    Args:
        days: Número de dias para manter alertas

    Returns:
        Número de alertas removidos
    """
    logger.info(f"[ALERTS] Limpando alertas mais antigos que {days} dias")

    cutoff = datetime.now(SAO_PAULO_TZ).timestamp() - (days * 86400)
    removed = 0

    # Limpar memória
    original_len = len(_alert_history)
    _alert_history[:] = [
        a for a in _alert_history
        if datetime.fromisoformat(a["timestamp"]).timestamp() > cutoff
    ]
    removed = original_len - len(_alert_history)

    logger.info(f"[ALERTS] {removed} alertas removidos")
    return removed


logger.info("alerts.py: Módulo de alertas carregado.")
