from flask import Flask, request, send_file, jsonify
from google.cloud import storage
from core.ffmpeg_processor import generate_final_video
import os
import tempfile
import uuid
import logging
from flask import jsonify
from datetime import datetime, timedelta
from flask_cors import CORS


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512MB

# Permite CORS só para o POST /get_signed_url vindo do seu serviço Cloud Run
CORS(app, resources={
    r"/get_signed_url": {
        "origins": "https://darkcreator100k-mergevideo-998923445962.southamerica-east1.run.app",
        "methods": ["POST", "OPTIONS"]
    }
})

@app.errorhandler(413)
def too_large(e):
    return "Arquivo muito grande. O limite é 512MB.", 413

@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception(f"❌ Erro não tratado: {str(e)}")
    return jsonify(error=str(e)), 500



BUCKET_NAME = "dark_storage"

def allowed_file(filename, file_type):
    if file_type == "image":
        allowed_exts = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]
    elif file_type == "audio":
        allowed_exts = [".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"]
    else:
        return False
    return any(filename.lower().endswith(ext) for ext in allowed_exts)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route("/get_signed_url", methods=["POST"])
def get_signed_url():
    logger.info("📝 Recebendo solicitação para gerar signed URL...")
    try:
        data = request.get_json()
        if not data or 'filename' not in data or 'file_type' not in data:
            logger.info("❌ Dados inválidos na solicitação")
            return jsonify(error="filename e file_type são obrigatórios"), 400
        
        filename = data['filename']
        file_type = data['file_type']
        
        if not allowed_file(filename, file_type):
            logger.info(f"❌ Tipo de arquivo não permitido: {filename}")
            return jsonify(error="Tipo de arquivo não permitido"), 400
        
       # Manter exatamente o nome original
        object_name = filename
        
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(object_name)
        
        # Gerar signed URL para upload (válida por 1 hora)
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.utcnow() + timedelta(hours=1),
            method="PUT"
        )
        
        logger.info(f"✅ Signed URL gerada para: {object_name}")
        return jsonify({
            'signed_url': signed_url,
            'filename': object_name
        })
        
    except Exception as e:
        logger.exception(f"❌ Erro ao gerar signed URL: {str(e)}")
        return jsonify(error=str(e)), 500

def upload_to_bucket(bucket_name, file_storage, destination_blob_name):
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_file(file_storage)
        return blob.name
    except Exception as e:
        logger.exception(f"❌ Erro ao fazer upload para o bucket: {str(e)}")
        raise

def download_from_bucket(bucket_name, blob_name, destination_file):
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.download_to_filename(destination_file)
    except Exception as e:
        logger.exception(f"❌ Erro ao baixar do bucket: {str(e)}")
        raise

def upload_video_to_bucket(bucket_name, local_file_path, destination_blob_name):
    """Faz upload do vídeo para o bucket e retorna a URL de download"""
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        
        # Upload do arquivo
        blob.upload_from_filename(local_file_path)
        
        # Gerar URL de download com validade de 24 horas
        download_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.utcnow() + timedelta(hours=24),
            method="GET"
        )
        
        return download_url
    except Exception as e:
        logger.exception(f"❌ Erro ao fazer upload do vídeo para o bucket: {str(e)}")
        raise

@app.route("/create_video", methods=["POST"])
def create_video():
    logger.info("📥 Recebendo solicitação para criar vídeo...")
    logger.info(f"📋 Headers da requisição: {dict(request.headers)}")
    logger.info(f"🔍 Método da requisição: {request.method}")
    try:
        data = request.get_json()
        if not data:
            logger.info("❌ Dados JSON não fornecidos")
            return jsonify(error="Dados JSON são obrigatórios"), 400
        
        # Verificar se os nomes dos arquivos foram fornecidos
        image_filenames = data.get('image_filenames', [])
        audio_filename = data.get('audio_filename')
        filename = data.get('filename', 'my_video.mp4')
        aspect_ratio = data.get('aspect_ratio', '9:16')
        green_duration = float(data.get('green_duration', 5.0))
        
        if not image_filenames:
            logger.info("❌ Arquivos de imagem não fornecidos")
            return jsonify(error="image_filenames é obrigatório"), 400
        
        logger.info(f"📂 Processando {len(image_filenames)} imagens")
        if audio_filename:
            logger.info(f"🎵 Áudio fornecido: {audio_filename}")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Baixar imagens do bucket
            image_paths = []
            for i, blob_name in enumerate(image_filenames):
                logger.info(f"⬇️ Baixando imagem {i+1}/{len(image_filenames)}: {blob_name}")
                local_path = os.path.join(tmpdir, f"image_{i}.jpg")
                download_from_bucket(BUCKET_NAME, blob_name, local_path)
                image_paths.append(local_path)
            
            # Baixar áudio do bucket (se fornecido)
            audio_path = None
            if audio_filename:
                logger.info(f"⬇️ Baixando áudio: {audio_filename}")
                audio_path = os.path.join(tmpdir, "audio.mp3")
                download_from_bucket(BUCKET_NAME, audio_filename, audio_path)
            
            # Gerar vídeo
            output_filename = filename if filename.endswith('.mp4') else f"{filename}.mp4"
            output_path = os.path.join(tmpdir, output_filename)
            
            logger.info("🎬 Iniciando geração do vídeo...")
            generate_final_video(image_paths, audio_path, output_path, green_duration, aspect_ratio)
            
            # Upload do vídeo para o bucket
            logger.info("☁️ Fazendo upload do vídeo para o bucket...")
            video_blob_name = f"videos/{output_filename}"
            download_url = upload_video_to_bucket(BUCKET_NAME, output_path, video_blob_name)
            
            logger.info(f"✅ Vídeo criado e enviado para o bucket com sucesso!")
            return jsonify({
                'success': True,
                'download_url': download_url,
                'filename': output_filename
            })
            
    except Exception as e:
        logger.exception(f"❌ Erro ao criar vídeo: {str(e)}")
        return jsonify(error=str(e)), 500

@app.route("/")
def index():
    return send_file("templates/index.html")

@app.route("/health")
def health_check():
    """Endpoint de health check para o Cloud Run"""
    return jsonify({
        'status': 'healthy',
        'service': 'darkcreator100k-mergevideo',
        'timestamp': datetime.utcnow().isoformat()
    }), 200

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)