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
# COMANDO FINAL E CORRETO (FORMA SHELL)
# Executa o comando sem colchetes para que a variável ${PORT} seja processada.
# ==============================================================================
CMD gunicorn --worker-class gthread --threads 4 --workers 1 --bind 0.0.0.0:${PORT} api.index:app