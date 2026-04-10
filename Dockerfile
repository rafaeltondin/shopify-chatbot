# Use uma imagem base Python oficial para Linux (Bookworm)
# Python 3.11 é recomendado para compatibilidade com google-api-core e outras dependências modernas
FROM python:3.11-slim-bookworm

# CRÍTICO: Define que está rodando em Docker para que o config.py
# use APENAS variáveis de ambiente (do Easypanel) e NÃO tente carregar .env
ENV RUNNING_IN_SHOPIFY_BOT_DOCKER=true

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Instala ffmpeg e outras dependências do sistema
# ffmpeg é necessário para processamento de áudio (transcrição, etc.)
# git é útil para quaisquer dependências de repositório (não estritamente necessário para requirements.txt estático)
# build-essential é para compilação de certas bibliotecas Python se necessário
# default-libmysqlclient-dev é para PyMySQL (client C library)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libpq-dev default-libmysqlclient-dev gcc g++ build-essential libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

# Copia o arquivo requirements.txt para o WORKDIR
COPY requirements.txt .

# Instala as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o restante do código da aplicação para o contêiner
COPY . .

# Expõe a porta que a aplicação FastAPI escutará (padrão 8000 no settings.py)
EXPOSE 8000

# Comando para iniciar a aplicação usando Uvicorn
# 'main:app' refere-se ao objeto 'app' dentro do arquivo 'main.py'
# '--host 0.0.0.0' faz com que o servidor escute em todas as interfaces de rede
# O log_level será configurado via variáveis de ambiente ou settings.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
