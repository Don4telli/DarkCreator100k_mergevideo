# app_local_test.py  ───────────────────────────────────────────────────────────
# Versão local completa com todas as funcionalidades do app.py online
# mas usando armazenamento local em vez do Google Cloud Storage
from flask import (
    Flask, request, send_file, jsonify,
    Response, abort, send_from_directory, make_response
)
from werkzeug.exceptions import HTTPException
from core.ffmpeg_processor import generate_final_video, group_images_by_prefix
import os, tempfile, uuid, logging, threading, time, json, shutil
from datetime import datetime, timedelta, timezone
from flask_cors import CORS

# ───────────────────────── CONTROLE DE PROGRESSO ──────────────────────────
progress_data: dict[str, dict] = {}            # session_id → estado
_progress_lock = threading.Lock()

def _set_progress(session_id: str, **kwargs):
    """Atualiza (com lock) o dicionário progress_data."""
    with _progress_lock:
        progress_data.setdefault(session_id, {})
        progress_data[session_id].update(kwargs)
# ──────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512 MB

# CORS (pode ajustar domínios depois)
CORS(app, resources={
    r"/get_signed_url": {"origins": "*"},
    r"/create_video":   {"origins": "*"},
    r"/progress/*":     {"origins": "*"},
    r"/download/*":     {"origins": "*"}
})

# ───────────────────────── HANDLERS DE ERRO BÁSICOS ───────────────────────
@app.errorhandler(413)
def too_large(e):                    return "Arquivo muito grande.", 413

@app.errorhandler(HTTPException)
def handle_http(e):                 return jsonify(error=e.description), e.code

@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled exception")
    return jsonify(error="Internal server error"), 500
# ──────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Diretórios locais para simular o bucket
LOCAL_STORAGE_DIR = os.path.join(os.getcwd(), "local_storage")
UPLOADS_DIR = os.path.join(LOCAL_STORAGE_DIR, "uploads")
VIDEOS_DIR = os.path.join(LOCAL_STORAGE_DIR, "videos")

# Criar diretórios se não existirem
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(VIDEOS_DIR, exist_ok=True)

BUCKET_NAME = "darkcreator100k-mergevideo"

# ───────────────────────── UTILITÁRIOS DE STORAGE ────────────────────────
def allowed_file(fname, typ):
    exts = {
        "image": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
        "audio": [".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"]
    }.get(typ, [])
    return any(fname.lower().endswith(e) for e in exts)

def generate_local_signed_url(filename):
    """Simula uma signed URL para upload local"""
    unique_filename = f"{uuid.uuid4()}_{filename}"
    # Retorna uma URL local que será interceptada pelo nosso endpoint
    return f"http://localhost:8081/local_upload/{unique_filename}", unique_filename

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ╭─────────────────────────── GET SIGNED URL ══════════════════════════════╮
@app.route("/get_signed_url", methods=["POST"])
def get_signed_url():
    logger.info("📝 Solicitando signed URL (LOCAL)…")
    data = request.get_json()
    if not data or 'filename' not in data or 'file_type' not in data:
        return jsonify(error="filename e file_type são obrigatórios"), 400

    fname, ftype = data['filename'], data['file_type']
    if '../' in fname or '\\' in fname:
        return jsonify(error="Nome de arquivo inválido"), 400
    if not allowed_file(fname, ftype):
        return jsonify(error="Tipo de arquivo não permitido"), 400

    signed_url, unique_filename = generate_local_signed_url(fname)
    logger.info("✅ Signed URL local gerada para %s", unique_filename)
    return jsonify({'signed_url': signed_url, 'filename': unique_filename})
# ╰─────────────────────────────────────────────────────────────────────────╯

# ╭─────────────────────────── UPLOAD LOCAL ════════════════════════════════╮
@app.route("/local_upload/<filename>", methods=["PUT", "POST", "OPTIONS"])
def local_upload(filename):
    """Endpoint que simula o upload para GCS, mas salva localmente"""
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'PUT, POST, OPTIONS')
        return response
    
    try:
        file_data = request.get_data()
        if not file_data:
            logger.error("❌ Dados do arquivo vazios para: %s", filename)
            return "Dados do arquivo vazios", 400
            
        file_path = os.path.join(UPLOADS_DIR, filename)
        
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        logger.info("✅ Arquivo salvo localmente: %s (%d bytes)", filename, len(file_data))
        
        response = make_response("", 200)
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
        
    except Exception as e:
        logger.error("❌ Erro no upload local: %s", str(e))
        response = make_response(str(e), 500)
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
# ╰─────────────────────────────────────────────────────────────────────────╯

# ╭────────────────────────── SSE DE PROGRESSO ═════════════════════════════╮
@app.route("/progress/<session_id>")
def progress_stream(session_id):
    """Stream de progresso (Server‑Sent Events)."""
    def event_stream():
        last = None
        while True:
            with _progress_lock:
                snap = progress_data.get(session_id, {}).copy()

            if snap and snap != last:
                yield f"data: {json.dumps(snap)}\n\n"
                last = snap
                if snap.get("completed"):
                    with _progress_lock:
                        progress_data.pop(session_id, None)
                    break

            if not snap and last != {"status": "waiting"}:
                last = {"status": "waiting"}
                yield 'data: {"status":"waiting"}\n\n'

            time.sleep(0.5)

    return Response(event_stream(),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "Connection": "keep-alive"})
# ╰─────────────────────────────────────────────────────────────────────────╯

# ╭──────────────────────────── CREATE VIDEO ═══════════════════════════════╮
@app.route('/create_video', methods=['POST'])
def create_video():
    logger.info("📥 /create_video recebido (LOCAL)")
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify(error="JSON inválido"), 400

    imgs = data.get('image_filenames')
    if not imgs or not isinstance(imgs, list):
        return jsonify(error="image_filenames (lista) é obrigatório"), 400

    aud = data.get('audio_filename')
    for f in imgs + ([aud] if aud else []):
        if f and (f.startswith('/') or '..' in f or '\\' in f):
            return jsonify(error="Nome de arquivo inválido"), 400

    session_id = str(uuid.uuid4())
    _set_progress(session_id, status="queued", progress=0, completed=False)

    threading.Thread(target=process_video_local,
                     args=(data, session_id),
                     daemon=True).start()

    return jsonify(session_id=session_id,
                   message="Processo do vídeo iniciado (LOCAL)"), 202
# ╰─────────────────────────────────────────────────────────────────────────╯

# ╭─────────────────────── PROCESSAMENTO LOCAL ═════════════════════════════╮
def process_video_local(data, session_id):
    """Processa vídeo usando arquivos locais."""
    try:
        _set_progress(session_id, status="processing", progress=10,
                      message="Iniciando processamento...")

        imgs = data['image_filenames']
        aud = data.get('audio_filename')
        fname = data.get('filename', 'video.mp4')
        aspect = data.get('aspect_ratio', '9:16')
        green_dur = float(data.get('green_duration', 5.0))

        # Verificar arquivos locais
        _set_progress(session_id, progress=20, message="Verificando arquivos...")
        img_paths = []
        for img in imgs:
            path = os.path.join(UPLOADS_DIR, img)
            if not os.path.exists(path):
                raise FileNotFoundError(f"Imagem não encontrada: {img}")
            img_paths.append(path)

        aud_path = None
        if aud:
            aud_path = os.path.join(UPLOADS_DIR, aud)
            if not os.path.exists(aud_path):
                raise FileNotFoundError(f"Áudio não encontrado: {aud}")

        # Agrupar imagens
        _set_progress(session_id, progress=30, message="Agrupando imagens...")
        grouped = group_images_by_prefix(img_paths)

        # Gerar vídeo
        _set_progress(session_id, progress=50, message="Gerando vídeo...")
        output_name = fname if fname.endswith('.mp4') else f"{fname}.mp4"
        output_path = os.path.join(VIDEOS_DIR, output_name)

        def progress_callback(progress, status, message=""):
            _set_progress(session_id, status=status, progress=progress, message=message)
        
        generate_final_video(
            image_groups=grouped,
            audio_path=aud_path,
            output_path=output_path,
            green_sec=int(green_dur),
            aspect_ratio=aspect,
            progress_cb=progress_callback
        )

        _set_progress(session_id, status="completed", progress=100,
                      message="Vídeo criado com sucesso!",
                      download_url=f"/download/{output_name}",
                      filename=output_name, completed=True)

    except Exception as e:
        logger.exception("Erro no processamento local")
        _set_progress(session_id, status="error", message=str(e), completed=True)
# ╰─────────────────────────────────────────────────────────────────────────╯

# ╭──────────────────────────── DOWNLOAD ═══════════════════════════════════╮
@app.route("/download/<filename>")
def download_video(filename):
    """Download de vídeo local."""
    if '..' in filename or '/' in filename or '\\' in filename:
        abort(400)
    return send_from_directory(VIDEOS_DIR, filename, as_attachment=True)
# ╰─────────────────────────────────────────────────────────────────────────╯

# ╭──────────────────────— ROTAS DE ARQUIVOS ESTÁTICOS —────────────────────╮
@app.route("/")
def index():                       return send_file("templates/index.html")

@app.route('/static/<path:filename>')
def static_files(filename):        return send_from_directory('static', filename)

@app.route('/favicon.ico')
def favicon():                     return send_from_directory('static', 'favicon.ico')

@app.route('/@vite/client')
def vite_client():                 return '', 204
# ╰─────────────────────────────────────────────────────────────────────────╯

@app.route("/list_videos")
def list_videos():
    videos = [f for f in os.listdir(VIDEOS_DIR) if f.endswith('.mp4')]
    return jsonify(videos)

@app.route("/health")
def health_check():
    return jsonify(status="healthy",
                   service="darkcreator100k-mergevideo-local",
                   mode="LOCAL",
                   timestamp=datetime.now(timezone.utc).isoformat()), 200

if __name__ == "__main__":
    print("🏠 === MODO LOCAL COMPLETO ===")
    print("✅ Todas as funcionalidades do app online")
    print("📁 Armazenamento local em ./local_storage/")
    print("🎬 Processamento real de vídeo com FFmpeg")
    print("📊 Server-Sent Events para progresso")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8080, debug=True)