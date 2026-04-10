# -*- coding: utf-8 -*-
"""
CRUD Operations for Sales Funnels (Multiple Funnels Support)

This module provides database operations for managing multiple sales funnels,
including creation, retrieval, update, deletion, and migration of legacy funnels.
"""

import logging
import json
import uuid
from typing import Optional, Any, Dict, List
from datetime import datetime
import pytz

from src.core.config import settings, logger

logger = logging.getLogger(__name__)


async def get_all_funnels(instance_id: Optional[str] = None, include_inactive: bool = False) -> List[Dict[str, Any]]:
    """
    Retrieves all funnels for an instance.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)
        include_inactive: If True, includes inactive funnels

    Returns:
        List of funnel dictionaries with summary info
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"funnel_crud: Fetching all funnels for instance '{instance_id}' (include_inactive={include_inactive})")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return []

    sql = """
        SELECT funnel_id, name, description, stages, is_default, is_active, created_at, updated_at
        FROM sales_funnels
        WHERE instance_id = %s
    """
    params = [instance_id]

    if not include_inactive:
        sql += " AND is_active = TRUE"

    sql += " ORDER BY is_default DESC, name ASC"

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, tuple(params))
            results = await cursor.fetchall()

            funnels = []
            sao_paulo_tz = pytz.timezone('America/Sao_Paulo')

            for row in results:
                # Parse stages JSON
                stages = row.get('stages')
                if isinstance(stages, str):
                    try:
                        stages = json.loads(stages)
                    except json.JSONDecodeError:
                        stages = []
                elif stages is None:
                    stages = []

                # Format timestamps
                created_at = row.get('created_at')
                updated_at = row.get('updated_at')

                if created_at:
                    dt_utc = pytz.utc.localize(created_at) if created_at.tzinfo is None else created_at
                    created_at = dt_utc.astimezone(sao_paulo_tz).isoformat()

                if updated_at:
                    dt_utc = pytz.utc.localize(updated_at) if updated_at.tzinfo is None else updated_at
                    updated_at = dt_utc.astimezone(sao_paulo_tz).isoformat()

                funnels.append({
                    "funnel_id": row['funnel_id'],
                    "name": row['name'],
                    "description": row.get('description'),
                    "stages": stages,
                    "stages_count": len(stages) if isinstance(stages, list) else 0,
                    "is_default": bool(row.get('is_default', False)),
                    "is_active": bool(row.get('is_active', True)),
                    "created_at": created_at,
                    "updated_at": updated_at
                })

            logger.info(f"funnel_crud: Found {len(funnels)} funnels for instance '{instance_id}'")
            return funnels

    except Exception as e:
        logger.error(f"funnel_crud: Error fetching funnels: {e}", exc_info=True)
        return []


async def get_funnel_by_id(instance_id: Optional[str], funnel_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a specific funnel by its ID.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)
        funnel_id: The funnel's unique identifier

    Returns:
        Funnel dictionary or None if not found
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"funnel_crud: Fetching funnel '{funnel_id}' for instance '{instance_id}'")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return None

    sql = """
        SELECT funnel_id, name, description, stages, is_default, is_active, created_at, updated_at
        FROM sales_funnels
        WHERE instance_id = %s AND funnel_id = %s
    """

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id, funnel_id))
            row = await cursor.fetchone()

            if not row:
                logger.warning(f"funnel_crud: Funnel '{funnel_id}' not found for instance '{instance_id}'")
                return None

            # Parse stages JSON
            stages = row.get('stages')
            if isinstance(stages, str):
                try:
                    stages = json.loads(stages)
                except json.JSONDecodeError:
                    stages = []
            elif stages is None:
                stages = []

            # Format timestamps
            sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
            created_at = row.get('created_at')
            updated_at = row.get('updated_at')

            if created_at:
                dt_utc = pytz.utc.localize(created_at) if created_at.tzinfo is None else created_at
                created_at = dt_utc.astimezone(sao_paulo_tz).isoformat()

            if updated_at:
                dt_utc = pytz.utc.localize(updated_at) if updated_at.tzinfo is None else updated_at
                updated_at = dt_utc.astimezone(sao_paulo_tz).isoformat()

            funnel = {
                "funnel_id": row['funnel_id'],
                "name": row['name'],
                "description": row.get('description'),
                "stages": stages,
                "is_default": bool(row.get('is_default', False)),
                "is_active": bool(row.get('is_active', True)),
                "created_at": created_at,
                "updated_at": updated_at
            }

            logger.info(f"funnel_crud: Found funnel '{funnel_id}' with {len(stages)} stages")
            return funnel

    except Exception as e:
        logger.error(f"funnel_crud: Error fetching funnel '{funnel_id}': {e}", exc_info=True)
        return None


async def get_default_funnel(instance_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves the default funnel for an instance.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)

    Returns:
        Default funnel dictionary or None if not found
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"funnel_crud: Fetching default funnel for instance '{instance_id}'")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return None

    sql = """
        SELECT funnel_id, name, description, stages, is_default, is_active, created_at, updated_at
        FROM sales_funnels
        WHERE instance_id = %s AND is_default = TRUE AND is_active = TRUE
        LIMIT 1
    """

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(sql, (instance_id,))
            row = await cursor.fetchone()

            if not row:
                # Fallback: get the first active funnel
                logger.warning(f"funnel_crud: No default funnel found, trying first active funnel")
                fallback_sql = """
                    SELECT funnel_id, name, description, stages, is_default, is_active, created_at, updated_at
                    FROM sales_funnels
                    WHERE instance_id = %s AND is_active = TRUE
                    ORDER BY created_at ASC
                    LIMIT 1
                """
                await cursor.execute(fallback_sql, (instance_id,))
                row = await cursor.fetchone()

            if not row:
                logger.warning(f"funnel_crud: No active funnel found for instance '{instance_id}'")
                return None

            # Parse stages JSON
            stages = row.get('stages')
            if isinstance(stages, str):
                try:
                    stages = json.loads(stages)
                except json.JSONDecodeError:
                    stages = []
            elif stages is None:
                stages = []

            # Format timestamps
            sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
            created_at = row.get('created_at')
            updated_at = row.get('updated_at')

            if created_at:
                dt_utc = pytz.utc.localize(created_at) if created_at.tzinfo is None else created_at
                created_at = dt_utc.astimezone(sao_paulo_tz).isoformat()

            if updated_at:
                dt_utc = pytz.utc.localize(updated_at) if updated_at.tzinfo is None else updated_at
                updated_at = dt_utc.astimezone(sao_paulo_tz).isoformat()

            funnel = {
                "funnel_id": row['funnel_id'],
                "name": row['name'],
                "description": row.get('description'),
                "stages": stages,
                "is_default": bool(row.get('is_default', False)),
                "is_active": bool(row.get('is_active', True)),
                "created_at": created_at,
                "updated_at": updated_at
            }

            logger.info(f"funnel_crud: Found default funnel '{row['funnel_id']}' with {len(stages)} stages")
            return funnel

    except Exception as e:
        logger.error(f"funnel_crud: Error fetching default funnel: {e}", exc_info=True)
        return None


async def create_funnel(
    instance_id: Optional[str],
    name: str,
    stages: List[Dict[str, Any]],
    description: Optional[str] = None,
    set_as_default: bool = False,
    funnel_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Creates a new funnel.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)
        name: Name of the funnel
        stages: List of stage dictionaries
        description: Optional description
        set_as_default: If True, sets this as the default funnel
        funnel_id: Optional custom funnel ID (generates UUID if not provided)

    Returns:
        Created funnel dictionary or None on error
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    if funnel_id is None:
        funnel_id = str(uuid.uuid4())[:8]  # Short UUID for friendlier IDs

    logger.info(f"funnel_crud: Creating funnel '{name}' (id: {funnel_id}) for instance '{instance_id}'")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return None

    now_utc = datetime.utcnow()
    stages_json = json.dumps(stages, ensure_ascii=False)

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # If setting as default, first unset any existing default
                if set_as_default:
                    await cursor.execute(
                        "UPDATE sales_funnels SET is_default = FALSE WHERE instance_id = %s AND is_default = TRUE",
                        (instance_id,)
                    )

                # Insert the new funnel
                sql = """
                    INSERT INTO sales_funnels (instance_id, funnel_id, name, description, stages, is_default, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s)
                """
                await cursor.execute(sql, (
                    instance_id, funnel_id, name, description, stages_json,
                    set_as_default, now_utc, now_utc
                ))

                if not conn.get_autocommit():
                    await conn.commit()

        logger.info(f"funnel_crud: Funnel '{funnel_id}' created successfully")

        # Return the created funnel
        return await get_funnel_by_id(instance_id, funnel_id)

    except Exception as e:
        logger.error(f"funnel_crud: Error creating funnel: {e}", exc_info=True)
        return None


async def update_funnel(
    instance_id: Optional[str],
    funnel_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    stages: Optional[List[Dict[str, Any]]] = None,
    is_active: Optional[bool] = None
) -> Optional[Dict[str, Any]]:
    """
    Updates an existing funnel.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)
        funnel_id: The funnel's unique identifier
        name: New name (optional)
        description: New description (optional)
        stages: New stages (optional)
        is_active: New active status (optional)

    Returns:
        Updated funnel dictionary or None on error
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"funnel_crud: Updating funnel '{funnel_id}' for instance '{instance_id}'")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return None

    # Build dynamic update query
    updates = []
    params = []

    if name is not None:
        updates.append("name = %s")
        params.append(name)

    if description is not None:
        updates.append("description = %s")
        params.append(description)

    if stages is not None:
        updates.append("stages = %s")
        params.append(json.dumps(stages, ensure_ascii=False))

    if is_active is not None:
        updates.append("is_active = %s")
        params.append(is_active)

    if not updates:
        logger.warning("funnel_crud: No updates provided")
        return await get_funnel_by_id(instance_id, funnel_id)

    updates.append("updated_at = %s")
    params.append(datetime.utcnow())

    params.extend([instance_id, funnel_id])

    sql = f"""
        UPDATE sales_funnels
        SET {', '.join(updates)}
        WHERE instance_id = %s AND funnel_id = %s
    """

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, tuple(params))
                rows_affected = cursor.rowcount

                if not conn.get_autocommit():
                    await conn.commit()

        if rows_affected == 0:
            logger.warning(f"funnel_crud: Funnel '{funnel_id}' not found or no changes made")
            return None

        logger.info(f"funnel_crud: Funnel '{funnel_id}' updated successfully")
        return await get_funnel_by_id(instance_id, funnel_id)

    except Exception as e:
        logger.error(f"funnel_crud: Error updating funnel: {e}", exc_info=True)
        return None


async def delete_funnel(instance_id: Optional[str], funnel_id: str) -> bool:
    """
    Deletes a funnel.

    Note: Cannot delete the default funnel or a funnel with associated prospects.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)
        funnel_id: The funnel's unique identifier

    Returns:
        True if deleted successfully, False otherwise
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"funnel_crud: Attempting to delete funnel '{funnel_id}' for instance '{instance_id}'")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return False

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Check if it's the default funnel
                await cursor.execute(
                    "SELECT is_default FROM sales_funnels WHERE instance_id = %s AND funnel_id = %s",
                    (instance_id, funnel_id)
                )
                row = await cursor.fetchone()

                if not row:
                    logger.warning(f"funnel_crud: Funnel '{funnel_id}' not found")
                    return False

                if row.get('is_default'):
                    logger.error(f"funnel_crud: Cannot delete default funnel '{funnel_id}'")
                    return False

                # Check for associated prospects
                await cursor.execute(
                    "SELECT COUNT(*) as count FROM prospects WHERE instance_id = %s AND funnel_id = %s",
                    (instance_id, funnel_id)
                )
                count_result = await cursor.fetchone()
                prospects_count = count_result.get('count', 0) if count_result else 0

                if prospects_count > 0:
                    logger.error(f"funnel_crud: Cannot delete funnel '{funnel_id}' with {prospects_count} associated prospects")
                    return False

                # Delete the funnel
                await cursor.execute(
                    "DELETE FROM sales_funnels WHERE instance_id = %s AND funnel_id = %s",
                    (instance_id, funnel_id)
                )

                if not conn.get_autocommit():
                    await conn.commit()

        logger.info(f"funnel_crud: Funnel '{funnel_id}' deleted successfully")
        return True

    except Exception as e:
        logger.error(f"funnel_crud: Error deleting funnel: {e}", exc_info=True)
        return False


async def set_default_funnel(instance_id: Optional[str], funnel_id: str) -> bool:
    """
    Sets a funnel as the default for the instance.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)
        funnel_id: The funnel's unique identifier

    Returns:
        True if successful, False otherwise
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"funnel_crud: Setting funnel '{funnel_id}' as default for instance '{instance_id}'")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return False

    try:
        async with settings.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Verify the funnel exists and is active
                await cursor.execute(
                    "SELECT is_active FROM sales_funnels WHERE instance_id = %s AND funnel_id = %s",
                    (instance_id, funnel_id)
                )
                row = await cursor.fetchone()

                if not row:
                    logger.error(f"funnel_crud: Funnel '{funnel_id}' not found")
                    return False

                if not row.get('is_active'):
                    logger.error(f"funnel_crud: Cannot set inactive funnel '{funnel_id}' as default")
                    return False

                # Unset current default
                await cursor.execute(
                    "UPDATE sales_funnels SET is_default = FALSE, updated_at = %s WHERE instance_id = %s AND is_default = TRUE",
                    (datetime.utcnow(), instance_id)
                )

                # Set new default
                await cursor.execute(
                    "UPDATE sales_funnels SET is_default = TRUE, updated_at = %s WHERE instance_id = %s AND funnel_id = %s",
                    (datetime.utcnow(), instance_id, funnel_id)
                )

                if not conn.get_autocommit():
                    await conn.commit()

        logger.info(f"funnel_crud: Funnel '{funnel_id}' is now the default")
        return True

    except Exception as e:
        logger.error(f"funnel_crud: Error setting default funnel: {e}", exc_info=True)
        return False


async def migrate_legacy_funnel(instance_id: Optional[str] = None) -> Optional[str]:
    """
    Migrates the legacy funnel from application_config to the sales_funnels table.

    This function checks if there's a legacy funnel stored in the 'sales_flow_stages' key
    of the application_config table and migrates it to the new sales_funnels table.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)

    Returns:
        The funnel_id of the migrated funnel, or None if no migration was needed/performed
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"funnel_crud: Checking for legacy funnel migration for instance '{instance_id}'")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return None

    try:
        # First, check if we already have funnels in the new table
        existing_funnels = await get_all_funnels(instance_id, include_inactive=True)

        if existing_funnels:
            logger.info(f"funnel_crud: Instance '{instance_id}' already has {len(existing_funnels)} funnels. Skipping migration.")
            return None

        # Check for legacy funnel in application_config
        from src.core.db_operations.config_crud import get_config_value

        legacy_stages = await get_config_value("sales_flow_stages", [], instance_id=instance_id)

        if not legacy_stages or not isinstance(legacy_stages, list) or len(legacy_stages) == 0:
            logger.info(f"funnel_crud: No legacy funnel found for instance '{instance_id}'")
            return None

        logger.info(f"funnel_crud: Found legacy funnel with {len(legacy_stages)} stages. Starting migration...")

        # Create the migrated funnel
        funnel = await create_funnel(
            instance_id=instance_id,
            name="Funil Padrão",
            description="Funil migrado automaticamente do sistema anterior",
            stages=legacy_stages,
            set_as_default=True,
            funnel_id="default"
        )

        if funnel:
            logger.info(f"funnel_crud: Legacy funnel migrated successfully as '{funnel['funnel_id']}'")
            return funnel['funnel_id']
        else:
            logger.error(f"funnel_crud: Failed to migrate legacy funnel")
            return None

    except Exception as e:
        logger.error(f"funnel_crud: Error during legacy funnel migration: {e}", exc_info=True)
        return None


async def get_funnel_for_prospect(jid: str, instance_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Determines which funnel to use for a specific prospect.

    Priority:
    1. funnel_id defined in the prospect record
    2. Default funnel for the instance (is_default=True)
    3. First active funnel found
    4. None (error)

    Args:
        jid: The prospect's JID
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)

    Returns:
        Funnel dictionary or None if not found
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    logger.info(f"funnel_crud: Determining funnel for prospect '{jid}' in instance '{instance_id}'")

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return None

    try:
        # Check if prospect has a specific funnel_id
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            await cursor.execute(
                "SELECT funnel_id FROM prospects WHERE instance_id = %s AND jid = %s",
                (instance_id, jid)
            )
            row = await cursor.fetchone()

            if row and row.get('funnel_id'):
                prospect_funnel_id = row['funnel_id']
                logger.info(f"funnel_crud: Prospect '{jid}' has assigned funnel '{prospect_funnel_id}'")

                funnel = await get_funnel_by_id(instance_id, prospect_funnel_id)
                if funnel and funnel.get('is_active'):
                    return funnel
                else:
                    logger.warning(f"funnel_crud: Assigned funnel '{prospect_funnel_id}' is inactive or not found. Falling back to default.")

        # Fallback to default funnel
        return await get_default_funnel(instance_id)

    except Exception as e:
        logger.error(f"funnel_crud: Error getting funnel for prospect '{jid}': {e}", exc_info=True)
        return await get_default_funnel(instance_id)


async def get_prospects_count_by_funnel(instance_id: Optional[str] = None, funnel_id: Optional[str] = None) -> int:
    """
    Counts prospects associated with a specific funnel.

    Args:
        instance_id: Instance ID (defaults to settings.INSTANCE_ID)
        funnel_id: Funnel ID (if None, counts prospects without funnel assignment)

    Returns:
        Number of prospects
    """
    if instance_id is None:
        instance_id = settings.INSTANCE_ID

    if not settings.db_pool:
        logger.error("funnel_crud: Database pool not available.")
        return 0

    try:
        async with settings.db_pool.acquire() as conn, conn.cursor() as cursor:
            if funnel_id is None:
                await cursor.execute(
                    "SELECT COUNT(*) as count FROM prospects WHERE instance_id = %s AND (funnel_id IS NULL OR funnel_id = '')",
                    (instance_id,)
                )
            else:
                await cursor.execute(
                    "SELECT COUNT(*) as count FROM prospects WHERE instance_id = %s AND funnel_id = %s",
                    (instance_id, funnel_id)
                )

            row = await cursor.fetchone()
            return row.get('count', 0) if row else 0

    except Exception as e:
        logger.error(f"funnel_crud: Error counting prospects by funnel: {e}", exc_info=True)
        return 0


logger.info("funnel_crud: Module loaded.")
