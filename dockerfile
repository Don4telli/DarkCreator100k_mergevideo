# Use a imagem Python
FROM python:3.10

# Define diretório de trabalho
WORKDIR /app

# Copia todos os arquivos
COPY . .

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Expõe a porta usada pelo Flask
EXPOSE 8080

# Comando para rodar o app
CMD ["python", "app.py"]
