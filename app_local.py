# app_local.py  ───────────────────────────────────────────────────────────
# Versão local completa com todas as funcionalidades do app.py online
# mas usando armazenamento local em vez do Google Cloud Storage
from flask import (
    Flask, request, send_file, jsonify,
    Response, abort, send_from_directory
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
    return f"http://localhost:8082/local_upload/{unique_filename}", unique_filename

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
@app.route("/local_upload/<filename>", methods=["PUT"])
def local_upload(filename):
    """Endpoint que simula o upload para GCS, mas salva localmente"""
    try:
        file_data = request.get_data()
        file_path = os.path.join(UPLOADS_DIR, filename)
        
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        logger.info("✅ Arquivo salvo localmente: %s", filename)
        return "", 200
    except Exception as e:
        logger.error("❌ Erro no upload local: %s", str(e))
        return str(e), 500
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

# ╭────────────────────────── PROCESSAMENTO LOCAL ══════════════════════════╮
def process_video_local(data, session_id):
    def cb(pct: int, phase: str = "processing", msg: str | None = None):
        _set_progress(session_id,
                    status=phase,
                    progress=int(pct),
                    message=msg,
                    completed=False)

    try:
        images       = data['image_filenames']
        audio        = data.get('audio_filename')
        filename     = data.get('filename', 'my_video.mp4')
        aspect_ratio = data.get('aspect_ratio', '9:16')
        green_sec    = float(data.get('green_duration', 3))

        logger.info("📥 %d imagens; áudio: %s (LOCAL)", len(images), bool(audio))
        _set_progress(session_id, status="downloading", progress=0)

        # ── 1. copiar arquivos locais ────────────────────────────────────
        with tempfile.TemporaryDirectory() as tmp:
            img_paths = []
            for fname in images:
                src = os.path.join(UPLOADS_DIR, fname)
                if not os.path.exists(src):
                    raise FileNotFoundError(f"Arquivo não encontrado: {fname}")
                dst = os.path.join(tmp, os.path.basename(fname))
                shutil.copy2(src, dst)
                img_paths.append(dst)

            audio_path = None
            if audio:
                audio_src = os.path.join(UPLOADS_DIR, audio)
                if not os.path.exists(audio_src):
                    raise FileNotFoundError(f"Áudio não encontrado: {audio}")
                audio_path = os.path.join(tmp, 'audio.mp3')
                shutil.copy2(audio_src, audio_path)

            # 20 % — arquivos copiados
            cb(20, "processing",
                "Arquivos preparados — iniciando renderização…")

            # ── 2. gerar vídeo ────────────────────────────────────────
            groups   = group_images_by_prefix(img_paths)
            out_name = filename if filename.endswith('.mp4') else f'{filename}.mp4'
            out_path = os.path.join(tmp, out_name)

            generate_final_video(
                groups, audio_path, out_path,
                green_sec, aspect_ratio.replace(':', 'x'),
                cb
            )

            # 90 % — salvando vídeo
            cb(90, "uploading", "Salvando vídeo…")

            # Salvar vídeo final
            final_video_path = os.path.join(VIDEOS_DIR, f'{session_id}.mp4')
            shutil.copy2(out_path, final_video_path)

            # URL de download local
            download_url = f"http://localhost:8082/download/{session_id}"

        _set_progress(session_id,
                      status="completed",
                      message="Video ready!",
                      download_url=download_url,
                      filename=out_name,
                      progress=100,
                      completed=True)
        logger.info("🎉 Vídeo pronto (LOCAL): %s", download_url)

    except Exception as e:
        logger.exception("❌ Erro no processamento (LOCAL)")
        _set_progress(session_id,
                      status="error", message=str(e), completed=True)
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

# ╭────────────────────────── DOWNLOAD DE VÍDEO ════════════════════════════╮
@app.route("/download/<session_id>", methods=["GET"])
def download_video(session_id):
    video_path = os.path.join(VIDEOS_DIR, f"{session_id}.mp4")
    if not os.path.exists(video_path):
        abort(404, description="Vídeo não encontrado")
    
    return send_file(video_path, 
                     as_attachment=True, 
                     download_name=f"video_{session_id}.mp4",
                     mimetype="video/mp4")
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
    app.run(host="0.0.0.0", port=8082, debug=True)