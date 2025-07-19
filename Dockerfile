# Use uma imagem oficial do Python como base
FROM python:3.10-slim

# Define o diretório de trabalho
WORKDIR /app

# Copia os arquivos de dependência e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do app
COPY . .

# Expõe a porta usada pelo Gunicorn
EXPOSE 8080

# Comando para iniciar o app com Gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
