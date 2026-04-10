# -*- coding: utf-8 -*-
"""
Professionals CRUD Operations
Gerencia operações de banco de dados para profissionais (médicos, dentistas, etc.)
e suas agendas/salas em clínicas multi-profissionais.
"""
import logging
import aiomysql
import json
from typing import Optional, Any, Dict, List
from datetime import datetime, timedelta, time
import pytz

from src.core.config import settings

logger = logging.getLogger(__name__)

# SQL para criar tabela de profissionais
CREATE_PROFESSIONALS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS professionals (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'ID único do profissional',
    instance_id VARCHAR(100) NOT NULL COMMENT 'ID da instância da aplicação',
    name VARCHAR(255) NOT NULL COMMENT 'Nome completo do profissional',
    specialty VARCHAR(255) NULL COMMENT 'Especialidade (ex: Dentista, Nutricionista)',
    registration_number VARCHAR(100) NULL COMMENT 'Número de registro (CRM, CRO, CRN, etc.)',
    email VARCHAR(255) NULL COMMENT 'Email do profissional',
    phone VARCHAR(50) NULL COMMENT 'Telefone do profissional',
    photo_url VARCHAR(500) NULL COMMENT 'URL da foto do profissional',
    room_name VARCHAR(100) NULL COMMENT 'Nome da sala/consultório (ex: Sala 1, Consultório A)',
    room_number VARCHAR(50) NULL COMMENT 'Número da sala',
    color VARCHAR(7) DEFAULT '#0D9488' COMMENT 'Cor para identificação visual (hex)',
    bio TEXT NULL COMMENT 'Biografia/descrição do profissional',
    appointment_duration INT DEFAULT 30 COMMENT 'Duração padrão da consulta em minutos',
    buffer_time INT DEFAULT 10 COMMENT 'Tempo de intervalo entre consultas em minutos',
    max_daily_appointments INT DEFAULT 20 COMMENT 'Máximo de agendamentos por dia',
    accepts_new_patients BOOLEAN DEFAULT TRUE COMMENT 'Aceita novos pacientes',
    is_active BOOLEAN DEFAULT TRUE COMMENT 'Profissional ativo',
    availability_schedule JSON NULL COMMENT 'Disponibilidade semanal (JSON)',
    google_calendar_id VARCHAR(255) NULL COMMENT 'ID do calendário Google específico (opcional)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_instance_id (instance_id),
    INDEX idx_specialty (specialty),
    INDEX idx_is_active (is_active),
    INDEX idx_room (instance_id, room_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Cadastro de profissionais da clínica';
"""

# SQL para criar tabela de bloqueios de agenda
CREATE_SCHEDULE_BLOCKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS professional_schedule_blocks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    instance_id VARCHAR(100) NOT NULL,
    professional_id INT NOT NULL,
    block_type ENUM('vacation', 'holiday', 'personal', 'training', 'other') NOT NULL DEFAULT 'other',
    title VARCHAR(255) NULL COMMENT 'Título do bloqueio',
    start_datetime DATETIME NOT NULL,
    end_datetime DATETIME NOT NULL,
    all_day BOOLEAN DEFAULT FALSE,
    recurring BOOLEAN DEFAULT FALSE,
    recurrence_rule VARCHAR(255) NULL COMMENT 'Regra de recorrência (RRULE)',
    notes TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (professional_id) REFERENCES professionals(id) ON DELETE CASCADE,
    INDEX idx_professional_dates (professional_id, start_datetime, end_datetime),
    INDEX idx_instance_dates (instance_id, start_datetime, end_datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Bloqueios de agenda dos profissionais';
"""

# SQL para criar tabela de serviços por profissional
CREATE_PROFESSIONAL_SERVICES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS professional_services (
    id INT AUTO_INCREMENT PRIMARY KEY,
    instance_id VARCHAR(100) NOT NULL,
    professional_id INT NOT NULL,
    service_name VARCHAR(255) NOT NULL COMMENT 'Nome do serviço/procedimento',
    description TEXT NULL,
    duration_minutes INT DEFAULT 30 COMMENT 'Duração do serviço em minutos',
    price DECIMAL(10,2) NULL COMMENT 'Preço do serviço',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (professional_id) REFERENCES professionals(id) ON DELETE CASCADE,
    INDEX idx_professional (professional_id),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Serviços oferecidos por cada profissional';
"""

# SQL para criar tabela de OAuth do Google Calendar por profissional
CREATE_PROFESSIONAL_GOOGLE_OAUTH_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS professional_google_oauth (
    id INT AUTO_INCREMENT PRIMARY KEY,
    instance_id VARCHAR(100) NOT NULL COMMENT 'ID da instância da aplicação',
    professional_id INT NOT NULL COMMENT 'ID do profissional',
    google_email VARCHAR(255) NOT NULL COMMENT 'Email da conta Google autenticada',
    calendar_id VARCHAR(255) DEFAULT 'primary' COMMENT 'ID do calendário a usar',
    access_token TEXT NOT NULL COMMENT 'Token de acesso OAuth2',
    refresh_token TEXT NOT NULL COMMENT 'Token de refresh OAuth2',
    token_expiry DATETIME NULL COMMENT 'Data de expiração do access_token',
    scopes TEXT NULL COMMENT 'Escopos autorizados',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_professional_oauth (instance_id, professional_id),
    FOREIGN KEY (professional_id) REFERENCES professionals(id) ON DELETE CASCADE,
    INDEX idx_instance_active (instance_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Tokens OAuth do Google Calendar por profissional';
"""

# Disponibilidade padrão (seg-sex, 8h-18h)
DEFAULT_AVAILABILITY = {
    "monday": [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
    "tuesday": [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
    "wednesday": [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
    "thursday": [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
    "friday": [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
    "saturday": [],
    "sunday": []
}

# Cores padrão para profissionais
PROFESSIONAL_COLORS = [
    "#0D9488",  # Teal (primary)
    "#0EA5E9",  # Sky blue
    "#8B5CF6",  # Violet
    "#EC4899",  # Pink
    "#F59E0B",  # Amber
    "#10B981",  # Emerald
    "#EF4444",  # Red
    "#6366F1",  # Indigo
]


async def initialize_professionals_tables():
    """Inicializa as tabelas de profissionais no banco de dados."""
    if not settings.db_pool:
        logger.error("professionals_crud: Pool de conexão não disponível")
        return False

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                logger.info("professionals_crud: Criando tabela professionals...")
                await cursor.execute(CREATE_PROFESSIONALS_TABLE_SQL)

                logger.info("professionals_crud: Criando tabela professional_schedule_blocks...")
                await cursor.execute(CREATE_SCHEDULE_BLOCKS_TABLE_SQL)

                logger.info("professionals_crud: Criando tabela professional_services...")
                await cursor.execute(CREATE_PROFESSIONAL_SERVICES_TABLE_SQL)

                logger.info("professionals_crud: Criando tabela professional_google_oauth...")
                await cursor.execute(CREATE_PROFESSIONAL_GOOGLE_OAUTH_TABLE_SQL)

                await conn.commit()
                logger.info("professionals_crud: Tabelas de profissionais criadas/verificadas com sucesso")
                return True
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao criar tabelas de profissionais: {e}", exc_info=True)
        return False


# ============ CRUD de Profissionais ============

async def create_professional(
    name: str,
    specialty: Optional[str] = None,
    registration_number: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    photo_url: Optional[str] = None,
    room_name: Optional[str] = None,
    room_number: Optional[str] = None,
    color: Optional[str] = None,
    bio: Optional[str] = None,
    appointment_duration: int = 30,
    buffer_time: int = 10,
    max_daily_appointments: int = 20,
    availability_schedule: Optional[Dict] = None,
    google_calendar_id: Optional[str] = None,
    instance_id: Optional[str] = None
) -> Optional[int]:
    """
    Cria um novo profissional.

    Returns:
        ID do profissional criado ou None em caso de erro
    """
    if not settings.db_pool:
        logger.error("professionals_crud: Pool de conexão não disponível")
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    # Selecionar cor automática se não especificada
    if not color:
        count = await get_professionals_count(instance_id)
        color = PROFESSIONAL_COLORS[count % len(PROFESSIONAL_COLORS)]

    # Usar disponibilidade padrão se não especificada
    if availability_schedule is None:
        availability_schedule = DEFAULT_AVAILABILITY

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                INSERT INTO professionals
                (instance_id, name, specialty, registration_number, email, phone,
                 photo_url, room_name, room_number, color, bio, appointment_duration,
                 buffer_time, max_daily_appointments, availability_schedule, google_calendar_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                await cursor.execute(sql, (
                    instance_id, name, specialty, registration_number, email, phone,
                    photo_url, room_name, room_number, color, bio, appointment_duration,
                    buffer_time, max_daily_appointments, json.dumps(availability_schedule),
                    google_calendar_id
                ))
                await conn.commit()
                professional_id = cursor.lastrowid
                logger.info(f"professionals_crud: Profissional '{name}' criado com ID {professional_id}")
                return professional_id
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao criar profissional: {e}", exc_info=True)
        return None


async def get_professional_by_id(
    professional_id: int,
    instance_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Busca um profissional pelo ID."""
    if not settings.db_pool:
        logger.error("professionals_crud: Pool de conexão não disponível")
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Aceitar profissionais da instance_id especificada OU com instance_id NULL (legado)
                sql = "SELECT * FROM professionals WHERE id = %s AND (instance_id = %s OR instance_id IS NULL)"
                await cursor.execute(sql, (professional_id, instance_id))
                result = await cursor.fetchone()

                if result:
                    # Parse JSON fields
                    if result.get('availability_schedule'):
                        try:
                            result['availability_schedule'] = json.loads(result['availability_schedule'])
                        except:
                            result['availability_schedule'] = DEFAULT_AVAILABILITY

                    # Convert datetime fields
                    for key in ['created_at', 'updated_at']:
                        if result.get(key) and isinstance(result[key], datetime):
                            result[key] = result[key].isoformat()

                return result
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar profissional por ID: {e}", exc_info=True)
        return None


async def get_professionals_list(
    instance_id: Optional[str] = None,
    specialty: Optional[str] = None,
    is_active: Optional[bool] = None,
    room_name: Optional[str] = None,
    accepts_new_patients: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Lista profissionais com filtros opcionais.

    Returns:
        Dict com 'items' (lista de profissionais) e 'total' (contagem total)
    """
    if not settings.db_pool:
        logger.error("professionals_crud: Pool de conexão não disponível")
        return {"items": [], "total": 0}

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Construir query dinâmica
                where_clauses = ["instance_id = %s"]
                params = [instance_id]

                if specialty:
                    where_clauses.append("specialty = %s")
                    params.append(specialty)

                if is_active is not None:
                    where_clauses.append("is_active = %s")
                    params.append(is_active)

                if room_name:
                    where_clauses.append("room_name = %s")
                    params.append(room_name)

                if accepts_new_patients is not None:
                    where_clauses.append("accepts_new_patients = %s")
                    params.append(accepts_new_patients)

                where_sql = " AND ".join(where_clauses)

                # Contar total
                count_sql = f"SELECT COUNT(*) as total FROM professionals WHERE {where_sql}"
                await cursor.execute(count_sql, params)
                count_result = await cursor.fetchone()
                total = count_result['total'] if count_result else 0

                # Buscar items
                sql = f"""
                SELECT * FROM professionals
                WHERE {where_sql}
                ORDER BY name ASC
                LIMIT %s OFFSET %s
                """
                await cursor.execute(sql, params + [limit, offset])
                items = await cursor.fetchall()

                # Parse JSON fields e converter datas
                for item in items:
                    if item.get('availability_schedule'):
                        try:
                            item['availability_schedule'] = json.loads(item['availability_schedule'])
                        except:
                            item['availability_schedule'] = DEFAULT_AVAILABILITY

                    for key in ['created_at', 'updated_at']:
                        if item.get(key) and isinstance(item[key], datetime):
                            item[key] = item[key].isoformat()

                return {"items": items, "total": total}
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao listar profissionais: {e}", exc_info=True)
        return {"items": [], "total": 0}


async def get_professionals_count(instance_id: Optional[str] = None) -> int:
    """Retorna a contagem de profissionais."""
    if not settings.db_pool:
        return 0

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT COUNT(*) as count FROM professionals WHERE instance_id = %s",
                    (instance_id,)
                )
                result = await cursor.fetchone()
                return result['count'] if result else 0
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao contar profissionais: {e}", exc_info=True)
        return 0


async def update_professional(
    professional_id: int,
    updates: Dict[str, Any],
    instance_id: Optional[str] = None
) -> bool:
    """
    Atualiza um profissional.

    Args:
        professional_id: ID do profissional
        updates: Dicionário com campos a atualizar
        instance_id: ID da instância

    Returns:
        True se atualizado com sucesso
    """
    if not settings.db_pool:
        logger.error("professionals_crud: Pool de conexão não disponível")
        return False

    instance_id = instance_id or settings.INSTANCE_ID
    logger.info(f"professionals_crud: [UPDATE] Iniciando atualização do profissional {professional_id}, instance_id={instance_id}")

    # Campos permitidos para atualização
    allowed_fields = [
        'name', 'specialty', 'registration_number', 'email', 'phone',
        'photo_url', 'room_name', 'room_number', 'color', 'bio',
        'appointment_duration', 'buffer_time', 'max_daily_appointments',
        'accepts_new_patients', 'is_active', 'availability_schedule',
        'google_calendar_id'
    ]

    # Filtrar campos válidos
    valid_updates = {k: v for k, v in updates.items() if k in allowed_fields}

    if not valid_updates:
        logger.warning("professionals_crud: Nenhum campo válido para atualizar")
        return False

    # Serializar availability_schedule se presente
    if 'availability_schedule' in valid_updates and isinstance(valid_updates['availability_schedule'], dict):
        valid_updates['availability_schedule'] = json.dumps(valid_updates['availability_schedule'])

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # PRIMEIRO: Verificar se o profissional existe
                check_sql = "SELECT id, instance_id FROM professionals WHERE id = %s"
                await cursor.execute(check_sql, (professional_id,))
                existing = await cursor.fetchone()

                if not existing:
                    logger.warning(f"professionals_crud: [UPDATE] Profissional {professional_id} não existe no banco")
                    return False

                existing_instance = existing.get('instance_id')

                # Tratar caso de instance_id NULL ou diferente
                if existing_instance is None:
                    # Profissional foi criado antes da implementação de multi-tenant
                    # Atualizar o instance_id junto com os outros campos
                    logger.warning(
                        f"professionals_crud: [UPDATE] Profissional {professional_id} tem instance_id NULL. "
                        f"Atualizando para '{instance_id}'"
                    )
                    valid_updates['instance_id'] = instance_id
                elif existing_instance != instance_id:
                    logger.error(
                        f"professionals_crud: [UPDATE] MISMATCH! Profissional {professional_id} "
                        f"pertence à instance '{existing_instance}', mas tentando atualizar com instance '{instance_id}'"
                    )
                    return False

                # Construir SET clause
                set_clauses = [f"{field} = %s" for field in valid_updates.keys()]
                set_sql = ", ".join(set_clauses)

                # Usar apenas o ID na cláusula WHERE (já verificamos a instance acima)
                sql = f"""
                UPDATE professionals
                SET {set_sql}
                WHERE id = %s
                """

                params = list(valid_updates.values()) + [professional_id]
                logger.debug(f"professionals_crud: [UPDATE] SQL: {sql}")
                logger.debug(f"professionals_crud: [UPDATE] Params count: {len(params)}, fields: {list(valid_updates.keys())}")

                await cursor.execute(sql, params)
                await conn.commit()

                if cursor.rowcount > 0:
                    logger.info(f"professionals_crud: Profissional {professional_id} atualizado com sucesso")
                    return True
                else:
                    logger.warning(f"professionals_crud: Profissional {professional_id} não foi atualizado (rowcount=0)")
                    return False
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao atualizar profissional: {e}", exc_info=True)
        return False


async def delete_professional(
    professional_id: int,
    instance_id: Optional[str] = None
) -> bool:
    """Deleta um profissional (soft delete - marca como inativo)."""
    return await update_professional(professional_id, {"is_active": False}, instance_id)


async def hard_delete_professional(
    professional_id: int,
    instance_id: Optional[str] = None
) -> bool:
    """Deleta permanentemente um profissional."""
    if not settings.db_pool:
        logger.error("professionals_crud: Pool de conexão não disponível")
        return False

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "DELETE FROM professionals WHERE id = %s AND instance_id = %s"
                await cursor.execute(sql, (professional_id, instance_id))
                await conn.commit()
                logger.info(f"professionals_crud: Profissional {professional_id} deletado permanentemente")
                return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao deletar profissional: {e}", exc_info=True)
        return False


# ============ Disponibilidade ============

async def get_professional_availability(
    professional_id: int,
    date: datetime,
    instance_id: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Retorna os horários disponíveis de um profissional em uma data específica.

    Returns:
        Lista de slots disponíveis [{"start": "09:00", "end": "09:30"}, ...]
    """
    if not settings.db_pool:
        return []

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        # Buscar profissional
        professional = await get_professional_by_id(professional_id, instance_id)
        if not professional or not professional.get('is_active'):
            return []

        # Obter disponibilidade base do dia
        day_name = date.strftime('%A').lower()
        availability = professional.get('availability_schedule', DEFAULT_AVAILABILITY)
        day_slots = availability.get(day_name, [])

        if not day_slots:
            return []

        # Verificar bloqueios
        blocks = await get_schedule_blocks(professional_id, date, date + timedelta(days=1), instance_id)

        # Buscar agendamentos existentes
        existing_appointments = await get_professional_appointments_for_date(professional_id, date, instance_id)

        # Gerar slots disponíveis
        duration = professional.get('appointment_duration', 30)
        buffer = professional.get('buffer_time', 10)
        available_slots = []

        for slot in day_slots:
            start_time = datetime.strptime(slot['start'], '%H:%M').time()
            end_time = datetime.strptime(slot['end'], '%H:%M').time()

            current = datetime.combine(date.date(), start_time)
            slot_end = datetime.combine(date.date(), end_time)

            while current + timedelta(minutes=duration) <= slot_end:
                slot_start = current
                slot_finish = current + timedelta(minutes=duration)

                # Verificar se não está bloqueado
                is_blocked = any(
                    block['start_datetime'] <= slot_start < block['end_datetime'] or
                    block['start_datetime'] < slot_finish <= block['end_datetime']
                    for block in blocks
                )

                # Verificar se não há agendamento
                is_booked = any(
                    apt['appointment_datetime'] <= slot_start < apt['appointment_datetime'] + timedelta(minutes=duration) or
                    apt['appointment_datetime'] < slot_finish <= apt['appointment_datetime'] + timedelta(minutes=duration)
                    for apt in existing_appointments
                )

                if not is_blocked and not is_booked:
                    available_slots.append({
                        "start": slot_start.strftime('%H:%M'),
                        "end": slot_finish.strftime('%H:%M')
                    })

                current += timedelta(minutes=duration + buffer)

        return available_slots

    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar disponibilidade: {e}", exc_info=True)
        return []


async def get_professional_appointments_for_date(
    professional_id: int,
    date: datetime,
    instance_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Busca agendamentos de um profissional em uma data específica."""
    if not settings.db_pool:
        return []

    instance_id = instance_id or settings.INSTANCE_ID
    start_of_day = datetime.combine(date.date(), time.min)
    end_of_day = datetime.combine(date.date(), time.max)

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT * FROM scheduled_appointments
                WHERE instance_id = %s AND professional_id = %s
                AND appointment_datetime BETWEEN %s AND %s
                AND status NOT IN ('cancelled')
                ORDER BY appointment_datetime
                """
                await cursor.execute(sql, (instance_id, professional_id, start_of_day, end_of_day))
                return await cursor.fetchall()
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar agendamentos do profissional: {e}", exc_info=True)
        return []


# ============ Bloqueios de Agenda ============

async def create_schedule_block(
    professional_id: int,
    start_datetime: datetime,
    end_datetime: datetime,
    block_type: str = 'other',
    title: Optional[str] = None,
    all_day: bool = False,
    notes: Optional[str] = None,
    instance_id: Optional[str] = None
) -> Optional[int]:
    """Cria um bloqueio na agenda do profissional."""
    if not settings.db_pool:
        logger.error("professionals_crud: Pool de conexão não disponível")
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                INSERT INTO professional_schedule_blocks
                (instance_id, professional_id, block_type, title, start_datetime, end_datetime, all_day, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                await cursor.execute(sql, (
                    instance_id, professional_id, block_type, title,
                    start_datetime, end_datetime, all_day, notes
                ))
                await conn.commit()
                return cursor.lastrowid
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao criar bloqueio: {e}", exc_info=True)
        return None


async def get_schedule_blocks(
    professional_id: int,
    start_date: datetime,
    end_date: datetime,
    instance_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Busca bloqueios de agenda de um profissional em um período."""
    if not settings.db_pool:
        return []

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT * FROM professional_schedule_blocks
                WHERE instance_id = %s AND professional_id = %s
                AND (
                    (start_datetime BETWEEN %s AND %s) OR
                    (end_datetime BETWEEN %s AND %s) OR
                    (start_datetime <= %s AND end_datetime >= %s)
                )
                ORDER BY start_datetime
                """
                await cursor.execute(sql, (
                    instance_id, professional_id,
                    start_date, end_date,
                    start_date, end_date,
                    start_date, end_date
                ))
                return await cursor.fetchall()
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar bloqueios: {e}", exc_info=True)
        return []


async def delete_schedule_block(
    block_id: int,
    instance_id: Optional[str] = None
) -> bool:
    """Deleta um bloqueio de agenda."""
    if not settings.db_pool:
        return False

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "DELETE FROM professional_schedule_blocks WHERE id = %s AND instance_id = %s"
                await cursor.execute(sql, (block_id, instance_id))
                await conn.commit()
                return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao deletar bloqueio: {e}", exc_info=True)
        return False


# ============ Serviços ============

async def create_service(
    professional_id: int,
    service_name: str,
    description: Optional[str] = None,
    duration_minutes: int = 30,
    price: Optional[float] = None,
    instance_id: Optional[str] = None
) -> Optional[int]:
    """Cria um serviço para um profissional."""
    if not settings.db_pool:
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                INSERT INTO professional_services
                (instance_id, professional_id, service_name, description, duration_minutes, price)
                VALUES (%s, %s, %s, %s, %s, %s)
                """
                await cursor.execute(sql, (
                    instance_id, professional_id, service_name,
                    description, duration_minutes, price
                ))
                await conn.commit()
                return cursor.lastrowid
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao criar serviço: {e}", exc_info=True)
        return None


async def get_professional_services(
    professional_id: int,
    instance_id: Optional[str] = None,
    active_only: bool = True
) -> List[Dict[str, Any]]:
    """Busca serviços de um profissional."""
    if not settings.db_pool:
        return []

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT * FROM professional_services
                WHERE instance_id = %s AND professional_id = %s
                """
                params = [instance_id, professional_id]

                if active_only:
                    sql += " AND is_active = TRUE"

                sql += " ORDER BY service_name"
                await cursor.execute(sql, params)
                return await cursor.fetchall()
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar serviços: {e}", exc_info=True)
        return []


# ============ Estatísticas ============

async def get_professionals_stats(instance_id: Optional[str] = None) -> Dict[str, Any]:
    """Retorna estatísticas de profissionais."""
    if not settings.db_pool:
        return {}

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                stats = {}

                # Total de profissionais
                await cursor.execute(
                    "SELECT COUNT(*) as total FROM professionals WHERE instance_id = %s",
                    (instance_id,)
                )
                result = await cursor.fetchone()
                stats['total'] = result['total'] if result else 0

                # Profissionais ativos
                await cursor.execute(
                    "SELECT COUNT(*) as count FROM professionals WHERE instance_id = %s AND is_active = TRUE",
                    (instance_id,)
                )
                result = await cursor.fetchone()
                stats['active'] = result['count'] if result else 0

                # Por especialidade
                await cursor.execute("""
                    SELECT specialty, COUNT(*) as count
                    FROM professionals
                    WHERE instance_id = %s AND is_active = TRUE AND specialty IS NOT NULL
                    GROUP BY specialty
                    ORDER BY count DESC
                """, (instance_id,))
                specialty_counts = await cursor.fetchall()
                stats['by_specialty'] = {row['specialty']: row['count'] for row in specialty_counts}

                # Salas em uso
                await cursor.execute("""
                    SELECT COUNT(DISTINCT room_name) as count
                    FROM professionals
                    WHERE instance_id = %s AND is_active = TRUE AND room_name IS NOT NULL
                """, (instance_id,))
                result = await cursor.fetchone()
                stats['rooms_in_use'] = result['count'] if result else 0

                return stats
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar estatísticas: {e}", exc_info=True)
        return {}


# ============ Utilitários ============

async def get_all_specialties(instance_id: Optional[str] = None) -> List[str]:
    """Retorna lista de todas as especialidades cadastradas."""
    if not settings.db_pool:
        return []

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("""
                    SELECT DISTINCT specialty FROM professionals
                    WHERE instance_id = %s AND specialty IS NOT NULL
                    ORDER BY specialty
                """, (instance_id,))
                results = await cursor.fetchall()
                return [row['specialty'] for row in results]
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar especialidades: {e}", exc_info=True)
        return []


async def get_all_rooms(instance_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retorna lista de todas as salas cadastradas."""
    if not settings.db_pool:
        return []

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("""
                    SELECT DISTINCT room_name, room_number FROM professionals
                    WHERE instance_id = %s AND room_name IS NOT NULL AND is_active = TRUE
                    ORDER BY room_name
                """, (instance_id,))
                return await cursor.fetchall()
    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar salas: {e}", exc_info=True)
        return []


# ============ Professional Google OAuth CRUD ============

async def save_professional_oauth(
    professional_id: int,
    google_email: str,
    access_token: str,
    refresh_token: str,
    token_expiry: Optional[datetime] = None,
    scopes: Optional[str] = None,
    calendar_id: str = 'primary',
    instance_id: Optional[str] = None
) -> Optional[int]:
    """
    Salva ou atualiza credenciais OAuth do profissional.
    Usa UPSERT para atualizar se já existir.

    Returns:
        ID do registro criado/atualizado ou None se falhar
    """
    if not settings.db_pool:
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                INSERT INTO professional_google_oauth
                (instance_id, professional_id, google_email, calendar_id,
                 access_token, refresh_token, token_expiry, scopes, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                ON DUPLICATE KEY UPDATE
                    google_email = VALUES(google_email),
                    calendar_id = VALUES(calendar_id),
                    access_token = VALUES(access_token),
                    refresh_token = VALUES(refresh_token),
                    token_expiry = VALUES(token_expiry),
                    scopes = VALUES(scopes),
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                """
                await cursor.execute(sql, (
                    instance_id, professional_id, google_email, calendar_id,
                    access_token, refresh_token, token_expiry, scopes
                ))
                await conn.commit()

                # Retorna o ID do registro
                if cursor.lastrowid:
                    return cursor.lastrowid

                # Se foi UPDATE, busca o ID existente
                await cursor.execute(
                    """SELECT id FROM professional_google_oauth
                       WHERE instance_id = %s AND professional_id = %s""",
                    (instance_id, professional_id)
                )
                result = await cursor.fetchone()
                return result['id'] if result else None

    except Exception as e:
        logger.error(f"professionals_crud: Erro ao salvar OAuth: {e}", exc_info=True)
        return None


async def get_professional_oauth(
    professional_id: int,
    instance_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Busca credenciais OAuth de um profissional.

    Returns:
        Dict com credenciais ou None se não encontrar
    """
    if not settings.db_pool:
        return None

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT * FROM professional_google_oauth
                WHERE instance_id = %s AND professional_id = %s AND is_active = TRUE
                """
                await cursor.execute(sql, (instance_id, professional_id))
                result = await cursor.fetchone()

                if result:
                    # Converter datetime para string se necessário
                    if result.get('token_expiry'):
                        result['token_expiry'] = result['token_expiry'].isoformat()
                    if result.get('created_at'):
                        result['created_at'] = result['created_at'].isoformat()
                    if result.get('updated_at'):
                        result['updated_at'] = result['updated_at'].isoformat()

                return result

    except Exception as e:
        logger.error(f"professionals_crud: Erro ao buscar OAuth: {e}", exc_info=True)
        return None


async def delete_professional_oauth(
    professional_id: int,
    instance_id: Optional[str] = None
) -> bool:
    """
    Remove/desativa credenciais OAuth de um profissional.

    Returns:
        True se removido com sucesso
    """
    if not settings.db_pool:
        return False

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Soft delete - apenas desativa
                sql = """
                UPDATE professional_google_oauth
                SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE instance_id = %s AND professional_id = %s
                """
                await cursor.execute(sql, (instance_id, professional_id))
                await conn.commit()
                return cursor.rowcount > 0

    except Exception as e:
        logger.error(f"professionals_crud: Erro ao deletar OAuth: {e}", exc_info=True)
        return False


async def update_professional_oauth_token(
    professional_id: int,
    access_token: str,
    token_expiry: Optional[datetime] = None,
    instance_id: Optional[str] = None
) -> bool:
    """
    Atualiza apenas o access_token (após refresh).

    Returns:
        True se atualizado com sucesso
    """
    if not settings.db_pool:
        return False

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                UPDATE professional_google_oauth
                SET access_token = %s, token_expiry = %s, updated_at = CURRENT_TIMESTAMP
                WHERE instance_id = %s AND professional_id = %s AND is_active = TRUE
                """
                await cursor.execute(sql, (
                    access_token, token_expiry, instance_id, professional_id
                ))
                await conn.commit()
                return cursor.rowcount > 0

    except Exception as e:
        logger.error(f"professionals_crud: Erro ao atualizar token OAuth: {e}", exc_info=True)
        return False


async def is_professional_google_connected(
    professional_id: int,
    instance_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Verifica se profissional tem Google Calendar conectado.

    Returns:
        Dict com status da conexão
    """
    if not settings.db_pool:
        return {"is_connected": False, "email": None}

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT google_email, calendar_id, token_expiry, updated_at
                FROM professional_google_oauth
                WHERE instance_id = %s AND professional_id = %s AND is_active = TRUE
                """
                await cursor.execute(sql, (instance_id, professional_id))
                result = await cursor.fetchone()

                if result:
                    return {
                        "is_connected": True,
                        "email": result['google_email'],
                        "calendar_id": result['calendar_id'],
                        "last_updated": result['updated_at'].isoformat() if result.get('updated_at') else None
                    }

                return {"is_connected": False, "email": None}

    except Exception as e:
        logger.error(f"professionals_crud: Erro ao verificar conexão Google: {e}", exc_info=True)
        return {"is_connected": False, "email": None}


async def get_all_connected_professionals(
    instance_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retorna lista de todos os profissionais com Google Calendar conectado.

    Returns:
        Lista de profissionais com seus dados de conexão
    """
    if not settings.db_pool:
        return []

    instance_id = instance_id or settings.INSTANCE_ID

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                SELECT p.id, p.name, p.specialty, p.email,
                       o.google_email, o.calendar_id, o.updated_at as oauth_updated
                FROM professionals p
                INNER JOIN professional_google_oauth o ON p.id = o.professional_id
                WHERE p.instance_id = %s AND o.instance_id = %s
                AND p.is_active = TRUE AND o.is_active = TRUE
                ORDER BY p.name
                """
                await cursor.execute(sql, (instance_id, instance_id))
                results = await cursor.fetchall()

                # Converter datetimes
                for row in results:
                    if row.get('oauth_updated'):
                        row['oauth_updated'] = row['oauth_updated'].isoformat()

                return results

    except Exception as e:
        logger.error(f"professionals_crud: Erro ao listar profissionais conectados: {e}", exc_info=True)
        return []


logger.info("professionals_crud.py: Módulo carregado")
