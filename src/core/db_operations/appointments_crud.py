# -*- coding: utf-8 -*-
"""
Appointments CRUD Operations
Gerencia operações de banco de dados para agendamentos e confirmações automáticas.
"""
import logging
import aiomysql
import pymysql.err
import json
import asyncio
from typing import Optional, Any, Dict, List
from datetime import datetime, timedelta
import pytz

from src.core.config import settings
from src.core.db_operations.prospect_crud import execute_with_retry

logger = logging.getLogger(__name__)

# SQL para criar tabela de agendamentos
CREATE_APPOINTMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scheduled_appointments (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'ID único do agendamento',
    instance_id VARCHAR(100) NOT NULL COMMENT 'ID da instância da aplicação',
    professional_id INT NULL COMMENT 'ID do profissional responsável',
    prospect_jid VARCHAR(255) NOT NULL COMMENT 'JID do prospect (número WhatsApp)',
    prospect_name VARCHAR(255) NULL COMMENT 'Nome do prospect',
    appointment_datetime DATETIME NOT NULL COMMENT 'Data e hora do agendamento',
    service_name VARCHAR(255) NULL COMMENT 'Nome do serviço/procedimento',
    event_id VARCHAR(255) NULL COMMENT 'ID do evento no Google Calendar',
    event_summary VARCHAR(500) NULL COMMENT 'Título/resumo do evento',
    event_description TEXT NULL COMMENT 'Descrição do evento',
    hangout_link VARCHAR(500) NULL COMMENT 'Link da videochamada (Google Meet)',
    confirmation_24h_sent BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Confirmação 24h enviada',
    confirmation_24h_sent_at DATETIME NULL COMMENT 'Quando a confirmação 24h foi enviada',
    confirmation_1h_sent BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Confirmação 1h enviada',
    confirmation_1h_sent_at DATETIME NULL COMMENT 'Quando a confirmação 1h foi enviada',
    patient_confirmed BOOLEAN NULL COMMENT 'Paciente confirmou presença (null=não respondeu)',
    patient_response TEXT NULL COMMENT 'Resposta do paciente',
    status ENUM('scheduled', 'confirmed', 'cancelled', 'completed', 'no_show') NOT NULL DEFAULT 'scheduled' COMMENT 'Status do agendamento',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Data de criação',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Última atualização',
    INDEX idx_instance_jid (instance_id, prospect_jid),
    INDEX idx_professional (instance_id, professional_id),
    INDEX idx_appointment_datetime (appointment_datetime),
    INDEX idx_status (status),
    INDEX idx_confirmation_pending (confirmation_24h_sent, confirmation_1h_sent, appointment_datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Armazena agendamentos e status de confirmações';
"""

# SQL para adicionar coluna professional_id se não existir (migration)
ADD_PROFESSIONAL_ID_COLUMN_SQL = """
ALTER TABLE scheduled_appointments
ADD COLUMN IF NOT EXISTS professional_id INT NULL COMMENT 'ID do profissional responsável' AFTER instance_id,
ADD COLUMN IF NOT EXISTS service_name VARCHAR(255) NULL COMMENT 'Nome do serviço/procedimento' AFTER appointment_datetime,
ADD INDEX IF NOT EXISTS idx_professional (instance_id, professional_id);
"""

# SQL para criar tabela de configurações de confirmação
CREATE_CONFIRMATION_CONFIG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS appointment_confirmation_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    instance_id VARCHAR(100) NOT NULL UNIQUE COMMENT 'ID da instância',
    enabled BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Confirmações habilitadas',
    send_24h_before BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Enviar confirmação 24h antes',
    send_1h_before BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Enviar confirmação 1h antes',
    message_24h TEXT NULL COMMENT 'Mensagem personalizada para 24h',
    message_1h TEXT NULL COMMENT 'Mensagem personalizada para 1h',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Configurações de confirmação de agendamentos';
"""

# Mensagens padrão
DEFAULT_MESSAGE_24H = """Olá {nome}! 👋

Passando para lembrar do seu agendamento *amanhã*:

📅 *Data:* {data}
🕐 *Horário:* {horario}
{link_video}

Por favor, confirme sua presença respondendo:
✅ *SIM* - Confirmo minha presença
❌ *NÃO* - Preciso cancelar/reagendar

Aguardamos você! 🙂"""

DEFAULT_MESSAGE_1H = """Olá {nome}! ⏰

Seu agendamento é *daqui a 1 hora*:

🕐 *Horário:* {horario}
{link_video}

Estamos te esperando! 🙂"""


async def initialize_appointments_tables():
    """Inicializa as tabelas de agendamentos no banco de dados."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return False

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                logger.info("appointments_crud: Criando tabela scheduled_appointments...")
                await cursor.execute(CREATE_APPOINTMENTS_TABLE_SQL)

                logger.info("appointments_crud: Criando tabela appointment_confirmation_config...")
                await cursor.execute(CREATE_CONFIRMATION_CONFIG_TABLE_SQL)

                # Migration: adicionar colunas se não existirem
                logger.info("appointments_crud: Executando migration para professional_id...")
                try:
                    await cursor.execute(ADD_PROFESSIONAL_ID_COLUMN_SQL)
                except Exception as migration_error:
                    # Ignorar erro se colunas já existem
                    logger.debug(f"appointments_crud: Migration ignorada (colunas podem já existir): {migration_error}")

                await conn.commit()
                logger.info("appointments_crud: Tabelas de agendamentos criadas/verificadas com sucesso")
                return True
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao criar tabelas de agendamentos: {e}", exc_info=True)
        return False


async def create_appointment(
    prospect_jid: str,
    appointment_datetime: datetime,
    prospect_name: Optional[str] = None,
    professional_id: Optional[int] = None,
    service_name: Optional[str] = None,
    event_id: Optional[str] = None,
    event_summary: Optional[str] = None,
    event_description: Optional[str] = None,
    hangout_link: Optional[str] = None,
    instance_id: Optional[str] = None
) -> Optional[int]:
    """
    Cria um novo agendamento no banco de dados.

    Returns:
        ID do agendamento criado ou None em caso de erro
    """
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                INSERT INTO scheduled_appointments
                (instance_id, professional_id, prospect_jid, prospect_name, appointment_datetime,
                 service_name, event_id, event_summary, event_description, hangout_link)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                await cursor.execute(sql, (
                    instance_id, professional_id, prospect_jid, prospect_name, appointment_datetime,
                    service_name, event_id, event_summary, event_description, hangout_link
                ))
                await conn.commit()
                appointment_id = cursor.lastrowid
                logger.info(f"appointments_crud: Agendamento criado com ID {appointment_id} para {prospect_jid} (profissional: {professional_id})")
                return appointment_id
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao criar agendamento: {e}", exc_info=True)
        return None


async def get_pending_confirmations_24h(instance_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Busca agendamentos que precisam de confirmação 24h antes.
    Retorna agendamentos entre 23h e 25h antes do horário marcado que ainda não foram confirmados.
    """
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return []

    instance_id = instance_id or settings.INSTANCE_ID
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    now = datetime.now(sao_paulo_tz)

    # Janela de 23h a 25h antes do agendamento
    min_time = now + timedelta(hours=23)
    max_time = now + timedelta(hours=25)

    async def _execute_query():
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT * FROM scheduled_appointments
                WHERE instance_id = %s
                AND confirmation_24h_sent = FALSE
                AND status IN ('scheduled', 'confirmed')
                AND appointment_datetime BETWEEN %s AND %s
                ORDER BY appointment_datetime ASC
                """
                await cursor.execute(sql, (instance_id, min_time.replace(tzinfo=None), max_time.replace(tzinfo=None)))
                results = await cursor.fetchall()
                logger.debug(f"appointments_crud: Encontrados {len(results)} agendamentos pendentes de confirmação 24h")
                return results

    try:
        return await execute_with_retry(_execute_query, max_retries=3, jid="confirmations_24h")
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao buscar confirmações 24h pendentes após retries: {e}", exc_info=True)
        return []


async def get_pending_confirmations_1h(instance_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Busca agendamentos que precisam de confirmação 1h antes.
    Retorna agendamentos entre 50min e 70min antes do horário marcado que ainda não foram confirmados.
    """
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return []

    instance_id = instance_id or settings.INSTANCE_ID
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    now = datetime.now(sao_paulo_tz)

    # Janela de 50min a 70min antes do agendamento
    min_time = now + timedelta(minutes=50)
    max_time = now + timedelta(minutes=70)

    async def _execute_query():
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT * FROM scheduled_appointments
                WHERE instance_id = %s
                AND confirmation_1h_sent = FALSE
                AND status IN ('scheduled', 'confirmed')
                AND appointment_datetime BETWEEN %s AND %s
                ORDER BY appointment_datetime ASC
                """
                await cursor.execute(sql, (instance_id, min_time.replace(tzinfo=None), max_time.replace(tzinfo=None)))
                results = await cursor.fetchall()
                logger.debug(f"appointments_crud: Encontrados {len(results)} agendamentos pendentes de confirmação 1h")
                return results

    try:
        return await execute_with_retry(_execute_query, max_retries=3, jid="confirmations_1h")
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao buscar confirmações 1h pendentes após retries: {e}", exc_info=True)
        return []


async def mark_confirmation_sent(
    appointment_id: int,
    confirmation_type: str,  # '24h' ou '1h'
    instance_id: Optional[str] = None
) -> bool:
    """Marca uma confirmação como enviada."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return False

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if confirmation_type == '24h':
                    sql = """
                    UPDATE scheduled_appointments
                    SET confirmation_24h_sent = TRUE, confirmation_24h_sent_at = NOW()
                    WHERE id = %s AND instance_id = %s
                    """
                elif confirmation_type == '1h':
                    sql = """
                    UPDATE scheduled_appointments
                    SET confirmation_1h_sent = TRUE, confirmation_1h_sent_at = NOW()
                    WHERE id = %s AND instance_id = %s
                    """
                else:
                    logger.error(f"appointments_crud: Tipo de confirmação inválido: {confirmation_type}")
                    return False

                await cursor.execute(sql, (appointment_id, instance_id))
                await conn.commit()
                logger.info(f"appointments_crud: Confirmação {confirmation_type} marcada como enviada para agendamento {appointment_id}")
                return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao marcar confirmação como enviada: {e}", exc_info=True)
        return False


async def update_patient_response(
    appointment_id: int,
    confirmed: bool,
    response_text: Optional[str] = None,
    instance_id: Optional[str] = None
) -> bool:
    """Atualiza a resposta do paciente."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return False

    instance_id = instance_id or settings.INSTANCE_ID
    new_status = 'confirmed' if confirmed else 'cancelled'

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                UPDATE scheduled_appointments
                SET patient_confirmed = %s, patient_response = %s, status = %s
                WHERE id = %s AND instance_id = %s
                """
                await cursor.execute(sql, (confirmed, response_text, new_status, appointment_id, instance_id))
                await conn.commit()
                logger.info(f"appointments_crud: Resposta do paciente atualizada para agendamento {appointment_id}: confirmed={confirmed}")
                return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao atualizar resposta do paciente: {e}", exc_info=True)
        return False


async def update_appointment_status(
    appointment_id: int,
    status: str,
    instance_id: Optional[str] = None
) -> bool:
    """Atualiza o status de um agendamento."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return False

    instance_id = instance_id or settings.INSTANCE_ID
    valid_statuses = ['scheduled', 'confirmed', 'cancelled', 'completed', 'no_show']

    if status not in valid_statuses:
        logger.error(f"appointments_crud: Status inválido: {status}")
        return False

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                UPDATE scheduled_appointments
                SET status = %s
                WHERE id = %s AND instance_id = %s
                """
                await cursor.execute(sql, (status, appointment_id, instance_id))
                await conn.commit()
                logger.info(f"appointments_crud: Status do agendamento {appointment_id} atualizado para {status}")
                return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao atualizar status do agendamento: {e}", exc_info=True)
        return False


async def get_appointments_list(
    instance_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    prospect_jid: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Lista agendamentos com filtros opcionais.

    Returns:
        Dict com 'items' (lista de agendamentos) e 'total' (contagem total)
    """
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return {"items": [], "total": 0}

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Construir query dinâmica
                where_clauses = ["instance_id = %s"]
                params = [instance_id]

                if status:
                    where_clauses.append("status = %s")
                    params.append(status)

                if start_date:
                    where_clauses.append("appointment_datetime >= %s")
                    params.append(start_date)

                if end_date:
                    where_clauses.append("appointment_datetime <= %s")
                    params.append(end_date)

                if prospect_jid:
                    where_clauses.append("prospect_jid = %s")
                    params.append(prospect_jid)

                where_sql = " AND ".join(where_clauses)

                # Contar total
                count_sql = f"SELECT COUNT(*) as total FROM scheduled_appointments WHERE {where_sql}"
                await cursor.execute(count_sql, params)
                count_result = await cursor.fetchone()
                total = count_result['total'] if count_result else 0

                # Buscar items
                sql = f"""
                SELECT * FROM scheduled_appointments
                WHERE {where_sql}
                ORDER BY appointment_datetime DESC
                LIMIT %s OFFSET %s
                """
                await cursor.execute(sql, params + [limit, offset])
                items = await cursor.fetchall()

                # Converter datetime para string ISO
                for item in items:
                    for key in ['appointment_datetime', 'confirmation_24h_sent_at', 'confirmation_1h_sent_at', 'created_at', 'updated_at']:
                        if item.get(key) and isinstance(item[key], datetime):
                            item[key] = item[key].isoformat()

                return {"items": items, "total": total}
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao listar agendamentos: {e}", exc_info=True)
        return {"items": [], "total": 0}


async def get_appointment_by_id(
    appointment_id: int,
    instance_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Busca um agendamento pelo ID."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = "SELECT * FROM scheduled_appointments WHERE id = %s AND instance_id = %s"
                await cursor.execute(sql, (appointment_id, instance_id))
                result = await cursor.fetchone()

                if result:
                    # Converter datetime para string ISO
                    for key in ['appointment_datetime', 'confirmation_24h_sent_at', 'confirmation_1h_sent_at', 'created_at', 'updated_at']:
                        if result.get(key) and isinstance(result[key], datetime):
                            result[key] = result[key].isoformat()

                return result
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao buscar agendamento por ID: {e}", exc_info=True)
        return None


async def get_appointment_by_jid_and_time(
    prospect_jid: str,
    appointment_datetime: datetime,
    instance_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Busca um agendamento pelo JID do prospect e horário."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Janela de 5 minutos para encontrar o agendamento
                min_time = appointment_datetime - timedelta(minutes=5)
                max_time = appointment_datetime + timedelta(minutes=5)

                sql = """
                SELECT * FROM scheduled_appointments
                WHERE instance_id = %s AND prospect_jid = %s
                AND appointment_datetime BETWEEN %s AND %s
                ORDER BY appointment_datetime DESC
                LIMIT 1
                """
                await cursor.execute(sql, (instance_id, prospect_jid, min_time, max_time))
                return await cursor.fetchone()
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao buscar agendamento por JID e horário: {e}", exc_info=True)
        return None


# ============ Configurações de Confirmação ============

async def get_confirmation_config(instance_id: Optional[str] = None) -> Dict[str, Any]:
    """Busca configurações de confirmação de agendamentos."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return get_default_confirmation_config()

    instance_id = instance_id or settings.INSTANCE_ID

    async def _execute_query():
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = "SELECT * FROM appointment_confirmation_config WHERE instance_id = %s"
                await cursor.execute(sql, (instance_id,))
                result = await cursor.fetchone()

                if result:
                    return result
                else:
                    # Retornar configurações padrão
                    return get_default_confirmation_config()

    try:
        return await execute_with_retry(_execute_query, max_retries=3, jid="confirmation_config")
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao buscar configurações de confirmação após retries: {e}", exc_info=True)
        return get_default_confirmation_config()


def get_default_confirmation_config() -> Dict[str, Any]:
    """Retorna configurações padrão de confirmação."""
    return {
        "enabled": True,
        "send_24h_before": True,
        "send_1h_before": True,
        "message_24h": DEFAULT_MESSAGE_24H,
        "message_1h": DEFAULT_MESSAGE_1H
    }


async def save_confirmation_config(
    config: Dict[str, Any],
    instance_id: Optional[str] = None
) -> bool:
    """Salva configurações de confirmação de agendamentos."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return False

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                INSERT INTO appointment_confirmation_config
                (instance_id, enabled, send_24h_before, send_1h_before,
                 message_24h, message_1h)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                enabled = VALUES(enabled),
                send_24h_before = VALUES(send_24h_before),
                send_1h_before = VALUES(send_1h_before),
                message_24h = VALUES(message_24h),
                message_1h = VALUES(message_1h)
                """
                await cursor.execute(sql, (
                    instance_id,
                    config.get('enabled', True),
                    config.get('send_24h_before', True),
                    config.get('send_1h_before', True),
                    config.get('message_24h', DEFAULT_MESSAGE_24H),
                    config.get('message_1h', DEFAULT_MESSAGE_1H)
                ))
                await conn.commit()
                logger.info("appointments_crud: Configurações de confirmação salvas com sucesso")
                return True
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao salvar configurações de confirmação: {e}", exc_info=True)
        return False


async def get_upcoming_appointments(
    days_ahead: int = 7,
    instance_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Busca agendamentos futuros dentro do período especificado."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return []

    instance_id = instance_id or settings.INSTANCE_ID
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    now = datetime.now(sao_paulo_tz)
    end_date = now + timedelta(days=days_ahead)

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT * FROM scheduled_appointments
                WHERE instance_id = %s
                AND status IN ('scheduled', 'confirmed')
                AND appointment_datetime BETWEEN %s AND %s
                ORDER BY appointment_datetime ASC
                """
                await cursor.execute(sql, (instance_id, now.replace(tzinfo=None), end_date.replace(tzinfo=None)))
                results = await cursor.fetchall()

                # Converter datetime para string ISO
                for item in results:
                    for key in ['appointment_datetime', 'confirmation_24h_sent_at', 'confirmation_1h_sent_at', 'created_at', 'updated_at']:
                        if item.get(key) and isinstance(item[key], datetime):
                            item[key] = item[key].isoformat()

                return results
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao buscar agendamentos futuros: {e}", exc_info=True)
        return []


async def get_appointments_stats(instance_id: Optional[str] = None) -> Dict[str, Any]:
    """Retorna estatísticas de agendamentos."""
    if not settings.db_pool:
        logger.error("appointments_crud: Pool de conexão não disponível")
        return {}

    instance_id = instance_id or settings.INSTANCE_ID
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    now = datetime.now(sao_paulo_tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                stats = {}

                # Total de agendamentos
                await cursor.execute(
                    "SELECT COUNT(*) as total FROM scheduled_appointments WHERE instance_id = %s",
                    (instance_id,)
                )
                result = await cursor.fetchone()
                stats['total'] = result['total'] if result else 0

                # Agendamentos por status
                await cursor.execute("""
                    SELECT status, COUNT(*) as count
                    FROM scheduled_appointments
                    WHERE instance_id = %s
                    GROUP BY status
                """, (instance_id,))
                status_counts = await cursor.fetchall()
                stats['by_status'] = {row['status']: row['count'] for row in status_counts}

                # Agendamentos hoje
                await cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM scheduled_appointments
                    WHERE instance_id = %s
                    AND DATE(appointment_datetime) = DATE(%s)
                """, (instance_id, today_start.replace(tzinfo=None)))
                result = await cursor.fetchone()
                stats['today'] = result['count'] if result else 0

                # Agendamentos esta semana
                await cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM scheduled_appointments
                    WHERE instance_id = %s
                    AND appointment_datetime >= %s
                    AND appointment_datetime < %s
                """, (instance_id, week_start.replace(tzinfo=None), (week_start + timedelta(days=7)).replace(tzinfo=None)))
                result = await cursor.fetchone()
                stats['this_week'] = result['count'] if result else 0

                # Confirmações enviadas (24h)
                await cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM scheduled_appointments
                    WHERE instance_id = %s AND confirmation_24h_sent = TRUE
                """, (instance_id,))
                result = await cursor.fetchone()
                stats['confirmations_24h_sent'] = result['count'] if result else 0

                # Confirmações enviadas (1h)
                await cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM scheduled_appointments
                    WHERE instance_id = %s AND confirmation_1h_sent = TRUE
                """, (instance_id,))
                result = await cursor.fetchone()
                stats['confirmations_1h_sent'] = result['count'] if result else 0

                # Taxa de confirmação (pacientes que confirmaram)
                await cursor.execute("""
                    SELECT
                        COUNT(CASE WHEN patient_confirmed = TRUE THEN 1 END) as confirmed,
                        COUNT(CASE WHEN patient_confirmed IS NOT NULL THEN 1 END) as responded
                    FROM scheduled_appointments
                    WHERE instance_id = %s
                """, (instance_id,))
                result = await cursor.fetchone()
                if result and result['responded'] > 0:
                    stats['confirmation_rate'] = round((result['confirmed'] / result['responded']) * 100, 1)
                else:
                    stats['confirmation_rate'] = 0

                return stats
    except Exception as e:
        logger.error(f"appointments_crud: Erro ao buscar estatísticas de agendamentos: {e}", exc_info=True)
        return {}


logger.info("appointments_crud.py: Módulo carregado")
