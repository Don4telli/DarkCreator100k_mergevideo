
# Use imagem Python oficial
FROM python:3.10-slim

# Instala dependências do sistema
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Define diretório de trabalho
WORKDIR /app

# Copia os arquivos do projeto
COPY . .

# Instala dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Expõe a porta que o Flask usará
EXPOSE 8080

# Define o comando para iniciar a aplicação
CMD ["python", "app.py"]
