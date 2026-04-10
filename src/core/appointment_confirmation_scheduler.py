# -*- coding: utf-8 -*-
"""
Appointment Confirmation Scheduler
Sistema de envio automático de confirmações de agendamento (24h e 1h antes).
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import pytz

from src.core.config import settings
from src.core import evolution
from src.core.db_operations import appointments_crud, professionals_crud

logger = logging.getLogger(__name__)

# Controle do scheduler
_scheduler_task: Optional[asyncio.Task] = None
_scheduler_running: bool = False
_scheduler_paused: bool = False

# Intervalo de verificação (em segundos)
CHECK_INTERVAL_SECONDS = 60  # Verifica a cada 1 minuto


def format_confirmation_message(
    template: str,
    appointment: Dict[str, Any],
    config: Dict[str, Any],
    professional_name: Optional[str] = None
) -> str:
    """
    Formata a mensagem de confirmação com os dados do agendamento.

    Placeholders suportados:
    - {nome}: Nome do prospect
    - {data}: Data do agendamento (ex: "Segunda-feira, 15 de Janeiro")
    - {horario}: Horário do agendamento (ex: "14:30")
    - {link_video}: Link da videochamada (se houver)
    - {profissional}: Nome do profissional responsável
    - {servico}: Nome do serviço/procedimento
    - {sala}: Nome da sala/consultório
    """
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')

    # Obter data do agendamento
    appointment_dt = appointment.get('appointment_datetime')
    if isinstance(appointment_dt, str):
        appointment_dt = datetime.fromisoformat(appointment_dt)
    if appointment_dt.tzinfo is None:
        appointment_dt = sao_paulo_tz.localize(appointment_dt)
    else:
        appointment_dt = appointment_dt.astimezone(sao_paulo_tz)

    # Tradução dos dias da semana e meses
    dias_semana = {
        'Monday': 'Segunda-feira',
        'Tuesday': 'Terça-feira',
        'Wednesday': 'Quarta-feira',
        'Thursday': 'Quinta-feira',
        'Friday': 'Sexta-feira',
        'Saturday': 'Sábado',
        'Sunday': 'Domingo'
    }

    meses = {
        'January': 'Janeiro',
        'February': 'Fevereiro',
        'March': 'Março',
        'April': 'Abril',
        'May': 'Maio',
        'June': 'Junho',
        'July': 'Julho',
        'August': 'Agosto',
        'September': 'Setembro',
        'October': 'Outubro',
        'November': 'Novembro',
        'December': 'Dezembro'
    }

    # Formatar data em português
    dia_semana = dias_semana.get(appointment_dt.strftime('%A'), appointment_dt.strftime('%A'))
    dia = appointment_dt.strftime('%d')
    mes = meses.get(appointment_dt.strftime('%B'), appointment_dt.strftime('%B'))
    ano = appointment_dt.strftime('%Y')
    data_formatada = f"{dia_semana}, {dia} de {mes} de {ano}"

    # Formatar horário
    horario_formatado = appointment_dt.strftime('%H:%M')

    # Link de vídeo
    hangout_link = appointment.get('hangout_link')
    link_video = f"\n📹 *Link da videochamada:* {hangout_link}" if hangout_link else ""

    # Nome do prospect
    nome = appointment.get('prospect_name') or "Paciente"

    # Informações do profissional
    profissional = professional_name or ""
    servico = appointment.get('service_name') or ""
    sala = appointment.get('room_name') or ""

    # Substituir placeholders
    message = template.replace('{nome}', nome)
    message = message.replace('{data}', data_formatada)
    message = message.replace('{horario}', horario_formatado)
    message = message.replace('{link_video}', link_video)
    message = message.replace('{profissional}', profissional)
    message = message.replace('{servico}', servico)
    message = message.replace('{sala}', sala)

    return message


async def send_confirmation_message(
    appointment: Dict[str, Any],
    confirmation_type: str,  # '24h' ou '1h'
    config: Dict[str, Any]
) -> bool:
    """
    Envia mensagem de confirmação via WhatsApp.

    Returns:
        True se enviada com sucesso, False caso contrário
    """
    prospect_jid = appointment.get('prospect_jid')
    appointment_id = appointment.get('id')
    professional_id = appointment.get('professional_id')

    if not prospect_jid:
        logger.error(f"[CONFIRM_SCHEDULER] Agendamento {appointment_id} sem JID do prospect")
        return False

    try:
        # Buscar informações do profissional se houver
        professional_name = None
        if professional_id:
            try:
                professional = await professionals_crud.get_professional_by_id(professional_id)
                if professional:
                    professional_name = professional.get('name')
                    # Adicionar sala ao appointment para a formatação
                    appointment['room_name'] = professional.get('room_name')
            except Exception as e:
                logger.warning(f"[CONFIRM_SCHEDULER] Erro ao buscar profissional {professional_id}: {e}")

        # Selecionar template correto
        if confirmation_type == '24h':
            template = config.get('message_24h') or appointments_crud.DEFAULT_MESSAGE_24H
        else:
            template = config.get('message_1h') or appointments_crud.DEFAULT_MESSAGE_1H

        # Formatar mensagem
        message = format_confirmation_message(template, appointment, config, professional_name)

        # Enviar via Evolution API
        logger.info(f"[CONFIRM_SCHEDULER] Enviando confirmação {confirmation_type} para {prospect_jid}")
        result = await evolution.send_text_message(prospect_jid, message)

        if result:
            # Marcar como enviada no banco
            await appointments_crud.mark_confirmation_sent(appointment_id, confirmation_type)
            logger.info(f"[CONFIRM_SCHEDULER] Confirmação {confirmation_type} enviada com sucesso para {prospect_jid}")
            return True
        else:
            logger.error(f"[CONFIRM_SCHEDULER] Falha ao enviar confirmação {confirmation_type} para {prospect_jid}")
            return False

    except Exception as e:
        logger.error(f"[CONFIRM_SCHEDULER] Erro ao enviar confirmação: {e}", exc_info=True)
        return False


async def process_pending_confirmations():
    """Processa confirmações pendentes (24h e 1h)."""
    try:
        # Buscar configurações
        config = await appointments_crud.get_confirmation_config()

        if not config.get('enabled', True):
            logger.debug("[CONFIRM_SCHEDULER] Sistema de confirmações desabilitado")
            return

        # Processar confirmações de 24h
        if config.get('send_24h_before', True):
            pending_24h = await appointments_crud.get_pending_confirmations_24h()
            logger.debug(f"[CONFIRM_SCHEDULER] {len(pending_24h)} confirmações 24h pendentes")

            for appointment in pending_24h:
                await send_confirmation_message(appointment, '24h', config)
                # Pequeno delay entre envios para evitar rate limiting
                await asyncio.sleep(2)

        # Processar confirmações de 1h
        if config.get('send_1h_before', True):
            pending_1h = await appointments_crud.get_pending_confirmations_1h()
            logger.debug(f"[CONFIRM_SCHEDULER] {len(pending_1h)} confirmações 1h pendentes")

            for appointment in pending_1h:
                await send_confirmation_message(appointment, '1h', config)
                await asyncio.sleep(2)

    except Exception as e:
        logger.error(f"[CONFIRM_SCHEDULER] Erro ao processar confirmações: {e}", exc_info=True)


async def scheduler_loop():
    """Loop principal do scheduler de confirmações."""
    global _scheduler_running

    logger.info("[CONFIRM_SCHEDULER] Iniciando scheduler de confirmações de agendamento")

    while _scheduler_running:
        try:
            if not _scheduler_paused:
                await process_pending_confirmations()
            else:
                logger.debug("[CONFIRM_SCHEDULER] Scheduler pausado, aguardando...")

            # Aguardar próximo ciclo
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            logger.info("[CONFIRM_SCHEDULER] Scheduler cancelado")
            break
        except Exception as e:
            logger.error(f"[CONFIRM_SCHEDULER] Erro no loop do scheduler: {e}", exc_info=True)
            # Aguardar antes de tentar novamente
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    logger.info("[CONFIRM_SCHEDULER] Scheduler encerrado")


async def start_confirmation_scheduler():
    """Inicia o scheduler de confirmações."""
    global _scheduler_task, _scheduler_running

    if _scheduler_running:
        logger.warning("[CONFIRM_SCHEDULER] Scheduler já está em execução")
        return

    _scheduler_running = True
    _scheduler_task = asyncio.create_task(scheduler_loop())
    logger.info("[CONFIRM_SCHEDULER] Scheduler iniciado com sucesso")


async def stop_confirmation_scheduler():
    """Para o scheduler de confirmações."""
    global _scheduler_task, _scheduler_running

    if not _scheduler_running:
        logger.warning("[CONFIRM_SCHEDULER] Scheduler não está em execução")
        return

    _scheduler_running = False

    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None

    logger.info("[CONFIRM_SCHEDULER] Scheduler parado com sucesso")


def pause_confirmation_scheduler():
    """Pausa o scheduler de confirmações."""
    global _scheduler_paused
    _scheduler_paused = True
    logger.info("[CONFIRM_SCHEDULER] Scheduler pausado")


def resume_confirmation_scheduler():
    """Retoma o scheduler de confirmações."""
    global _scheduler_paused
    _scheduler_paused = False
    logger.info("[CONFIRM_SCHEDULER] Scheduler retomado")


def get_scheduler_status() -> Dict[str, Any]:
    """Retorna o status atual do scheduler."""
    return {
        "running": _scheduler_running,
        "paused": _scheduler_paused,
        "check_interval_seconds": CHECK_INTERVAL_SECONDS
    }


async def trigger_manual_check():
    """Dispara uma verificação manual de confirmações pendentes."""
    logger.info("[CONFIRM_SCHEDULER] Verificação manual disparada")
    await process_pending_confirmations()
    return {"message": "Verificação manual concluída"}


logger.info("appointment_confirmation_scheduler.py: Módulo carregado")
