# -*- coding: utf-8 -*-
import re
import logging
from typing import Optional

# Logger specific to this module
logger = logging.getLogger(__name__)

def clean_phone_number(number: Optional[str]) -> Optional[str]:
    """
    Cleans a phone number string by removing non-digit characters (except a leading '+')
    and stripping whitespace.

    Args:
        number: The phone number string to clean.

    Returns:
        The cleaned phone number string or None if the input is invalid or empty.
    """
    if number is None:
        logger.debug("formatting.py: clean_phone_number: Input is None.")
        return None

    number_str = str(number).strip()
    if not number_str:
        logger.debug("formatting.py: clean_phone_number: Input is empty after stripping.")
        return None

    # Keep '+' if it's the first character, remove all other non-digits
    # This regex will remove all non-digits.
    digits_only = re.sub(r'\D', '', number_str)

    # If the original number started with '+', ensure the cleaned number also does.
    # This handles cases like "+55 (11) 99999-8888" -> "+5511999998888"
    # And "55 (11) 99999-8888" -> "5511999998888"
    cleaned_number = digits_only
    if number_str.startswith('+'):
        if not cleaned_number.startswith('+'): # Avoid double '+' if already there from digits_only
            cleaned_number = '+' + cleaned_number
    else:
        # If original did not start with '+', ensure cleaned one also doesn't
        cleaned_number = cleaned_number.lstrip('+')


    # Basic length validation (adjust MIN_DIGITS as needed)
    # This check is on the numeric part, excluding a potential leading '+'
    numeric_part_for_length_check = cleaned_number.lstrip('+')
    MIN_DIGITS = 9 # Example: Minimum reasonable length for number + country code
    if len(numeric_part_for_length_check) < MIN_DIGITS:
        logger.warning(f"formatting.py: clean_phone_number: Number '{number_str}' has too few digits ({len(numeric_part_for_length_check)}) after cleaning. Input: '{cleaned_number}'. Considered invalid.")
        return None

    # A lógica de remoção do nono dígito foi removida para testes,
    # pois pode estar causando problemas com DDD 11 se a API Evolution espera o nono dígito.
    # if len(numeric_part_for_length_check) == 13 and numeric_part_for_length_check.startswith('55'):
    #     if len(numeric_part_for_length_check[4:]) == 9 and numeric_part_for_length_check[4] == '9':
    #         cleaned_number = cleaned_number[:4] + cleaned_number[5:]
    #         logger.info(f"formatting.py: clean_phone_number: Removed extra '9' from Brazilian number. Original: '{number_str}', Corrected: '{cleaned_number}'")

    logger.debug(f"formatting.py: clean_phone_number: Cleaned '{number_str}' to '{cleaned_number}'")
    return cleaned_number

def format_number_for_evolution(phone_number: Optional[str]) -> Optional[str]:
    """
    Formats a cleaned phone number for the Evolution API.
    Ensures it's digits only and appends '@s.whatsapp.net'.

    Args:
        phone_number: The cleaned phone number (e.g., '5511999998888' or '+5511999998888').

    Returns:
        The formatted JID string (e.g., '5511999998888@s.whatsapp.net') or None if input is invalid.
    """
    if not phone_number:
        logger.warning("formatting.py: format_number_for_evolution: Input phone_number is None or empty.")
        return None

    # Remove any non-digit characters, including a potential leading '+'
    digits_only = re.sub(r'\D', '', phone_number)

    if not digits_only:
        logger.warning(f"formatting.py: format_number_for_evolution: No digits found in '{phone_number}'.")
        return None
    
    # Basic length check (e.g., at least 9 digits for number + country code)
    MIN_DIGITS_FOR_JID = 9 
    if len(digits_only) < MIN_DIGITS_FOR_JID:
        logger.warning(f"formatting.py: format_number_for_evolution: Number '{digits_only}' is too short to be a valid JID.")
        return None

    formatted_jid = f"{digits_only}@s.whatsapp.net"
    logger.debug(f"formatting.py: format_number_for_evolution: Formatted '{phone_number}' to '{formatted_jid}'")
    return formatted_jid

logger.info("formatting.py: Module loaded.")
