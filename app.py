from flask import Flask, request, send_file, jsonify
from google.cloud import storage
from core.ffmpeg_processor import generate_final_video
import os
import tempfile
import uuid
import logging
from flask import jsonify
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512MB

@app.errorhandler(413)
def too_large(e):
    return "Arquivo muito grande. O limite é 512MB.", 413

@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception(f"❌ Erro não tratado: {str(e)}")
    return jsonify(error=str(e)), 500



BUCKET_NAME = "darkcreator100k-mergevideo"

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
        
        # Gerar nome único para o arquivo
        unique_filename = f"{uuid.uuid4()}_{filename}"
        
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(unique_filename)
        
        # Gerar signed URL para upload (válida por 1 hora)
        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.utcnow() + timedelta(hours=1),
            method="PUT",
            content_type=request.headers.get('Content-Type', 'application/octet-stream')
        )
        
        logger.info(f"✅ Signed URL gerada para: {unique_filename}")
        return jsonify({
            'signed_url': signed_url,
            'blob_name': unique_filename
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

@app.route("/create_video", methods=["POST"])
def create_video():
    logger.info("📥 Recebendo solicitação para criar vídeo...")
    try:
        data = request.get_json()
        if not data:
            logger.info("❌ Dados JSON não fornecidos")
            return jsonify(error="Dados JSON são obrigatórios"), 400
        
        # Verificar se os nomes dos arquivos foram fornecidos
        image_blob_names = data.get('image_files', [])
        audio_blob_name = data.get('audio_file')
        green_duration = int(data.get('green_duration', 3))
        
        if not image_blob_names or not audio_blob_name:
            logger.info("❌ Arquivos de imagem ou áudio não fornecidos")
            return jsonify(error="image_files e audio_file são obrigatórios"), 400
        
        logger.info(f"📂 Processando {len(image_blob_names)} imagens e 1 áudio")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Baixar imagens do bucket
            image_paths = []
            for i, blob_name in enumerate(image_blob_names):
                logger.info(f"⬇️ Baixando imagem {i+1}/{len(image_blob_names)}: {blob_name}")
                local_path = os.path.join(tmpdir, f"image_{i}.jpg")
                download_from_bucket(BUCKET_NAME, blob_name, local_path)
                image_paths.append(local_path)
            
            # Baixar áudio do bucket
            logger.info(f"⬇️ Baixando áudio: {audio_blob_name}")
            audio_path = os.path.join(tmpdir, "audio.mp3")
            download_from_bucket(BUCKET_NAME, audio_blob_name, audio_path)
            
            # Gerar vídeo
            output_filename = f"video_{uuid.uuid4().hex[:8]}.mp4"
            output_path = os.path.join(tmpdir, output_filename)
            
            logger.info("🎬 Iniciando geração do vídeo...")
            generate_final_video(image_paths, audio_path, output_path, green_duration)
            logger.info(f"✅ Vídeo criado com sucesso, enviando arquivo: {output_path}")
            return send_file(output_path, as_attachment=True, download_name=output_filename)
            
    except Exception as e:
        logger.exception(f"❌ Erro ao criar vídeo: {str(e)}")
        return jsonify(error=str(e)), 500

@app.route("/")
def index():
    return send_file("templates/index.html")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)