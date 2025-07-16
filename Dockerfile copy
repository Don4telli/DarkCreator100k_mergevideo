# Use uma imagem oficial e leve do Python
FROM python:3.11-slim

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Instala o FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de dependências primeiro
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do seu projeto para o contêiner
COPY . .

# ==============================================================================
# CORREÇÃO FINAL - Força 1 worker e usa threads para compartilhar memória
# ==============================================================================
CMD gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT} api.index:app