# -*- coding: utf-8 -*-
import logging
import csv
import io
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse # Adicionado StreamingResponse

from src.core import prospect as prospect_manager
from src.api.routes.queue_models import QueueStatusResponse, QueueActionResponse

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/queue/status", response_model=QueueStatusResponse, tags=["Queue"])
async def get_queue_status_endpoint():
    logger.info("[API_QUEUE_STATUS] Recebida requisição para obter status da fila.")
    size = await prospect_manager.get_queue_size()
    paused = await prospect_manager.is_queue_paused()
    logger.info(f"[API_QUEUE_STATUS] Status da fila: Tamanho={size}, Pausada={paused}")
    return QueueStatusResponse(queue_size=size, is_paused=paused)

@router.post("/queue/pause", response_model=QueueActionResponse, tags=["Queue"])
async def pause_queue_endpoint():
    logger.info("[API_QUEUE_PAUSE] Recebida requisição para pausar fila.")
    success = await prospect_manager.pause_queue()
    size = await prospect_manager.get_queue_size()
    if success:
        logger.info(f"[API_QUEUE_PAUSE] Fila pausada com sucesso. Tamanho atual: {size}")
        return QueueActionResponse(success=True, message="Fila pausada com sucesso.", queue_size=size)
    else:
        logger.error("[API_QUEUE_PAUSE] Falha ao pausar a fila.")
        raise HTTPException(status_code=500, detail="Não foi possível pausar a fila.")

@router.post("/queue/resume", response_model=QueueActionResponse, tags=["Queue"])
async def resume_queue_endpoint():
    logger.info("[API_QUEUE_RESUME] Recebida requisição para retomar fila.")
    success = await prospect_manager.resume_queue()
    size = await prospect_manager.get_queue_size()
    if success:
        logger.info(f"[API_QUEUE_RESUME] Fila retomada com sucesso. Tamanho atual: {size}")
        return QueueActionResponse(success=True, message="Fila retomada com sucesso.", queue_size=size)
    else:
        logger.error("[API_QUEUE_RESUME] Falha ao retomar a fila.")
        raise HTTPException(status_code=500, detail="Não foi possível retomar a fila.")

@router.post("/queue/clear", response_model=QueueActionResponse, tags=["Queue"])
async def clear_queue_endpoint():
    logger.info("[API_QUEUE_CLEAR] Recebida requisição para limpar fila.")
    cleared_count = await prospect_manager.clear_queue()
    logger.info(f"[API_QUEUE_CLEAR] Fila limpa. {cleared_count} leads removidos. Tamanho atual: 0")
    return QueueActionResponse(success=True, message=f"{cleared_count} leads removidos da fila.", queue_size=0)

@router.get("/queue/export-csv", tags=["Queue"]) # Removido response_class=StreamingResponse por enquanto
async def export_queue_jids_csv():
    """
    Exporta os JIDs atualmente na fila de prospecção em memória para um arquivo CSV.
    Retorna um erro 404 se a fila estiver vazia.
    """
    logger.info("[API_QUEUE_EXPORT_CSV] Recebida requisição para exportar JIDs da fila para CSV.")
    try:
        # A função get_current_jids_in_queue foi adicionada em main_prospect_logic.py
        # e é um alias para get_all_jids_in_memory_queue de queue.py
        jids_in_queue = await prospect_manager.get_current_jids_in_queue()
        
        if not jids_in_queue:
            logger.info("[API_QUEUE_EXPORT_CSV] Fila está vazia. Nenhum prospect para exportar.")
            # Retornar um erro 404 com uma mensagem JSON
            raise HTTPException(status_code=404, detail="A fila está vazia. Nenhum prospect para exportar.")

        logger.info(f"[API_QUEUE_EXPORT_CSV] {len(jids_in_queue)} JIDs encontrados na fila para exportação.")
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Escreve o cabeçalho
        writer.writerow(['jid'])
        
        # Escreve os dados
        for jid in jids_in_queue:
            writer.writerow([jid])
            
        output.seek(0) # Volta para o início do buffer para leitura
        
        logger.info("[API_QUEUE_EXPORT_CSV] Arquivo CSV gerado com sucesso.")
        return StreamingResponse(
            iter([output.getvalue()]), 
            media_type="text/csv", 
            headers={"Content-Disposition": "attachment; filename=fila_prospects.csv"}
        )

    except Exception as e:
        logger.error(f"[API_QUEUE_EXPORT_CSV] Erro ao exportar JIDs da fila para CSV: {e}", exc_info=True)
        # Em caso de erro, você pode querer retornar uma resposta de erro HTTP
        # Aqui, vamos levantar uma HTTPException para que o FastAPI a manipule.
        # No entanto, como a response_class é StreamingResponse, um erro HTTP pode não ser o ideal
        # se o streaming já começou. Para este caso, a exceção ocorrerá antes do streaming.
        raise HTTPException(status_code=500, detail="Erro ao gerar o arquivo CSV da fila.")
