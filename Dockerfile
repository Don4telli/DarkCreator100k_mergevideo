# Use uma imagem oficial e leve do Python
FROM python:3.11-slim

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# ==============================================================================
# A CORREÇÃO DEFINITIVA - Define a variável de ambiente PYTHONPATH
# Isso diz ao Python para sempre procurar módulos na nossa pasta raiz /app.
# ==============================================================================
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Instala dependências do sistema necessárias
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de dependências primeiro
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do seu projeto para o contêiner
COPY . .

# Comando final para iniciar o servidor, usando a forma "shell" para que ${PORT} funcione
CMD gunicorn --worker-class gthread --threads 4 --workers 1 --timeout 600 --bind 0.0.0.0:${PORT} api.index:app