from flask import Flask, request, send_file, jsonify, Response, abort, send_from_directory
from werkzeug.exceptions import HTTPException
from google.cloud import storage
from core.ffmpeg_processor import generate_final_video, group_images_by_prefix
import os, tempfile, uuid, logging, threading, time, json
from datetime import datetime, timedelta
from flask_cors import CORS
import os, tempfile, logging, shutil


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512MB

# Global progress tracking
progress_data = {}

# Configure CORS for all necessary endpoints
CORS(app, resources={
    r"/get_signed_url": {"origins": "*"},
    r"/create_video": {"origins": "*"},
    r"/progress/*": {"origins": "*"},
    r"/download/*": {"origins": "*"}
})

@app.errorhandler(413)
def too_large(e):
    return "Arquivo muito grande. O limite é 512MB.", 413

@app.errorhandler(HTTPException)
def handle_http(e):
    return jsonify(error=e.description), e.code

@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled exception")
    return jsonify(error="Internal server error"), 500



logger       = logging.getLogger(__name__)
BUCKET_NAME  = os.environ.get("BUCKET_NAME", "dark_storage")

def generate_download_url(blob, expires=3600):
    """
    Gera uma signed URL V4 válida por `expires` segundos (padrão: 3600s = 1h).
    """
    return blob.generate_signed_url(
        version="v4",
        expiration=expires,   # agora é um inteiro de segundos
        method="GET"
    )


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
        
        # Validate filename to prevent path traversal
        if '../' in filename or '\\' in filename:
            logger.info(f"❌ Nome de arquivo inválido (path traversal): {filename}")
            return jsonify(error="Nome de arquivo inválido"), 400
        
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
        method="PUT",
        service_account_email="storage-signer-sa@dark-creator-video-app.iam.gserviceaccount.com"
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

@app.route("/progress/<session_id>")
def get_progress(session_id):
    """Server-Sent Events endpoint for progress updates"""
    def generate():
        while True:
            if session_id in progress_data:
                data = progress_data[session_id]
                yield f"data: {json.dumps(data)}\n\n"
                if data.get('completed', False):
                    # Clean up completed progress data to prevent memory leaks
                    del progress_data[session_id]
                    break
            else:
                yield f"data: {{\"status\": \"waiting\"}}\n\n"
            time.sleep(0.5)
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive'
    })

@app.route('/create_video', methods=['POST'])
def create_video():
    """Endpoint que dispara o processamento em background e devolve o session_id."""
    logger.info("📥 Requisição /create_video recebida")
    logger.info("🔍 Headers: %s", dict(request.headers))

    # ── 1. Ler e validar o JSON ───────────────────────────────────────────────
    try:
        data = request.get_json(force=True)
    except Exception as e:
        logger.warning("❌ JSON inválido: %s", e)
        return jsonify({'error': 'JSON inválido'}), 400

    image_filenames = data.get('image_filenames')
    if not image_filenames or not isinstance(image_filenames, list):
        return jsonify({'error': 'image_filenames (lista) é obrigatório'}), 400

    audio_filename = data.get('audio_filename')

    # path-traversal check
    for fname in image_filenames + ([audio_filename] if audio_filename else []):
        if not fname:
            continue
        if fname.startswith('/') or '..' in fname or '\\' in fname:
            logger.warning("❌ Tentativa de path traversal: %s", fname)
            return jsonify({'error': 'Nome de arquivo inválido'}), 400

    # ── 2. Cria session_id e inicia thread ───────────────────────────────────
    session_id = str(uuid.uuid4())
    progress_data[session_id] = {'status': 'queued', 'progress': 0}

    thread = threading.Thread(
        target=process_video,          # NOVA assinatura = 2 args
        args=(data, session_id),
        daemon=True
    )
    thread.start()
    logger.info("🚀 Thread iniciada para session_id=%s", session_id)

    # ── 3. Resposta imediata ─────────────────────────────────────────────────
    return jsonify({
        'session_id': session_id,
        'message': 'Video processing started'
    }), 202

def progress_callback(percent: int) -> None:
    """
        Atualiza o progresso do job (0-100).

        Chamado de dentro de core/ffmpeg_processor.generate_final_video().
        """
    progress_data[session_id]['progress'] = percent

    progress_data[session_id] = {
            'status': 'processing',
            'progress': progress_percent,
            'message': message,
            'current': current,
            'total': total
    }    
    
    # Start video processing in background thread
    thread = threading.Thread(target=process_video,
                              args=(data, session_id))
    thread.start()
    
    return jsonify({
        'session_id': session_id,
        'message': 'Video processing started'
    })

def process_video(data, session_id):
    """
    Executa o pipeline:
      20% baixar → 90% gerar vídeo → 100% upload + URL
    Atualiza progress_data[session_id] a cada etapa.
    """
    # ── callback usado pelo ffmpeg_processor ──────────────────────────
    def progress_callback(percent: int) -> None:
        progress_data[session_id]['progress'] = percent

    try:
        # ── 0. parâmetros vindos do front-end ─────────────────────────
        images        = data['image_filenames']          # lista no bucket
        audio         = data.get('audio_filename')       # opcional
        filename      = data.get('filename', 'my_video.mp4')
        aspect_ratio  = data.get('aspect_ratio', '9:16')
        green_seconds = float(data.get('green_duration', 3))

        logger.info("📥 %d imagens; áudio: %s", len(images), bool(audio))
        progress_data[session_id] = {'status': 'downloading', 'progress': 0}

        # ── 1. baixar mídias ──────────────────────────────────────────
        with tempfile.TemporaryDirectory() as tmp:
            image_paths = []
            client = storage.Client()
            bucket = client.bucket(BUCKET_NAME)

            for blob_name in images:
                dst = os.path.join(tmp, os.path.basename(blob_name))
                bucket.blob(blob_name).download_to_filename(dst)
                image_paths.append(dst)

            audio_path = None
            if audio:
                audio_path = os.path.join(tmp, 'audio.mp3')
                bucket.blob(audio).download_to_filename(audio_path)

            progress_callback(20)                 # → 20 %

            # ── 2. gerar vídeo ────────────────────────────────────────
            groups   = group_images_by_prefix(image_paths)
            out_name = filename if filename.endswith('.mp4') else f'{filename}.mp4'
            out_path = os.path.join(tmp, out_name)

            generate_final_video(
                groups, audio_path, out_path,
                green_seconds, aspect_ratio.replace(':', 'x'),
                progress_callback
            )
            progress_callback(90)                 # → 90 %

            # ── 3. upload + URL ───────────────────────────────────────
            blob_final = f'videos/{session_id}.mp4'
            blob       = bucket.blob(blob_final)
            blob.upload_from_filename(out_path)
            signed_url = blob.generate_signed_url(
                expiration=datetime.timedelta(hours=1),  # válido por 1 h
                version="v4"
            )

        # ── sucesso ──────────────────────────────────────────────────
        progress_callback(100)                   # → 100 %
        progress_data[session_id].update({
            'status':       'completed',
            'message':      'Video ready!',
            'download_url': signed_url,
            'filename':     out_name,
            'completed':    True,
        })
        logger.info("🎉 Vídeo pronto: %s", signed_url)

    except Exception as e:
        logger.exception("❌ Erro no processamento")
        progress_data[session_id] = {
            'status': 'error', 'message': str(e), 'completed': True
        }


@app.route("/")
def index():
    return send_file("templates/index.html")

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico')

@app.route('/@vite/client')
def vite_client():
    """Handle Vite client requests to prevent 404 errors"""
    return '', 204

@app.route("/download/<session_id>", methods=["GET"])
def download_video(session_id):
    blob_path = f"videos/{session_id}.mp4"
    client = storage.Client()
    
    try:
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.get_blob(blob_path)
        
        if blob is None:
            app.logger.info(f"Blob não encontrado: {blob_path}")
            abort(404, description="Vídeo não encontrado no bucket")
        
        url = generate_download_url(blob)
        app.logger.info(f"Signed URL gerada com sucesso para {blob_path}")
        return jsonify({ "download_url": url })
        
    except Exception as e:
        app.logger.error(f"Erro no download endpoint para {blob_path}: {e}", exc_info=True)
        abort(500, description="Erro acessando o Storage")
    finally:
        client.close()

@app.route("/list_videos", methods=["GET"])
def list_videos():
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    names = [b.name for b in bucket.list_blobs(prefix="videos/")]
    return jsonify(names)

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