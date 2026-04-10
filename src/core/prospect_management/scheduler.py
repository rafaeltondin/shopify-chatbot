# -*- coding: utf-8 -*-
import logging
import asyncio
from typing import Dict, List, Optional, Literal
from datetime import timedelta, datetime
import pytz
from pydantic import ValidationError

from src.core.config import settings, logger
from src.core.prospect_management.state import ProspectState, get_prospect, save_prospect, add_message_to_history_state
from src.core.db_operations.config_crud import get_follow_up_rules
from src.core.wallet_manager import get_wallet_balance
from src.core.notifications import send_low_balance_notification
from src.core.db_operations.prospect_crud import get_all_instance_ids # Assuming this function will be created
from src.core.db_operations.prospect_crud import get_active_prospect_jids, get_prospect_funnel_id # Importar funções necessárias
from src.api.routes.config_models import FollowUpRule # For validation
from src.core.prospect_management.flow_logic import _send_text_message_fl # Reusing send function

logger = logging.getLogger(__name__)

follow_up_scheduler_task_sch: Optional[asyncio.Task] = None
is_follow_up_scheduler_running_sch: bool = False
wallet_checker_task_sch: Optional[asyncio.Task] = None
is_wallet_checker_running_sch: bool = False

def _convert_delay_to_timedelta_sch(delay_value: int, delay_unit: Literal["days", "minutes"]) -> timedelta:
    if delay_unit == "days": return timedelta(days=delay_value)
    elif delay_unit == "minutes": return timedelta(minutes=delay_value)
    raise ValueError(f"Unknown delay unit: {delay_unit}")

async def _follow_up_scheduler_loop_sch():
    global is_follow_up_scheduler_running_sch
    logger.info("[FOLLOW_UP_SCHED_LOOP_SCH] Follow-up scheduler loop started.")
    consecutive_errors = 0
    max_consecutive_errors = 5

    try:
        while is_follow_up_scheduler_running_sch:
            try:
                logger.info("[FOLLOW_UP_SCHED_LOOP_SCH] Starting follow-up check cycle...")

                rules_data = await get_follow_up_rules()
                active_rules: List[FollowUpRule] = []
                for rule_dict in rules_data:
                    try:
                        rule = FollowUpRule(**rule_dict)
                        if rule.enabled: active_rules.append(rule)
                    except ValidationError as e: logger.error(f"[FOLLOW_UP_SCHED_LOOP_SCH] Validation error in follow-up rule: {rule_dict} - {e}")

                if not active_rules:
                    logger.info("[FOLLOW_UP_SCHED_LOOP_SCH] No active follow-up rules. Skipping check.")
                else:
                    logger.info(f"[FOLLOW_UP_SCHED_LOOP_SCH] {len(active_rules)} active follow-up rules found.")

                    all_prospect_jids = await get_active_prospect_jids(settings.INSTANCE_ID)
                    logger.info(f"[FOLLOW_UP_SCHED_LOOP_SCH] Found {len(all_prospect_jids)} active JIDs to check.")

                    for jid in all_prospect_jids:
                        try:
                            prospect = await get_prospect(jid)
                            if not prospect or prospect.status != 'active' or not prospect.last_outgoing_message_at:
                                logger.debug(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Skipping prospect: Not active, no state, or no last outgoing message.")
                                continue

                            # Obter o funil do prospect para filtrar regras
                            prospect_funnel_id = await get_prospect_funnel_id(jid, settings.INSTANCE_ID)
                            logger.debug(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Prospect funnel_id: {prospect_funnel_id}")

                            current_time_utc = datetime.now(pytz.utc)
                            for rule in active_rules:
                                try:
                                    # Gerar rule_id incluindo funnel_id para unicidade
                                    rule_funnel = getattr(rule, 'funnel_id', None)
                                    rule_id = f"{rule.stage}-{rule.delay_value}-{rule.delay_unit}-{rule_funnel or 'all'}"

                                    if rule_id in prospect.applied_follow_up_rules or prospect.stage != rule.stage:
                                        continue

                                    # Verificar se a regra se aplica ao funil do prospect
                                    # Se rule.funnel_id é None, aplica a todos os funis
                                    # Se rule.funnel_id tem valor, só aplica se prospect está nesse funil
                                    if rule_funnel is not None and rule_funnel != prospect_funnel_id:
                                        logger.debug(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Rule {rule_id} skipped: funnel mismatch (rule: {rule_funnel}, prospect: {prospect_funnel_id})")
                                        continue

                                    required_delay = _convert_delay_to_timedelta_sch(rule.delay_value, rule.delay_unit)
                                    time_since_last_message = current_time_utc - prospect.last_outgoing_message_at

                                    if time_since_last_message >= required_delay:
                                        current_local_time = datetime.now().astimezone(pytz.timezone('America/Sao_Paulo'))
                                        if (current_local_time.time() >= datetime.strptime(rule.start_time, '%H:%M').time() and
                                            current_local_time.time() <= datetime.strptime(rule.end_time, '%H:%M').time()):

                                            logger.info(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Prospect eligible for follow-up (Rule: {rule_id}).")
                                            await _send_text_message_fl(jid, rule.message)
                                            await add_message_to_history_state(jid, "system", f"[AUTO_FOLLOW_UP] Sent: '{rule.message}' (Rule: {rule_id})")
                                            prospect.applied_follow_up_rules.append(rule_id)
                                            await save_prospect(prospect)
                                            logger.info(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Follow-up sent and rule '{rule_id}' marked as applied.")
                                        else:
                                            logger.debug(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Eligible, but outside time window ({rule.start_time}-{rule.end_time}).")
                                    else:
                                        logger.debug(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Not yet eligible. Time since last: {time_since_last_message}, Required: {required_delay}.")
                                except Exception as e_rule:
                                    logger.error(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Error processing rule {rule_id}: {e_rule}", exc_info=True)
                                    continue
                        except Exception as e_prospect:
                            logger.error(f"[{jid}] [FOLLOW_UP_SCHED_LOOP_SCH] Error processing prospect: {e_prospect}", exc_info=True)
                            continue

                # Reset consecutive errors on successful cycle
                consecutive_errors = 0

                interval = getattr(settings, 'FOLLOW_UP_SCHEDULER_INTERVAL', 60)
                logger.info(f"[FOLLOW_UP_SCHED_LOOP_SCH] Cycle finished. Waiting {interval}s for next cycle.")
                try: await asyncio.wait_for(asyncio.sleep(interval), timeout=interval + 5)
                except asyncio.TimeoutError: logger.warning("[FOLLOW_UP_SCHED_LOOP_SCH] Timeout waiting for next cycle. Continuing.")

            except asyncio.CancelledError:
                raise  # Propagar cancelamento
            except Exception as e_cycle:
                consecutive_errors += 1
                logger.error(f"[FOLLOW_UP_SCHED_LOOP_SCH] Error in cycle (consecutive errors: {consecutive_errors}): {e_cycle}", exc_info=True)

                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"[FOLLOW_UP_SCHED_LOOP_SCH] Too many consecutive errors ({consecutive_errors}). Stopping scheduler.")
                    break

                # Wait before retrying
                await asyncio.sleep(30)
                continue

    except asyncio.CancelledError:
        logger.info("[FOLLOW_UP_SCHED_LOOP_SCH] Loop cancelled.")
    except Exception as e:
        logger.error(f"[FOLLOW_UP_SCHED_LOOP_SCH] Critical error: {e}", exc_info=True)
    finally:
        is_follow_up_scheduler_running_sch = False
        logger.info("[FOLLOW_UP_SCHED_LOOP_SCH] Loop finished.")

async def _wallet_balance_checker_loop_sch():
    global is_wallet_checker_running_sch
    logger.info("[WALLET_CHECKER_LOOP_SCH] Wallet balance checker loop started.")
    try:
        while is_wallet_checker_running_sch:
            logger.info("[WALLET_CHECKER_LOOP_SCH] Starting wallet balance check cycle...")
            
            # In a multi-tenant system, you'd get all unique instance_ids
            # For now, we'll just use the current instance_id
            instance_ids = [settings.INSTANCE_ID]
            
            for instance_id in instance_ids:
                try:
                    balance = await get_wallet_balance(instance_id)
                    if balance is not None and balance < settings.LOW_BALANCE_THRESHOLD:
                        logger.warning(f"Instance {instance_id} has low balance: {balance}. Sending notification.")
                        if settings.ADMIN_EMAIL:
                            await send_low_balance_notification(settings.ADMIN_EMAIL, balance)
                        else:
                            logger.error(f"Cannot send low balance notification for instance {instance_id}: ADMIN_EMAIL not set.")
                except Exception as e:
                    logger.error(f"Error checking wallet balance for instance {instance_id}: {e}", exc_info=True)

            # Check every hour
            await asyncio.sleep(3600)
            
    except asyncio.CancelledError:
        logger.info("[WALLET_CHECKER_LOOP_SCH] Loop cancelled.")
    except Exception as e:
        logger.error(f"[WALLET_CHECKER_LOOP_SCH] Critical error: {e}", exc_info=True)
    finally:
        is_wallet_checker_running_sch = False
        logger.info("[WALLET_CHECKER_LOOP_SCH] Loop finished.")

def start_wallet_checker_sch():
    global wallet_checker_task_sch, is_wallet_checker_running_sch
    logger.info("[WALLET_CHECKER_CTRL_SCH] Attempting to start wallet balance checker.")
    if not is_wallet_checker_running_sch:
        if wallet_checker_task_sch is None or wallet_checker_task_sch.done():
            is_wallet_checker_running_sch = True
            try:
                loop = asyncio.get_running_loop()
                wallet_checker_task_sch = loop.create_task(_wallet_balance_checker_loop_sch())
                logger.info("[WALLET_CHECKER_CTRL_SCH] Wallet checker task (re)started.")
            except RuntimeError:
                logger.error("[WALLET_CHECKER_CTRL_SCH] asyncio loop not running. Task not created.")
                is_wallet_checker_running_sch = False
        else:
            logger.debug("[WALLET_CHECKER_CTRL_SCH] Task already active and not done.")
    else:
        logger.debug("[WALLET_CHECKER_CTRL_SCH] Wallet checker already marked as running.")

async def stop_wallet_checker_sch():
    global wallet_checker_task_sch, is_wallet_checker_running_sch
    logger.info("[WALLET_CHECKER_CTRL_SCH] Attempting to stop wallet balance checker.")
    is_wallet_checker_running_sch = False
    if wallet_checker_task_sch and not wallet_checker_task_sch.done():
        wallet_checker_task_sch.cancel()
        try:
            await wallet_checker_task_sch
        except asyncio.CancelledError:
            pass
    logger.info("[WALLET_CHECKER_CTRL_SCH] Wallet checker stop process completed.")

def start_follow_up_scheduler_sch(): 
    global follow_up_scheduler_task_sch, is_follow_up_scheduler_running_sch
    logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] Attempting to start follow-up scheduler.")
    if not getattr(settings, 'ENABLE_FOLLOW_UP_SCHEDULER', False): 
        logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] Disabled in settings. Not started."); return

    if not is_follow_up_scheduler_running_sch:
        if follow_up_scheduler_task_sch is None or follow_up_scheduler_task_sch.done():
            is_follow_up_scheduler_running_sch = True
            try:
                loop = asyncio.get_running_loop()
                follow_up_scheduler_task_sch = loop.create_task(_follow_up_scheduler_loop_sch())
                logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] Scheduler task (re)started.")
            except RuntimeError:
                logger.error("[FOLLOW_UP_SCHED_CTRL_SCH] asyncio loop not running. Task not created.")
                is_follow_up_scheduler_running_sch = False
        else: logger.debug("[FOLLOW_UP_SCHED_CTRL_SCH] Task already active and not done.")
    else: logger.debug("[FOLLOW_UP_SCHED_CTRL_SCH] Scheduler already marked as running.")

async def stop_follow_up_scheduler_sch():
    global follow_up_scheduler_task_sch, is_follow_up_scheduler_running_sch
    logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] Attempting to stop follow-up scheduler.")
    is_follow_up_scheduler_running_sch = False
    stop_timeout = getattr(settings, 'FOLLOW_UP_SCHEDULER_STOP_TIMEOUT', 10) 

    if follow_up_scheduler_task_sch and not follow_up_scheduler_task_sch.done():
        logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] Cancelling active task...")
        follow_up_scheduler_task_sch.cancel()
        try:
            await asyncio.wait_for(follow_up_scheduler_task_sch, timeout=stop_timeout)
            logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] Task cancelled and awaited.")
        except asyncio.CancelledError: logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] Task cancelled as expected.")
        except asyncio.TimeoutError: logger.warning(f"[FOLLOW_UP_SCHED_CTRL_SCH] Timeout ({stop_timeout}s) awaiting task termination.")
        except Exception as e: logger.error(f"[FOLLOW_UP_SCHED_CTRL_SCH] Exceptional error during stop: {e}", exc_info=True)
        finally: follow_up_scheduler_task_sch = None
    else: logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] No active task to stop or already finished.")
    logger.info("[FOLLOW_UP_SCHED_CTRL_SCH] Stop process completed.")

logger.info("prospect_management.scheduler: Module loaded.")
