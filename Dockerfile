# Use uma imagem oficial e leve do Python
FROM python:3.11-slim

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Instala o FFmpeg (a causa de todos os nossos problemas) e outras ferramentas
# O '&' no final é para rodar em segundo plano e não interagir
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de dependências primeiro, para aproveitar o cache em builds futuros
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o resto do seu projeto para o contêiner
COPY . .

# Comando para iniciar seu servidor web quando o contêiner rodar
# Ele diz ao Gunicorn para rodar o objeto 'app' que está no arquivo 'api/index.py'
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "api.index:app"]