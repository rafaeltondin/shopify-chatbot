# src/utils/time_utils.py
from datetime import datetime
import pytz
import json

def get_current_datetime_info_tool():
    """
    Retorna a data, hora e dia da semana atuais no fuso horário de São Paulo.
    Esta função foi projetada para ser usada como uma ferramenta por um LLM.
    """
    try:
        # Usar um fuso horário explícito para consistência
        tz = pytz.timezone('America/Sao_Paulo')
        now = datetime.now(tz)
        
        datetime_info = {
            "full_datetime_iso": now.isoformat(),
            "date": now.strftime('%Y-%m-%d'),
            "time": now.strftime('%H:%M:%S'),
            "weekday": now.strftime('%A').lower(),  # e.g., "monday"
            "timezone": "America/Sao_Paulo"
        }
        
        # Retorna uma string JSON, como é comum para o conteúdo da ferramenta
        return json.dumps(datetime_info)
    except Exception as e:
        # Em caso de erro, retorna uma mensagem de erro clara
        return json.dumps({"error": "Failed to retrieve current datetime", "details": str(e)})
