# -*- coding: utf-8 -*-
import base64
import logging
import os
import asyncio
import tempfile
import mimetypes
from pathlib import Path
import math
from typing import Optional, Tuple
import subprocess
import time # Importado para logging de tempo

import httpx
from mutagen import File as MutagenFile
from mutagen import MutagenError
from openai import AsyncOpenAI, OpenAIError, APIConnectionError, AuthenticationError, RateLimitError
from groq import AsyncGroq, GroqError

# Import settings and logger from the config module
from src.core.config import settings, logger

# Logger specific to this module
logger = logging.getLogger(__name__)

# --- Audio Utility Functions (New and Modified) ---

async def _convert_audio_to_mp3(input_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Converte um arquivo de áudio para MP3 usando FFmpeg.
    Retorna o caminho do arquivo MP3 convertido ou None em caso de falha.
    """
    output_path = output_dir / f"{input_path.stem}.mp3"
    logger.info(f"[CONVERT_AUDIO] Iniciando conversão de áudio de '{input_path}' para MP3 em '{output_path}'")
    logger.debug(f"[CONVERT_AUDIO] Tamanho do arquivo de entrada '{input_path}': {input_path.stat().st_size if input_path.exists() else 'Não encontrado'} bytes")

    command = [
        "ffmpeg",
        "-i", str(input_path),
        "-c:a", "libmp3lame", # Codec de áudio MP3
        "-q:a", "2",          # Qualidade de áudio (VBR, 0=melhor, 9=pior)
        "-y",                 # Sobrescrever arquivo de saída se existir
        str(output_path)
    ]
    logger.debug(f"[CONVERT_AUDIO] Comando FFmpeg a ser executado: {' '.join(command)}")

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        decoded_stdout = stdout.decode(errors='ignore').strip()
        decoded_stderr = stderr.decode(errors='ignore').strip()

        if process.returncode == 0:
            logger.info(f"[CONVERT_AUDIO] Conversão para MP3 bem-sucedida: {output_path}")
            if decoded_stdout:
                logger.debug(f"[CONVERT_AUDIO] FFmpeg STDOUT (Sucesso):\n{decoded_stdout}")
            if decoded_stderr: # FFmpeg frequentemente usa stderr para informações de progresso
                logger.debug(f"[CONVERT_AUDIO] FFmpeg STDERR (Sucesso/Info):\n{decoded_stderr}")
            logger.debug(f"[CONVERT_AUDIO] Tamanho do arquivo de saída '{output_path}': {output_path.stat().st_size if output_path.exists() else 'Não criado'} bytes")
            return output_path
        else:
            logger.error(f"[CONVERT_AUDIO] Erro na conversão FFmpeg para MP3 de '{input_path}'. Código de retorno: {process.returncode}")
            if decoded_stdout:
                logger.error(f"[CONVERT_AUDIO] FFmpeg STDOUT (Erro):\n{decoded_stdout}")
            if decoded_stderr:
                logger.error(f"[CONVERT_AUDIO] FFmpeg STDERR (Erro):\n{decoded_stderr}")
            return None
    except FileNotFoundError:
        logger.error("[CONVERT_AUDIO] FFmpeg não encontrado. Certifique-se de que está instalado e no PATH do sistema ou container.")
        return None
    except Exception as e:
        logger.error(f"[CONVERT_AUDIO] Erro inesperado durante a conversão FFmpeg para '{input_path}': {e}", exc_info=True)
        return None

async def _transcribe_with_local_whisper(audio_file_path: Path) -> Optional[str]:
    """
    Transcreve áudio usando a API local faster-whisper (compatível com OpenAI/Groq).

    Configurada por settings.WHISPER_API_BASE_URL (ex: http://host.docker.internal:8771/v1).
    Usada como transcritor PRIMÁRIO quando WHISPER_API_ENABLED=true.

    Returns:
        Texto transcrito ou None se falhar (dispara fallback pra OpenAI/Groq)
    """
    base_url = getattr(settings, "WHISPER_API_BASE_URL", None)
    if not base_url:
        return None

    model_name = getattr(settings, "WHISPER_API_MODEL", "whisper-large-v3-turbo")
    logger.info(f"[TRANSCRIBE_LOCAL] Tentando transcrição via API local ({base_url}) para: {audio_file_path.name}")
    start_ts = time.monotonic()

    try:
        client = AsyncOpenAI(
            base_url=base_url,
            api_key="local-dummy",
            timeout=180.0,
            max_retries=0,
        )
        with open(audio_file_path, "rb") as audio_file_object:
            logger.debug(f"[TRANSCRIBE_LOCAL] POST {base_url}/audio/transcriptions model={model_name} language=pt")
            transcription_response = await client.audio.transcriptions.create(
                model=model_name,
                file=audio_file_object,
                language="pt",
                response_format="text",
            )

        elapsed_time = time.monotonic() - start_ts
        transcription_text = transcription_response if isinstance(transcription_response, str) else ""

        if not transcription_text.strip():
            logger.warning(f"[TRANSCRIBE_LOCAL] Transcrição vazia após {elapsed_time:.2f}s")
            return None

        logger.info(f"[TRANSCRIBE_LOCAL] Sucesso em {elapsed_time:.2f}s. Texto: '{transcription_text[:100]}...'")
        return transcription_text.strip()

    except (APIConnectionError, OpenAIError) as e:
        logger.warning(f"[TRANSCRIBE_LOCAL] Falha ao chamar API local ({type(e).__name__}): {e}. Indo pro fallback.")
        return None
    except Exception as e:
        logger.error(f"[TRANSCRIBE_LOCAL] Erro inesperado: {e}", exc_info=True)
        return None


async def _transcribe_with_groq(audio_file_path: Path) -> Optional[str]:
    """
    Transcreve áudio usando a API do Groq (Whisper large-v3).
    Usado como fallback quando OpenAI falha com quota exceeded.

    Returns:
        Texto transcrito ou None se falhar
    """
    if not settings.GROQ_API_KEY:
        logger.warning("[TRANSCRIBE_GROQ] Chave da API Groq não configurada. Fallback não disponível.")
        return None

    logger.info(f"[TRANSCRIBE_GROQ] Tentando transcrição via Groq para: {audio_file_path.name}")
    start_ts = time.monotonic()

    try:
        client = AsyncGroq(api_key=settings.GROQ_API_KEY, timeout=120.0)
        with open(audio_file_path, "rb") as audio_file_object:
            logger.debug("[TRANSCRIBE_GROQ] Chamando Groq transcriptions.create com model='whisper-large-v3', language='pt'")
            transcription_response = await client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file_object,
                language="pt",
                response_format="text"
            )

        elapsed_time = time.monotonic() - start_ts
        transcription_text = transcription_response if isinstance(transcription_response, str) else ""

        if not transcription_text.strip():
            logger.warning(f"[TRANSCRIBE_GROQ] Transcrição Groq bem-sucedida mas vazia. Tempo: {elapsed_time:.2f}s")
            return "[Transcrição vazia]"

        logger.info(f"[TRANSCRIBE_GROQ] Sucesso via Groq em {elapsed_time:.2f}s. Transcrição: '{transcription_text[:100]}...'")
        return transcription_text.strip()

    except GroqError as e:
        error_message = str(e)
        logger.error(f"[TRANSCRIBE_GROQ] Erro da API Groq: {error_message}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"[TRANSCRIBE_GROQ] Erro inesperado: {e}", exc_info=True)
        return None


async def transcribe_audio(audio_path: str) -> str:
    """
    Transcreve um arquivo de áudio.
    Ordem de tentativa:
      1. API local faster-whisper (se WHISPER_API_ENABLED=true)
      2. OpenAI Whisper (se OPENAI_API_KEY configurada)
      3. Groq Whisper (fallback)
    """
    logger.info(f"[TRANSCRIBE_AUDIO] Iniciando transcrição para o arquivo: {audio_path}")

    audio_file_path = Path(audio_path)
    if not audio_file_path.is_file():
        logger.error(f"[TRANSCRIBE_AUDIO] Arquivo de áudio não encontrado para transcrição: {audio_path}")
        return "[Erro Transcrição: Arquivo não encontrado]"

    file_size = audio_file_path.stat().st_size
    logger.info(f"[TRANSCRIBE_AUDIO] Arquivo: '{audio_file_path.name}' (Tamanho: {file_size} bytes)")

    # Verificar configuração dos provedores
    use_local = bool(getattr(settings, "WHISPER_API_ENABLED", False)) and bool(getattr(settings, "WHISPER_API_BASE_URL", None))
    use_openai = bool(settings.OPENAI_API_KEY)
    use_groq_fallback = bool(settings.GROQ_API_KEY)

    if not use_local and not use_openai and not use_groq_fallback:
        logger.error("[TRANSCRIBE_AUDIO] Nenhuma API de transcrição configurada (local, OpenAI ou Groq).")
        return "[Erro Transcrição: Nenhuma API configurada]"

    # 1. Tentar API local primeiro (gratuita, baixa latência)
    if use_local:
        local_result = await _transcribe_with_local_whisper(audio_file_path)
        if local_result:
            return local_result
        logger.warning("[TRANSCRIBE_AUDIO] API local falhou/vazia, tentando fallback OpenAI/Groq...")

    # Tentar OpenAI primeiro (se configurada)
    if use_openai:
        start_ts = time.monotonic()
        try:
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=120.0, max_retries=2)
            with open(audio_file_path, "rb") as audio_file_object:
                logger.debug(f"[TRANSCRIBE_AUDIO] Chamando OpenAI Whisper...")
                transcription_response = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file_object,
                    language="pt",
                    response_format="text"
                )

            elapsed_time = time.monotonic() - start_ts
            transcription_text = transcription_response if isinstance(transcription_response, str) else ""

            if not transcription_text.strip():
                logger.warning(f"[TRANSCRIBE_AUDIO] Transcrição OpenAI vazia. Tempo: {elapsed_time:.2f}s.")
                return "[Transcrição vazia]"

            logger.info(f"[TRANSCRIBE_AUDIO] Sucesso OpenAI em {elapsed_time:.2f}s. Transcrição: '{transcription_text[:100]}...'")
            return transcription_text.strip()

        except RateLimitError as e:
            # Erro 429 - Quota exceeded - usar fallback Groq
            logger.warning(f"[TRANSCRIBE_AUDIO] OpenAI quota exceeded (429). Tentando fallback Groq...")
            if use_groq_fallback:
                groq_result = await _transcribe_with_groq(audio_file_path)
                if groq_result:
                    return groq_result
                logger.error("[TRANSCRIBE_AUDIO] Fallback Groq também falhou.")
                return "[Erro Transcrição: OpenAI sem quota e Groq falhou]"
            else:
                logger.error("[TRANSCRIBE_AUDIO] OpenAI sem quota e Groq não configurado.")
                return "[Erro Transcrição: OpenAI sem quota, configure GROQ_API_KEY]"

        except AuthenticationError:
            logger.error(f"[TRANSCRIBE_AUDIO] Erro de autenticação OpenAI.")
            # Tentar Groq como fallback
            if use_groq_fallback:
                logger.info("[TRANSCRIBE_AUDIO] Tentando Groq como fallback após erro de auth OpenAI...")
                groq_result = await _transcribe_with_groq(audio_file_path)
                if groq_result:
                    return groq_result
            return "[Erro Transcrição: Chave OpenAI inválida]"

        except APIConnectionError as e:
            logger.error(f"[TRANSCRIBE_AUDIO] Erro de conexão OpenAI: {e}")
            # Tentar Groq como fallback
            if use_groq_fallback:
                logger.info("[TRANSCRIBE_AUDIO] Tentando Groq como fallback após erro de conexão OpenAI...")
                groq_result = await _transcribe_with_groq(audio_file_path)
                if groq_result:
                    return groq_result
            return "[Erro Transcrição: Falha de conexão com API]"

        except OpenAIError as e:
            status_code = getattr(e, 'status_code', 'N/A')
            error_message = getattr(e, 'message', str(e))
            logger.error(f"[TRANSCRIBE_AUDIO] Erro OpenAI (Status: {status_code}): '{error_message}'")

            # Para qualquer erro OpenAI, tentar Groq
            if use_groq_fallback:
                logger.info(f"[TRANSCRIBE_AUDIO] Tentando Groq como fallback após erro OpenAI {status_code}...")
                groq_result = await _transcribe_with_groq(audio_file_path)
                if groq_result:
                    return groq_result
            return f"[Erro API Transcrição ({status_code}): {error_message}]"

        except FileNotFoundError:
            logger.error(f"[TRANSCRIBE_AUDIO] Arquivo '{audio_path}' desapareceu.")
            return "[Erro Transcrição: Arquivo desapareceu]"

        except Exception as e:
            logger.error(f"[TRANSCRIBE_AUDIO] Erro inesperado: {e}", exc_info=True)
            # Tentar Groq como último recurso
            if use_groq_fallback:
                logger.info("[TRANSCRIBE_AUDIO] Tentando Groq como fallback após erro inesperado...")
                groq_result = await _transcribe_with_groq(audio_file_path)
                if groq_result:
                    return groq_result
            return f"[Erro inesperado na transcrição: {str(e)}]"

    # Se OpenAI não está configurada, usar Groq diretamente
    else:
        logger.info("[TRANSCRIBE_AUDIO] OpenAI não configurada, usando Groq diretamente.")
        groq_result = await _transcribe_with_groq(audio_file_path)
        if groq_result:
            return groq_result
        return "[Erro Transcrição: Groq falhou]"

async def transcribe_audio_from_base64(base64_data: str, mimetype: str) -> str:
    """
    Decodifica dados de áudio base64, salva em arquivo temporário, converte para MP3,
    transcreve o MP3 e limpa os arquivos temporários.
    """
    logger.info(f"[TRANSCRIBE_BASE64] Iniciando transcrição de dados base64. MimeType: {mimetype}, Tamanho Base64: {len(base64_data)} caracteres.")
    original_temp_file_path: Optional[Path] = None
    mp3_temp_file_path: Optional[Path] = None
    
    try:
        if not base64_data or len(base64_data) < 100: # Verificação básica
            logger.error("[TRANSCRIBE_BASE64] Dados base64 inválidos ou muito curtos.")
            return "[Erro Transcrição: Dados base64 inválidos]"

        logger.debug("[TRANSCRIBE_BASE64] Decodificando dados base64 para bytes...")
        audio_bytes = await asyncio.to_thread(base64.b64decode, base64_data)
        logger.info(f"[TRANSCRIBE_BASE64] Dados base64 decodificados. Tamanho em bytes: {len(audio_bytes)}")

        # Determina a extensão do arquivo original a partir do mimetype
        original_extension = mimetypes.guess_extension((mimetype or '').split(';')[0], strict=False) or '.bin'
        logger.debug(f"[TRANSCRIBE_BASE64] Extensão original inferida do mimetype '{mimetype}': {original_extension}")

        temp_dir = settings.TEMP_AUDIO_DOWNLOAD_DIR
        temp_dir.mkdir(parents=True, exist_ok=True) # Garante que o diretório exista

        # Salva o arquivo original decodificado
        with tempfile.NamedTemporaryFile(delete=False, suffix=original_extension, dir=temp_dir, mode='wb') as temp_file:
            temp_file.write(audio_bytes)
            original_temp_file_path = Path(temp_file.name)
        logger.info(f"[TRANSCRIBE_BASE64] Áudio base64 salvo em arquivo temporário original: {original_temp_file_path}")

        # Converte o arquivo original para MP3
        logger.debug(f"[TRANSCRIBE_BASE64] Solicitando conversão de '{original_temp_file_path}' para MP3.")
        mp3_temp_file_path = await _convert_audio_to_mp3(original_temp_file_path, temp_dir)
        
        if not mp3_temp_file_path:
            logger.error(f"[TRANSCRIBE_BASE64] Falha na conversão para MP3 do arquivo: {original_temp_file_path}. Transcrição abortada.")
            return "[Erro Transcrição: Falha na conversão de áudio]"
        logger.info(f"[TRANSCRIBE_BASE64] Áudio convertido para MP3: {mp3_temp_file_path}")

        # Transcreve o arquivo MP3
        logger.debug(f"[TRANSCRIBE_BASE64] Solicitando transcrição do arquivo MP3: {mp3_temp_file_path}")
        transcription_result = await transcribe_audio(str(mp3_temp_file_path))
        logger.info(f"[TRANSCRIBE_BASE64] Resultado da transcrição para dados base64 (início): '{transcription_result[:100]}...'")
        return transcription_result

    except (ValueError, base64.binascii.Error) as e:
        logger.error(f"[TRANSCRIBE_BASE64] Erro ao decodificar dados base64: {e}", exc_info=True)
        return f"[Erro Transcrição: Dados base64 inválidos ({str(e)})]"
    except Exception as e:
        logger.error(f"[TRANSCRIBE_BASE64] Erro inesperado durante processo de transcrição de áudio base64: {e}", exc_info=True)
        return f"[Erro Transcrição: Processamento de áudio base64 ({str(e)})]"
    finally:
        # Limpeza dos arquivos temporários
        if original_temp_file_path and original_temp_file_path.exists():
            try:
                os.unlink(original_temp_file_path)
                logger.info(f"[TRANSCRIBE_BASE64] Arquivo temporário original ({original_temp_file_path}) limpo.")
            except OSError as unlink_err:
                logger.error(f"[TRANSCRIBE_BASE64] Erro ao deletar arquivo temporário original {original_temp_file_path}: {unlink_err}")
        if mp3_temp_file_path and mp3_temp_file_path.exists():
            try:
                os.unlink(mp3_temp_file_path)
                logger.info(f"[TRANSCRIBE_BASE64] Arquivo temporário MP3 ({mp3_temp_file_path}) limpo.")
            except OSError as unlink_err:
                logger.error(f"[TRANSCRIBE_BASE64] Erro ao deletar arquivo temporário MP3 {mp3_temp_file_path}: {unlink_err}")
        logger.debug("[TRANSCRIBE_BASE64] Processo de limpeza de arquivos temporários finalizado.")

async def download_and_transcribe_audio(audio_url: str) -> str:
    """
    Baixa áudio de uma URL, salva temporariamente, converte para MP3,
    transcreve o MP3 e limpa os arquivos temporários.
    """
    logger.info(f"[DOWNLOAD_TRANSCRIBE] Iniciando download e transcrição da URL: {audio_url}")
    original_temp_file_path: Optional[Path] = None
    mp3_temp_file_path: Optional[Path] = None
    
    try:
        temp_dir = settings.TEMP_AUDIO_DOWNLOAD_DIR
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Cria um nome de arquivo temporário inicial para o download
        with tempfile.NamedTemporaryFile(delete=False, suffix=".download_tmp", dir=temp_dir, mode='wb') as temp_file_obj:
            original_temp_file_path = Path(temp_file_obj.name)
        logger.debug(f"[DOWNLOAD_TRANSCRIBE] Arquivo temporário para download criado: {original_temp_file_path}")

        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            logger.info(f"[DOWNLOAD_TRANSCRIBE] Baixando áudio de {audio_url} para {original_temp_file_path}")
            async with client.stream("GET", audio_url) as response:
                response.raise_for_status() # Levanta exceção para códigos de erro HTTP
                
                content_type = response.headers.get('content-type', 'application/octet-stream')
                logger.info(f"[DOWNLOAD_TRANSCRIBE] Content-Type do áudio baixado: {content_type}")

                downloaded_size = 0
                with original_temp_file_path.open("wb") as f_out:
                    async for chunk in response.aiter_bytes():
                        f_out.write(chunk)
                        downloaded_size += len(chunk)
            logger.info(f"[DOWNLOAD_TRANSCRIBE] Download do áudio completo. Tamanho: {downloaded_size} bytes. Salvo em: {original_temp_file_path}")

        if downloaded_size == 0:
            logger.error(f"[DOWNLOAD_TRANSCRIBE] Arquivo baixado de {audio_url} está vazio. Transcrição abortada.")
            return "[Erro Transcrição: Arquivo de áudio baixado vazio]"

        # Tenta inferir a extensão correta e renomeia se necessário
        inferred_extension = mimetypes.guess_extension(content_type.split(';')[0], strict=False)
        # Heurística para áudios do WhatsApp que podem vir como octet-stream
        if not inferred_extension and 'whatsapp.net' in audio_url and 'audio' in audio_url:
            inferred_extension = '.ogg'
            logger.info(f"[DOWNLOAD_TRANSCRIBE] URL parece ser do WhatsApp e Content-Type é genérico. Assumindo extensão .ogg.")
        
        final_original_extension = inferred_extension or '.bin' # Fallback para .bin
        logger.debug(f"[DOWNLOAD_TRANSCRIBE] Extensão inferida para arquivo baixado: {final_original_extension}")
        
        renamed_original_path = original_temp_file_path.with_suffix(final_original_extension)
        if original_temp_file_path != renamed_original_path:
            os.rename(original_temp_file_path, renamed_original_path)
            original_temp_file_path = renamed_original_path # Atualiza o caminho
            logger.info(f"[DOWNLOAD_TRANSCRIBE] Arquivo temporário baixado renomeado para: {original_temp_file_path}")

        # Converte o arquivo baixado (com extensão correta) para MP3
        logger.debug(f"[DOWNLOAD_TRANSCRIBE] Solicitando conversão de '{original_temp_file_path}' para MP3.")
        mp3_temp_file_path = await _convert_audio_to_mp3(original_temp_file_path, temp_dir)

        if not mp3_temp_file_path:
            logger.error(f"[DOWNLOAD_TRANSCRIBE] Falha na conversão para MP3 do arquivo baixado: {original_temp_file_path}. Transcrição abortada.")
            return "[Erro Transcrição: Falha na conversão de áudio]"
        logger.info(f"[DOWNLOAD_TRANSCRIBE] Áudio baixado convertido para MP3: {mp3_temp_file_path}")

        # Transcreve o arquivo MP3
        logger.debug(f"[DOWNLOAD_TRANSCRIBE] Solicitando transcrição do arquivo MP3: {mp3_temp_file_path}")
        transcription_result = await transcribe_audio(str(mp3_temp_file_path))
        logger.info(f"[DOWNLOAD_TRANSCRIBE] Resultado da transcrição para áudio da URL (início): '{transcription_result[:100]}...'")
        return transcription_result

    except httpx.RequestError as e:
        logger.error(f"[DOWNLOAD_TRANSCRIBE] Erro de rede ao baixar áudio de {audio_url}: {e}", exc_info=True)
        return "[Erro Transcrição: Falha ao baixar áudio]"
    except httpx.HTTPStatusError as e:
        logger.error(f"[DOWNLOAD_TRANSCRIBE] Erro HTTP {e.response.status_code} ao baixar áudio de {audio_url}: {e.response.text[:200]}...", exc_info=True)
        return f"[Erro Transcrição: HTTP {e.response.status_code} ao baixar áudio]"
    except Exception as e:
        logger.error(f"[DOWNLOAD_TRANSCRIBE] Erro inesperado ao processar áudio da URL {audio_url}: {e}", exc_info=True)
        return f"[Erro Transcrição: Processamento de áudio da URL ({str(e)})]"
    finally:
        # Limpeza dos arquivos temporários
        if original_temp_file_path and original_temp_file_path.exists():
            try:
                os.unlink(original_temp_file_path)
                logger.info(f"[DOWNLOAD_TRANSCRIBE] Arquivo temporário original baixado ({original_temp_file_path}) limpo.")
            except OSError as unlink_err:
                logger.error(f"[DOWNLOAD_TRANSCRIBE] Erro ao deletar arquivo temporário original baixado {original_temp_file_path}: {unlink_err}")
        if mp3_temp_file_path and mp3_temp_file_path.exists():
            try:
                os.unlink(mp3_temp_file_path)
                logger.info(f"[DOWNLOAD_TRANSCRIBE] Arquivo temporário MP3 baixado ({mp3_temp_file_path}) limpo.")
            except OSError as unlink_err:
                logger.error(f"[DOWNLOAD_TRANSCRIBE] Erro ao deletar arquivo temporário MP3 baixado {mp3_temp_file_path}: {unlink_err}")
        logger.debug("[DOWNLOAD_TRANSCRIBE] Processo de limpeza de arquivos temporários finalizado.")

async def encode_audio_base64(file_path_str: str) -> Optional[str]:
    """Codifica um arquivo de áudio para uma string base64."""
    audio_path = Path(file_path_str)
    logger.debug(f"[ENCODE_AUDIO] Tentando codificar para base64: {audio_path}")
    if not audio_path.is_file():
        logger.error(f"[ENCODE_AUDIO] Arquivo de áudio não encontrado para codificação base64: {audio_path}")
        return None
    try:
        with open(audio_path, "rb") as audio_file:
            file_data = audio_file.read()
        encoded_bytes = await asyncio.to_thread(base64.b64encode, file_data)
        encoded_string = encoded_bytes.decode('utf-8')
        logger.info(f"[ENCODE_AUDIO] Arquivo '{audio_path.name}' (Tamanho: {len(file_data)} bytes) codificado para base64 (Tamanho string: {len(encoded_string)}).")
        return encoded_string
    except Exception as e:
        logger.error(f"[ENCODE_AUDIO] Erro ao codificar arquivo de áudio {audio_path} para base64: {e}", exc_info=True)
        return None

async def get_audio_duration(file_path_str: str) -> Optional[int]:
    """Obtém a duração de um arquivo de áudio em segundos usando mutagen."""
    audio_path = Path(file_path_str)
    logger.debug(f"[GET_DURATION] Tentando obter duração de: {audio_path}")
    if not audio_path.is_file():
        logger.error(f"[GET_DURATION] Arquivo de áudio não encontrado para verificação de duração: {audio_path}")
        return None
    try:
        def read_duration_sync(path_obj: Path) -> Optional[float]:
            try:
                audio_info = MutagenFile(path_obj)
                if audio_info and hasattr(audio_info, 'info') and hasattr(audio_info.info, 'length'):
                    return audio_info.info.length
                else:
                    logger.warning(f"[GET_DURATION] Mutagen não conseguiu ler informações de duração para: {path_obj}")
                    return None
            except MutagenError as me:
                logger.error(f"[GET_DURATION] Erro do Mutagen ao ler duração de {path_obj}: {me}")
                return None
            except Exception as e_mutagen: # Captura outras exceções do Mutagen
                 logger.error(f"[GET_DURATION] Erro inesperado na leitura da duração com Mutagen para {path_obj}: {e_mutagen}", exc_info=True)
                 return None

        duration_float = await asyncio.to_thread(read_duration_sync, audio_path)
        
        if duration_float is None:
            logger.warning(f"[GET_DURATION] Não foi possível determinar a duração para {audio_path.name}.")
            return None

        rounded_duration_int = math.ceil(duration_float)
        logger.info(f"[GET_DURATION] Duração de '{audio_path.name}': {duration_float:.2f}s. Arredondado para cima: {rounded_duration_int}s.")
        return rounded_duration_int
    except Exception as e: # Captura exceções fora da thread do Mutagen
        logger.error(f"[GET_DURATION] Erro ao obter duração do áudio para {audio_path}: {e}", exc_info=True)
        return None

logger.info("Módulo audio_utils.py carregado e logs configurados.")
