# app.py  ───────────────────────────────────────────────────────────
from flask import (
    Flask, request, send_file, jsonify,
    Response, abort, send_from_directory
)
from werkzeug.exceptions import HTTPException
from google.cloud import storage
from core.ffmpeg_processor import generate_final_video, group_images_by_prefix
import os, tempfile, uuid, logging, threading, time, json
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
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512 MB

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
logger       = logging.getLogger(__name__)
BUCKET_NAME  = os.environ.get("BUCKET_NAME", "dark_storage")

# ───────────────────────── UTILITÁRIOS DE STORAGE ────────────────────────
def generate_download_url(blob, expires=3600, disposition=None):
    return blob.generate_signed_url(
        version="v4",
        expiration=expires,
        method="GET",
        response_disposition=disposition
    )

def allowed_file(fname, typ):
    exts = {
        "image": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
        "audio": [".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"]
    }.get(typ, [])
    return any(fname.lower().endswith(e) for e in exts)
# ──────────────────────────────────────────────────────────────────────────

# ╭─────────────────────────── GET SIGNED URL ══════════════════════════════╮
@app.route("/get_signed_url", methods=["POST"])
def get_signed_url():
    logger.info("📝 Solicitando signed URL…")
    data = request.get_json()
    if not data or 'filename' not in data or 'file_type' not in data:
        return jsonify(error="filename e file_type são obrigatórios"), 400

    fname, ftype = data['filename'], data['file_type']
    if '../' in fname or '\\' in fname:
        return jsonify(error="Nome de arquivo inválido"), 400
    if not allowed_file(fname, ftype):
        return jsonify(error="Tipo de arquivo não permitido"), 400

    client  = storage.Client()
    blob    = client.bucket(BUCKET_NAME).blob(fname)
    url     = blob.generate_signed_url(
        version="v4",
        expiration=datetime.now(timezone.utc) + timedelta(hours=1),
        method="PUT",
        service_account_email="storage-signer-sa@dark-creator-video-app.iam.gserviceaccount.com"
    )
    logger.info("✅ Signed URL gerada para %s", fname)
    return jsonify({'signed_url': url, 'filename': fname})
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
    logger.info("📥 /create_video recebido")
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

    threading.Thread(target=process_video,
                     args=(data, session_id),
                     daemon=True).start()

    return jsonify(session_id=session_id,
                   message="Processo do vídeo iniciado"), 202
# ╰─────────────────────────────────────────────────────────────────────────╯

# ╭────────────────────────── PROCESSAMENTO ════════════════════════════════╮
def process_video(data, session_id):
    def cb(pct: int, phase: str = "processing"):
        _set_progress(session_id,
                      status=phase,
                      progress=int(pct),
                      completed=False)

    try:
        images       = data['image_filenames']
        audio        = data.get('audio_filename')
        filename     = data.get('filename', 'my_video.mp4')
        aspect_ratio = data.get('aspect_ratio', '9:16')
        green_sec    = float(data.get('green_duration', 3))

        logger.info("📥 %d imagens; áudio: %s", len(images), bool(audio))
        _set_progress(session_id, status="downloading", progress=0)

        with tempfile.TemporaryDirectory() as tmp:
            client = storage.Client()
            bucket = client.bucket(BUCKET_NAME)

            img_paths = []
            for bname in images:
                dst = os.path.join(tmp, os.path.basename(bname))
                bucket.blob(bname).download_to_filename(dst)
                img_paths.append(dst)

            audio_path = None
            if audio:
                audio_path = os.path.join(tmp, 'audio.mp3')
                bucket.blob(audio).download_to_filename(audio_path)

            cb(20)

            groups   = group_images_by_prefix(img_paths)
            out_name = filename if filename.endswith('.mp4') else f'{filename}.mp4'
            out_path = os.path.join(tmp, out_name)

            generate_final_video(
                groups, audio_path, out_path,
                green_sec, aspect_ratio.replace(':', 'x'),
                lambda p: cb(p, "processing")
            )

            cb(90, "uploading")  # 90 % antes do upload

            dest_blob = f'videos/{session_id}.mp4'
            bucket.blob(dest_blob).upload_from_filename(out_path)

            url = bucket.blob(dest_blob).generate_signed_url(
                version="v4",
                expiration=timedelta(hours=1),
                response_disposition=f'attachment; filename="{out_name}"'
            )

        _set_progress(session_id,
                      status="completed",
                      message="Video ready!",
                      download_url=url,
                      filename=out_name,
                      progress=100,
                      completed=True)
        logger.info("🎉 Vídeo pronto: %s", url)

    except Exception as e:
        logger.exception("❌ Erro no processamento")
        _set_progress(session_id,
                      status="error", message=str(e), completed=True)
# ╰─────────────────────────────────────────────────────────────────────────╯

# ╭──────────────────────— ROTAS DE ARQUIVOS ESTÁTICOS —────────────────────╮
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
    blob_path = f"videos/{session_id}.mp4"
    client    = storage.Client()
    bucket    = client.bucket(BUCKET_NAME)
    blob      = bucket.get_blob(blob_path)
    if not blob:
        abort(404, description="Vídeo não encontrado")
    url = generate_download_url(blob,
                                disposition=f'attachment; filename="{os.path.basename(blob.name)}"')
    return jsonify(download_url=url)
# ╰─────────────────────────────────────────────────────────────────────────╯

@app.route("/list_videos")
def list_videos():
    names = [b.name for b in storage.Client().bucket(BUCKET_NAME).list_blobs(prefix="videos/")]
    return jsonify(names)

@app.route("/health")
def health_check():
    return jsonify(status="healthy",
                   service="darkcreator100k-mergevideo",
                   timestamp=datetime.now(timezone.utc).isoformat()), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
