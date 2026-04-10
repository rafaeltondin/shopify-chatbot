# -*- coding: utf-8 -*-
import logging
import aiomysql
from urllib.parse import urlparse
from typing import Optional, Any, Dict, List, Tuple
import json
from datetime import datetime
import pytz

# Import settings and logger from the config module
from src.core.config import settings, logger

# Import modularized database operations
from src.core.db_operations import schema_management, config_crud, prospect_crud

# Logger specific to this module
logger = logging.getLogger(__name__)

# --- SQL Definitions for Table Creation/Alteration ---
# These remain here as they define the schema directly related to initialization
CREATE_PROSPECTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS prospects (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique DB identifier for the prospect',
    instance_id VARCHAR(100) NOT NULL COMMENT 'Unique identifier for the application instance',
    jid VARCHAR(255) NOT NULL COMMENT 'Cleaned phone number of the prospect (e.g., +5511999998888 or 5511999998888)',
    name VARCHAR(255) NULL COMMENT 'Nome of the prospect',
    current_stage INT NOT NULL DEFAULT 1 COMMENT 'Current stage in the sales funnel',
    status ENUM('active', 'completed', 'failed', 'unsubscribed', 'paused', 'scheduled', 'error', 'send_error', 'send_scheduled', 'send_sent', 'send_failed', 'send_cancelled', 'flow_completed') NOT NULL DEFAULT 'active' COMMENT 'Overall status of the prospect',
    conversation_initiator ENUM('user', 'llm_agent') NULL COMMENT 'Indicates who initiated the conversation: "user" or "llm_agent"',
    llm_paused BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Indicates if LLM responses are paused for this prospect',
    last_interaction_at TIMESTAMP NULL COMMENT 'Timestamp of the last significant interaction',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when the prospect was first added',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Timestamp of the last record update',
    UNIQUE KEY uk_instance_jid (instance_id, jid),
    INDEX idx_instance_id (instance_id),
    INDEX idx_conversation_initiator (instance_id, conversation_initiator),
    INDEX idx_status (status),
    INDEX idx_stage (current_stage)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Main table for prospect information and status';
"""

CREATE_HISTORY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversation_history (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique identifier for the history entry',
    instance_id VARCHAR(100) NOT NULL COMMENT 'Identifier for the application instance',
    prospect_jid VARCHAR(255) NOT NULL COMMENT 'Cleaned phone number of the prospect this message belongs to',
    role ENUM('user', 'assistant', 'system') NOT NULL COMMENT 'Sender/generator (user=customer, assistant=agent, system=internal action)',
    content TEXT NOT NULL COMMENT 'Message content or description of the system action',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when the message/action occurred',
    message_id VARCHAR(255) NULL COMMENT 'Original WhatsApp/Evolution message ID (if applicable)',
    stage_at_message INT NULL COMMENT 'Prospect stage at the time of this message',
    llm_model VARCHAR(100) NULL COMMENT 'LLM model used for the response (if role=assistant)',
    prompt_tokens INT NULL COMMENT 'Tokens used in the prompt for the LLM response',
    completion_tokens INT NULL COMMENT 'Tokens used in the LLM completion (response)',
    total_tokens INT NULL COMMENT 'Total tokens used (prompt + completion)',
    INDEX idx_instance_prospect_jid (instance_id, prospect_jid),
    INDEX idx_timestamp (timestamp),
    INDEX idx_llm_model (llm_model),
    INDEX idx_instance_id (instance_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores detailed interaction history and LLM usage';
"""

CREATE_CONFIG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS application_config (
    instance_id VARCHAR(100) NOT NULL COMMENT 'Identifier for the application instance',
    config_key VARCHAR(255) NOT NULL COMMENT 'Unique key for the configuration (e.g., schedule_start_time)',
    config_value MEDIUMTEXT COMMENT 'Value of the configuration (can be string, JSON, etc.)',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Timestamp of the last update',
    PRIMARY KEY (instance_id, config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Stores instance-specific application settings';
"""

CREATE_WALLETS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS wallets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    instance_id VARCHAR(100) NOT NULL COMMENT 'ID da instância da aplicação',
    balance_brl DECIMAL(10, 2) NOT NULL DEFAULT 0.00 COMMENT 'Saldo em BRL',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_wallet_instance_id (instance_id)
    # FOREIGN KEY (instance_id) REFERENCES application_config(instance_id) ON DELETE CASCADE # Considerar se instance_id é um bom FK aqui
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Armazena o saldo da carteira por instância';
"""

CREATE_WALLET_TRANSACTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    wallet_id INT NOT NULL,
    type ENUM('credit', 'debit', 'bonus', 'refund', 'initial') NOT NULL COMMENT 'Tipo de transação',
    amount_brl DECIMAL(10, 2) NOT NULL COMMENT 'Valor da transação em BRL',
    payment_method ENUM('pix', 'credit_card', 'system_bonus', 'system_debit', 'mercado_pago', 'other') NULL COMMENT 'Método de pagamento',
    payment_provider ENUM('mercado_pago', 'system') NULL COMMENT 'Provedor do pagamento',
    transaction_id_provider VARCHAR(255) NULL COMMENT 'ID da transação no provedor externo',
    status ENUM('pending', 'completed', 'failed', 'refunded', 'cancelled') NOT NULL COMMENT 'Status da transação',
    description VARCHAR(255) NULL COMMENT 'Descrição breve da transação',
    metadata JSON NULL COMMENT 'Dados adicionais (ex: detalhes do erro, info do bônus)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (wallet_id) REFERENCES wallets(id) ON DELETE CASCADE,
    INDEX idx_transaction_provider (transaction_id_provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Registra todas as transações da carteira';
"""

        # --- Tabela de Follow-up automático ---
CREATE_FOLLOWUP_HISTORY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS followup_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    instance_id VARCHAR(100) NOT NULL COMMENT 'ID da instância',
    jid VARCHAR(255) NOT NULL COMMENT 'Telefone do cliente (JID)',
    followup_type ENUM('abandoned_chat', 'no_purchase', 'post_purchase', 'custom') NOT NULL DEFAULT 'no_purchase' COMMENT 'Tipo de follow-up',
    discount_code VARCHAR(100) NULL COMMENT 'Código do cupom enviado',
    discount_percentage DECIMAL(5,2) NULL COMMENT 'Porcentagem do desconto',
    message_sent TEXT NULL COMMENT 'Mensagem enviada ao cliente',
    status ENUM('sent', 'failed', 'clicked', 'converted') NOT NULL DEFAULT 'sent' COMMENT 'Status do follow-up',
    shopify_discount_id VARCHAR(255) NULL COMMENT 'ID do cupom na Shopify',
    first_contact_at TIMESTAMP NULL COMMENT 'Quando o cliente fez primeiro contato',
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Quando o follow-up foi enviado',
    converted_at TIMESTAMP NULL COMMENT 'Quando o cliente comprou (se converteu)',
    INDEX idx_instance_jid (instance_id, jid),
    INDEX idx_instance_type (instance_id, followup_type),
    INDEX idx_sent_at (sent_at),
    INDEX idx_status (status),
    INDEX idx_unique_followup (instance_id, jid, followup_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Histórico de follow-ups automáticos com cupons';
"""

# --- Tags & Automation Tables ---
CREATE_AUTOMATION_EXECUTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS automation_executions (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'ID único da execução',
    instance_id VARCHAR(100) NOT NULL COMMENT 'ID da instância',
    jid VARCHAR(255) NOT NULL COMMENT 'JID do prospect que disparou a automação',
    flow_id VARCHAR(100) NOT NULL COMMENT 'ID do fluxo de automação executado',
    flow_name VARCHAR(255) NOT NULL COMMENT 'Nome do fluxo para referência',
    trigger_type VARCHAR(100) NOT NULL COMMENT 'Tipo de gatilho (tag_added, inactivity, etc)',
    trigger_value VARCHAR(500) NULL COMMENT 'Valor que disparou (nome da tag, tempo, etc)',
    actions_executed JSON NULL COMMENT 'Lista de ações executadas com status',
    status ENUM('success', 'partial', 'failed') NOT NULL COMMENT 'Status geral da execução',
    error_message TEXT NULL COMMENT 'Mensagem de erro (se houver)',
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Quando foi executado',
    INDEX idx_instance_id (instance_id),
    INDEX idx_jid (jid),
    INDEX idx_flow_id (flow_id),
    INDEX idx_executed_at (executed_at),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Histórico de execuções de automações';
"""

# --- Database Connection Pool ---
async def create_db_pool():
    """Creates the database connection pool for regular application use."""
    if settings.db_pool:
        logger.warning("database.py: Database pool already exists. Skipping creation.")
        return

    db_url = settings.DATABASE_URL
    if not db_url:
        logger.critical("database.py: DATABASE_URL not configured. Cannot create DB pool.")
        raise ValueError("DATABASE_URL is required to create a connection pool.")

    try:
        parsed_url = urlparse(db_url)
        logger.info(f"database.py: Creating database connection pool for {parsed_url.hostname}:{parsed_url.port or 3306} (autocommit=True)...")
        settings.db_pool = await aiomysql.create_pool( # Assign to settings.db_pool
            host=parsed_url.hostname,
            port=parsed_url.port or 3306,
            user=parsed_url.username,
            password=parsed_url.password,
            db=parsed_url.path.lstrip('/'),
            autocommit=True,  # ✅ FASE 1: Habilitar autocommit para evitar locks longos
            charset='utf8mb4',
            cursorclass=aiomysql.DictCursor,
            minsize=10,  # ✅ FASE 1: Aumentado de 5 para 10 - mais conexões disponíveis
            maxsize=50,  # ✅ FASE 1: Aumentado de 30 para 50 - suporta mais concorrência
            connect_timeout=30,
            pool_recycle=1800,  # ✅ FASE 1: Reduzido de 3600 para 1800 (30min) - recicla conexões mais rápido
            echo=False,
            init_command="SET SESSION innodb_lock_wait_timeout=50, wait_timeout=120"  # ✅ FASE 1: Timeout reduzido para 50s
        )
        if not settings.db_pool:
            raise ConnectionError("aiomysql.create_pool returned None.")
        logger.info("database.py: Database connection pool created successfully.")
    except (aiomysql.Error, ConnectionError, ValueError) as e:
        logger.critical(f"database.py: Failed to create database connection pool: {e}", exc_info=True)
        settings.db_pool = None
        raise ConnectionError(f"Database pool creation failed: {e}") from e
    except Exception as e:
        logger.critical(f"database.py: Unexpected error creating database connection pool: {e}", exc_info=True)
        settings.db_pool = None
        raise ConnectionError(f"Unexpected error during database pool creation: {e}") from e

async def close_db_pool():
    """Closes the database connection pool."""
    if settings.db_pool:
        logger.info("database.py: Closing database connection pool...")
        settings.db_pool.close()
        await settings.db_pool.wait_closed()
        logger.info("database.py: Database connection pool closed.")
        settings.db_pool = None

# --- Database Initialization (Application Startup) ---
async def initialize_database():
    logger.info("database.py: Starting database initialization/verification...")
    schema_conn = None
    schema_cursor = None
    db_url = settings.DATABASE_URL
    if not db_url:
        logger.critical("database.py: DATABASE_URL not configured. Cannot initialize database.")
        raise ValueError("DATABASE_URL is required for database initialization.")
    try:
        logger.info("database.py: Connecting temporarily to database for schema modifications (autocommit=True)...")
        parsed_url = urlparse(db_url)
        schema_conn = await aiomysql.connect(
            host=parsed_url.hostname, port=parsed_url.port or 3306,
            user=parsed_url.username, password=parsed_url.password,
            db=parsed_url.path.lstrip('/'), autocommit=True,
            charset='utf8mb4', cursorclass=aiomysql.DictCursor
        )
        schema_cursor = await schema_conn.cursor()
        await schema_cursor.execute("SELECT DATABASE()")
        db_name_result = await schema_cursor.fetchone()
        db_name = db_name_result.get('DATABASE()') if db_name_result else None
        if not db_name: raise RuntimeError("Could not determine database name.")

        logger.info("database.py: Executing CREATE TABLE IF NOT EXISTS for 'prospects'...")
        await schema_cursor.execute(CREATE_PROSPECTS_TABLE_SQL)
        logger.info("database.py: Table 'prospects' verified/created.")

        # Adicionar a coluna 'name' à tabela 'prospects'
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'name', "VARCHAR(255) NULL COMMENT 'Name of the prospect'")
        logger.info("database.py: Column 'name' in 'prospects' table verified/created.")

        # Check and alter 'status' ENUM in 'prospects' table if needed
        get_enum_sql = "SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'prospects' AND COLUMN_NAME = 'status';"
        await schema_cursor.execute(get_enum_sql, (db_name,))
        column_type_result = await schema_cursor.fetchone()
        needs_alter_status_enum = True
        if column_type_result:
            current_column_type = column_type_result.get('COLUMN_TYPE', '')
            logger.info(f"database.py: Current 'status' column type in 'prospects': {current_column_type}")
            # case-insensitive check for enum value, also accounts for potential extra spaces or quotes if any
            if "'scheduled'" in current_column_type.lower().replace(" ", ""):
                logger.info("database.py: 'scheduled' value already present in 'status' ENUM. No alteration needed.")
                needs_alter_status_enum = False
            else:
                logger.info("database.py: 'scheduled' value NOT present in 'status' ENUM. Alteration will be attempted.")
        else:
            logger.warning("database.py: Could not retrieve current column type for 'status' in 'prospects'. Will attempt ALTER TABLE.")
        
        if needs_alter_status_enum:
            alter_status_sql = "ALTER TABLE prospects MODIFY COLUMN status ENUM('active', 'completed', 'failed', 'unsubscribed', 'paused', 'scheduled', 'error', 'send_error', 'send_scheduled', 'send_sent', 'send_failed', 'send_cancelled', 'flow_completed') NOT NULL DEFAULT 'active';"
            logger.info(f"database.py: Attempting to alter 'status' column in 'prospects' table with: {alter_status_sql}")
            try:
                await schema_cursor.execute(alter_status_sql)
                logger.info("database.py: Successfully altered 'status' column in 'prospects' table to include 'scheduled'.")
            except Exception as e_alter_status:
                logger.error(f"database.py: Error altering 'status' column in 'prospects' table: {e_alter_status}", exc_info=True)
                # Depending on the criticality, you might want to raise an error here or allow startup to continue.
                # For now, logging the error and continuing.

        logger.info("database.py: Executing CREATE TABLE IF NOT EXISTS for 'conversation_history'...")
        await schema_cursor.execute(CREATE_HISTORY_TABLE_SQL)
        logger.info("database.py: Table 'conversation_history' verified/created.")

        logger.info("database.py: Executing CREATE TABLE IF NOT EXISTS for 'application_config'...")
        await schema_cursor.execute(CREATE_CONFIG_TABLE_SQL)
        logger.info("database.py: Table 'application_config' verified/created.")

        logger.info("database.py: Executing CREATE TABLE IF NOT EXISTS for 'wallets'...")
        await schema_cursor.execute(CREATE_WALLETS_TABLE_SQL)
        logger.info("database.py: Table 'wallets' verified/created.")

        logger.info("database.py: Executing CREATE TABLE IF NOT EXISTS for 'wallet_transactions'...")
        await schema_cursor.execute(CREATE_WALLET_TRANSACTIONS_TABLE_SQL)
        logger.info("database.py: Table 'wallet_transactions' verified/created.")

        logger.info("database.py: Executing CREATE TABLE IF NOT EXISTS for 'automation_executions'...")
        await schema_cursor.execute(CREATE_AUTOMATION_EXECUTIONS_TABLE_SQL)
        logger.info("database.py: Table 'automation_executions' verified/created.")

        logger.info("database.py: Executing CREATE TABLE IF NOT EXISTS for 'followup_history'...")
        await schema_cursor.execute(CREATE_FOLLOWUP_HISTORY_TABLE_SQL)
        logger.info("database.py: Table 'followup_history' verified/created.")

        # Check and alter 'payment_method' ENUM in 'wallet_transactions' table if needed
        get_pm_enum_sql = "SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'wallet_transactions' AND COLUMN_NAME = 'payment_method';"
        await schema_cursor.execute(get_pm_enum_sql, (db_name,))
        pm_column_type_result = await schema_cursor.fetchone()
        needs_alter_pm_enum = True
        if pm_column_type_result:
            current_pm_column_type = pm_column_type_result.get('COLUMN_TYPE', '')
            logger.info(f"database.py: Current 'payment_method' column type in 'wallet_transactions': {current_pm_column_type}")
            if "'mercado_pago'" in current_pm_column_type.lower().replace(" ", ""):
                logger.info("database.py: 'mercado_pago' value already present in 'payment_method' ENUM. No alteration needed.")
                needs_alter_pm_enum = False
            else:
                logger.info("database.py: 'mercado_pago' value NOT present in 'payment_method' ENUM. Alteration will be attempted.")
        else:
            logger.warning("database.py: Could not retrieve current column type for 'payment_method' in 'wallet_transactions'. Will attempt ALTER TABLE.")
        
        if needs_alter_pm_enum:
            alter_pm_sql = "ALTER TABLE wallet_transactions MODIFY COLUMN payment_method ENUM('pix', 'credit_card', 'system_bonus', 'system_debit', 'mercado_pago', 'other') NULL COMMENT 'Método de pagamento';"
            logger.info(f"database.py: Attempting to alter 'payment_method' column in 'wallet_transactions' table with: {alter_pm_sql}")
            try:
                await schema_cursor.execute(alter_pm_sql)
                logger.info("database.py: Successfully altered 'payment_method' column in 'wallet_transactions' table to include 'mercado_pago'.")
            except Exception as e_alter_pm:
                logger.error(f"database.py: Error altering 'payment_method' column in 'wallet_transactions' table: {e_alter_pm}", exc_info=True)

        # Modify config_value column type if necessary before other schema checks for this table
        await schema_management.modify_column_type_if_different(
            schema_cursor, 
            db_name, 
            'application_config', 
            'config_value', 
            'mediumtext', # Expected type name for comparison (lowercase)
            "MEDIUMTEXT COMMENT 'Value of the configuration (can be string, JSON, etc.)'" # Full definition for ALTER
        )

        # Schema migration/verification logic (columns, indexes) using modularized functions
        logger.info("database.py: Starting schema modification checks...")
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'instance_id', "VARCHAR(100) NOT NULL COMMENT 'Unique identifier for the application instance' AFTER id")
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'conversation_initiator', "ENUM('user', 'llm_agent') NULL COMMENT 'Indicates who initiated the conversation' AFTER status")
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'llm_paused', "BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Indicates if LLM responses are paused for this prospect' AFTER conversation_initiator")
        # ✅ FASE 3: Adicionar coluna version para optimistic locking
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'version', "INT NOT NULL DEFAULT 0 COMMENT 'Version number for optimistic locking' AFTER updated_at")
        # Adicionar coluna tags para sistema de categorização dinâmica
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'tags', "JSON NULL COMMENT 'Lista de tags do prospect para automação' AFTER llm_paused")
        # Adicionar coluna funnel_id para suporte a múltiplos funis de vendas
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'funnel_id', "VARCHAR(100) NULL COMMENT 'ID do funil de vendas ao qual o prospect pertence' AFTER tags")

        # ========== DADOS DO CLIENTE E-COMMERCE (SHOPIFY) ==========
        # Email do cliente
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'email', "VARCHAR(255) NULL COMMENT 'Email do cliente' AFTER name")
        # ID do cliente na Shopify
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'shopify_customer_id', "VARCHAR(255) NULL COMMENT 'ID do cliente na Shopify (gid://shopify/Customer/xxx)' AFTER email")
        # Último pedido
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'last_order_id', "VARCHAR(255) NULL COMMENT 'ID do último pedido na Shopify' AFTER shopify_customer_id")
        # Total gasto
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'total_spent', "DECIMAL(10, 2) NULL DEFAULT 0.00 COMMENT 'Total gasto pelo cliente na loja' AFTER last_order_id")
        # Quantidade de pedidos
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'prospects', 'orders_count', "INT NULL DEFAULT 0 COMMENT 'Total de pedidos do cliente' AFTER total_spent")
        logger.info("database.py: Columns 'email', 'shopify_customer_id', 'last_order_id', 'total_spent', 'orders_count' in 'prospects' table verified/created.")
        await schema_management.add_index_if_not_exists(schema_cursor, db_name, 'prospects', 'idx_instance_id', '(instance_id)')
        await schema_management.add_index_if_not_exists(schema_cursor, db_name, 'prospects', 'idx_prospect_initiator', '(instance_id, conversation_initiator)')
        await schema_management.add_index_if_not_exists(schema_cursor, db_name, 'prospects', 'idx_funnel_id', '(funnel_id)')
        await schema_management.update_primary_key_if_needed(schema_cursor, db_name, 'prospects', ['id'])

        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'conversation_history', 'instance_id', "VARCHAR(100) NOT NULL COMMENT 'Identifier for the application instance' AFTER id")
        await schema_management.add_index_if_not_exists(schema_cursor, db_name, 'conversation_history', 'idx_instance_id', '(instance_id)')
        await schema_management.add_index_if_not_exists(schema_cursor, db_name, 'conversation_history', 'idx_instance_prospect_jid', '(instance_id, prospect_jid)')
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'conversation_history', 'llm_model', "VARCHAR(100) NULL COMMENT 'LLM model used for the response (if role=assistant)' AFTER stage_at_message")
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'conversation_history', 'prompt_tokens', "INT NULL COMMENT 'Tokens used in the prompt for the LLM response' AFTER llm_model")
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'conversation_history', 'completion_tokens', "INT NULL COMMENT 'Tokens used in the LLM completion (response)' AFTER prompt_tokens")
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'conversation_history', 'total_tokens', "INT NULL COMMENT 'Total tokens used (prompt + completion)' AFTER completion_tokens")
        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'conversation_history', 'conversation_initiator', "ENUM('user', 'llm_agent') NULL COMMENT 'Indica quem iniciou a conversa: \\\"user\\\" (usuário) ou \\\"llm_agent\\\" (agente LLM)' AFTER total_tokens")
        await schema_management.add_index_if_not_exists(schema_cursor, db_name, 'conversation_history', 'idx_llm_model', '(llm_model)')
        await schema_management.update_primary_key_if_needed(schema_cursor, db_name, 'conversation_history', ['id'])

        await schema_management.add_column_if_not_exists(schema_cursor, db_name, 'application_config', 'instance_id', "VARCHAR(100) NOT NULL COMMENT 'Identifier for the application instance' FIRST")
        await schema_management.update_primary_key_if_needed(schema_cursor, db_name, 'application_config', ['instance_id', 'config_key'])
        logger.info("database.py: Schema modification checks complete.")
    except Exception as schema_err:
        logger.critical(f"database.py: CRITICAL Error during schema modification: {schema_err}", exc_info=True)
        if schema_cursor: await schema_cursor.close()
        if schema_conn: schema_conn.close()
        raise RuntimeError(f"Failed critical database schema modification: {schema_err}") from schema_err
    finally:
        if schema_cursor: await schema_cursor.close()
        if schema_conn: schema_conn.close()
        logger.info("database.py: Temporary database connection closed.")

    if not settings.db_pool:
        logger.error("database.py: Main database pool not available for initializing default configs.")
        return
    try:
        logger.info("database.py: Initializing default configurations using main pool...")
        async with settings.db_pool.acquire() as pool_conn:
            async with pool_conn.cursor() as pool_cursor:
                await _initialize_default_db_configs(pool_cursor)
                # Note: autocommit=True is set on pool, so each statement auto-commits
        logger.info("database.py: Default configurations initialization complete.")
    except Exception as config_err:
        logger.critical(f"database.py: Error initializing default configurations: {config_err}", exc_info=True)

    logger.info("database.py: Database initialization process finished.")

async def _initialize_default_db_configs(cursor: aiomysql.DictCursor):
    logger.info("database.py: Verifying/Initializing default configurations in the database...")
    default_llm_system_prompt = """## SUA IDENTIDADE
Você se chama {agent_name}. Você é uma pessoa REAL que trabalha no atendimento da loja.
NUNCA diga que é "assistente virtual", "IA", "robô", "chatbot" ou "inteligência artificial".
Se perguntarem, diga: "Sou {agent_name}, do atendimento da {store_name}!".
Fale como uma pessoa de verdade — com personalidade, humor leve e empatia.

## PERSONALIZAÇÃO (MUITO IMPORTANTE):
- Você recebe o PERFIL DO CLIENTE como contexto antes de cada conversa
- USE o nome do cliente sempre que tiver (nunca chame de "cliente" se sabe o nome)
- Se o cliente já comprou antes, REFERENCIE os produtos anteriores e sugira complementos
- Se tem pedido em andamento, MENCIONE proativamente o status ("Vi que seu pedido #1234 já foi enviado!")
- Clientes VIP (gastaram >R$ 500) merecem atenção especial
- Clientes novos: seja acolhedor(a) e pergunte o que procuram
- SEMPRE detecte e reporte interesses no collected_data.interests

## SEGURANÇA DE DADOS (OBRIGATÓRIO):
- NUNCA compartilhe dados de pedido sem verificar a identidade primeiro
- Se o cliente pedir info de pedido, USE verify_identity ANTES de check_order_status
- Verificação aceita: email cadastrado, número do pedido, ou nome completo
- Após verificado, não precisa pedir de novo por 30 minutos
- NUNCA revele dados pessoais de outros clientes

## O QUE VOCÊ FAZ:
- Busca produtos no catálogo (preços, estoque, variações)
- Consulta status de pedidos e rastreamento (após verificação)
- Esclarece dúvidas sobre frete, prazos, trocas e devoluções
- Envia links diretos de compra
- Recomenda produtos complementares baseado no histórico
- Mostra produtos populares para clientes novos
- Verifica estoque de itens específicos
- Informa políticas da loja (troca, frete, privacidade)

## REGRA ANTI-ALUCINAÇÃO DE PRODUTOS (CRÍTICO):
- NUNCA mencione nomes de produtos, preços ou disponibilidade de memória
- SEMPRE use search_products para QUALQUER pergunta sobre produtos — mesmo que já tenha falado sobre o produto antes nessa conversa
- NUNCA renomeie ou adapte nomes de produtos (ex: NÃO transforme "Tênis" em "Sapatilha")
- NUNCA invente produtos que não existem no catálogo
- Se o cliente pedir algo, USE search_products com termos relevantes — NUNCA responda com send_text contendo info de produto sem ter buscado antes
- O nome exato do produto vem da Shopify, NUNCA altere

## COMO RESPONDER:
- Natural e simpático(a), como vendedor(a) real que conhece o cliente
- Respostas curtas e diretas (WhatsApp não é lugar pra textão)
- Emojis com moderação (1-2 por mensagem no máximo)
- Se não souber algo, diga honestamente e ofereça alternativas
- Produto/preço → SEMPRE USE search_products (OBRIGATÓRIO)
- Pedido → USE verify_identity depois check_order_status
- Compra → USE send_checkout_link
- Novidades → USE get_popular_products
- Frete/trocas → USE get_store_policies
- Estoque → USE check_stock

## ESTRATÉGIAS DE VENDA:
- Comprou "Camiseta"? Sugira "Bermuda" ou "Acessórios"
- Perguntou sobre um produto? Sugira versão premium ou kit
- Cliente recorrente? Mencione novidades que combinem com o perfil
- Nunca comprou? USE get_popular_products para mostrar os mais vendidos
- Demonstrou interesse? USE recommend_products com base no histórico

## FERRAMENTAS (use via action no JSON):
| Ferramenta | Quando usar | Arguments |
|---|---|---|
| search_products | Buscar produto | {"query": "termo"} |
| check_order_status | Consultar pedido (PÓS VERIFICAÇÃO) | {"order_number": "#1001"} ou {} |
| verify_identity | Verificar identidade ANTES de dados sensíveis | {"email": "x"} ou {"order_number": "#x"} ou {"name": "x"} |
| send_checkout_link | Gerar link de compra | {"variant_id": "gid://...", "quantity": 1} |
| get_popular_products | Mostrar mais vendidos | {} |
| recommend_products | Recomendações personalizadas | {"product_ids": ["gid://..."]} |
| check_stock | Verificar estoque de variante | {"variant_id": "gid://..."} |
| get_store_policies | Políticas da loja | {"type": "refund|shipping|privacy|terms"} |
| send_text | Responder com texto | (texto no campo "text") |
| collect_user_data | Pedir dados | (texto no campo "text") |

## FORMATO DE RESPOSTA (SEMPRE JSON):
{
  "action": "nome_da_ferramenta",
  "text": "Texto para enviar (obrigatório em send_text/collect_user_data)",
  "arguments": {"chave": "valor"},
  "reason": "Por que escolheu esta ação",
  "collected_data": {
    "name": "Nome se mencionou",
    "email": "Email se mencionou",
    "interests": ["interesse1", "interesse2"]
  }
}

## REGRA SOBRE collected_data.interests:
SEMPRE preencha com interesses detectados na mensagem. Ex: ["camisetas", "tamanho G", "cor preta"].
Se nenhum interesse novo, envie [].
"""
    defaults = {
        "schedule_start_time": "08:00", "schedule_end_time": "17:00",
        "min_delay_seconds": str(settings.MIN_DELAY_SECONDS), "max_delay_seconds": str(settings.MAX_DELAY_SECONDS),
        "followup_rules": json.dumps([]),
        "evolution_api_url": "", "evolution_api_key": "",
        "evolution_instance_name": "", "llm_system_prompt": default_llm_system_prompt.strip(),
        "product_context": "", "allowed_weekdays": json.dumps([1, 2, 3, 4, 5]),
        "sales_flow_stages": json.dumps([]),  # Não utilizado — chatbot reativo sem funil 
        "initial_message_counter": "0", # NOVA LINHA
        # "user_openrouter_api_key": "", # Removido
        # "llm_model_preference": settings.DEFAULT_LLM_MODEL, # Removido
        # "llm_temperature": str(settings.DEFAULT_LLM_TEMPERATURE), # Removido
        "queue_paused": "false",
        # Configurações do agente
        "agent_name": "Ana",
        "store_name": "Nossa Loja",
        "store_description": "",
        "agent_personality": "Simpática, prestativa e objetiva",
        # Shopify Integration Defaults
        "shopify_store_url": "",
        "shopify_welcome_message": "Oi! Aqui é a {agent_name} da {store_name}! Como posso te ajudar?",
        "shopify_order_notification_enabled": "true",
        # Follow-up automático com cupom de desconto
        "followup_enabled": "true",
        "followup_check_interval_hours": "6",
        "followup_min_hours_after_contact": "24",
        "followup_max_hours_after_contact": "168",
        "followup_no_purchase_days": "7",
        "followup_discount_percentage": "10",
        "followup_discount_expiry_days": "3",
        "followup_discount_minimum_subtotal": "",
        "followup_message_template": json.dumps(
            "Oi, {nome}! 😊\n\n"
            "Vi que você conversou com a gente mas ainda não finalizou sua compra.\n\n"
            "Preparei um cupom especial pra você:\n\n"
            "🎁 *{desconto}% de desconto* com o código:\n"
            "👉 *{cupom}*\n\n"
            "⏰ Válido por {validade} dias!\n\n"
            "É só usar na hora de finalizar o pedido no site. Se precisar de ajuda, estou aqui! 🛍️"
        ),
        "followup_schedule_start_time": "09:00",
        "followup_schedule_end_time": "20:00",
        "followup_allowed_weekdays": json.dumps([0, 1, 2, 3, 4, 5])
     }
    inserted_count = 0; instance_id = settings.INSTANCE_ID
    for key, value in defaults.items():
        try:
            check_sql = "SELECT 1 FROM application_config WHERE instance_id = %s AND config_key = %s"
            await cursor.execute(check_sql, (instance_id, key))
            if not await cursor.fetchone():
                insert_sql = "INSERT INTO application_config (instance_id, config_key, config_value) VALUES (%s, %s, %s)"
                await cursor.execute(insert_sql, (instance_id, key, value))
                if cursor.rowcount > 0:
                    inserted_count += 1
                    logger.info(f"database.py: Default config '{key}' inserted for instance '{instance_id}'.")
        except Exception as e:
            logger.error(f"database.py: Error processing default config '{key}' for instance '{instance_id}': {e}", exc_info=True)
    if inserted_count > 0: logger.info(f"database.py: {inserted_count} default configurations inserted/updated for instance '{instance_id}'.")

# --- Generic Configuration Access Functions (now imported from config_crud) ---
get_config_value = config_crud.get_config_value
set_config_value = config_crud.set_config_value
get_all_configs_as_dict = config_crud.get_all_configs_as_dict

# --- Specific Configuration Getters/Setters (now imported from config_crud) ---
get_evolution_config = config_crud.get_evolution_config
set_evolution_config = config_crud.set_evolution_config
get_product_context = config_crud.get_product_context
set_product_context = config_crud.set_product_context
get_llm_system_prompt = config_crud.get_llm_system_prompt
set_llm_system_prompt = config_crud.set_llm_system_prompt
# get_llm_preferences = config_crud.get_llm_preferences # Removido
# set_llm_preferences = config_crud.set_llm_preferences # Removido
get_sales_flow_stages = config_crud.get_sales_flow_stages
set_sales_flow_stages = config_crud.set_sales_flow_stages
get_follow_up_rules = config_crud.get_follow_up_rules
set_follow_up_rules = config_crud.set_follow_up_rules

# --- Prospect Data Access Functions (now imported from prospect_crud) ---
get_prospects_list = prospect_crud.get_prospects_list
get_prospect_conversation_history = prospect_crud.get_prospect_conversation_history
get_prospect_db_status = prospect_crud.get_prospect_db_status
add_or_update_prospect_db = prospect_crud.add_or_update_prospect_db
update_prospect_status_db = prospect_crud.update_prospect_status_db
add_history_entry_db = prospect_crud.add_history_entry_db
get_total_token_usage = prospect_crud.get_total_token_usage

# --- Data Clearing Functions (now imported from prospect_crud) ---
clear_all_leads_from_db = prospect_crud.clear_all_leads_from_db
clear_all_conversations_from_db = prospect_crud.clear_all_conversations_from_db
clear_all_token_usage_from_db = prospect_crud.clear_all_token_usage_from_db

logger.info("database.py: Module loaded.")
