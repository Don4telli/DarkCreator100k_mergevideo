FROM python:3.10-slim

WORKDIR /app

# Instala ffmpeg e outras dependências do sistema antes do Python
RUN apt-get update && apt-get install -y ffmpeg

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]


