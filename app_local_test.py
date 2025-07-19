from flask import Flask, request, send_file, jsonify
import os
import tempfile
import uuid
import logging
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
    """Versão de teste que simula a geração de signed URL"""
    logger.info("📝 Recebendo solicitação para gerar signed URL (MODO TESTE)...")
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
        
        # Simular signed URL (para teste local)
        fake_signed_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{unique_filename}?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=test"
        
        logger.info(f"✅ Signed URL simulada para: {unique_filename}")
        return jsonify({
            'signed_url': fake_signed_url,
            'filename': unique_filename
        })
        
    except Exception as e:
        logger.exception(f"❌ Erro ao gerar signed URL: {str(e)}")
        return jsonify(error=str(e)), 500

@app.route("/create_video", methods=["POST"])
def create_video():
    """Versão de teste que simula a criação de vídeo"""
    logger.info("📥 Recebendo solicitação para criar vídeo (MODO TESTE)...")
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
        
        logger.info(f"📂 Processando {len(image_filenames)} imagens (SIMULADO)")
        if audio_filename:
            logger.info(f"🎵 Áudio fornecido: {audio_filename} (SIMULADO)")
        
        # Simular processamento
        import time
        time.sleep(2)  # Simular tempo de processamento
        
        # Simular URL de download
        output_filename = filename if filename.endswith('.mp4') else f"{filename}.mp4"
        fake_download_url = f"https://storage.googleapis.com/{BUCKET_NAME}/videos/{output_filename}?X-Goog-Algorithm=GOOG4-RSA-SHA256"
        
        logger.info(f"✅ Vídeo simulado criado com sucesso!")
        return jsonify({
            'success': True,
            'download_url': fake_download_url,
            'filename': output_filename,
            'message': 'MODO TESTE - Vídeo simulado criado'
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
        'mode': 'LOCAL_TEST',
        'timestamp': datetime.utcnow().isoformat()
    }), 200

if __name__ == "__main__":
    print("🧪 === MODO TESTE LOCAL ===")
    print("⚠️  Este é um servidor de teste que simula o GCS")
    print("📝 Para produção, use o app.py original com credenciais")
    print("=" * 50)
    app.run(host='0.0.0.0', port=8082, debug=True)