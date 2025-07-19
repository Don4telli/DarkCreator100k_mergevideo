from flask import Flask, request, send_file, render_template
from core.ffmpeg_processor import generate_final_video 
from werkzeug.utils import secure_filename
from google.cloud import storage
import tempfile
import os
import uuid

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512MB upload limit

@app.errorhandler(413)
def request_entity_too_large(error):
    return "Arquivo muito grande. O limite é 512MB.", 413



# It's good practice to create a 'templates' folder for your HTML files.
# The following line assumes index.html is in a 'templates' folder.
# If index.html is in the same folder as app.py, your original code will work,
# but using a 'templates' folder is the standard for Flask.
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html") 

BUCKET_NAME = "dark_storage"
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
ALLOWED_AUDIO_EXTENSIONS = {'.mp3'}

def is_allowed(filename, allowed_exts):
    return any(filename.lower().endswith(ext) for ext in allowed_exts)

def upload_to_bucket(bucket_name, file_storage, destination_blob_name):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_file(file_storage)
    return blob.name

def download_from_bucket(bucket_name, blob_name, destination_file):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(destination_file)

@app.route("/create_video", methods=["POST"])
def create_video():
    print("📥 Recebendo solicitação para criar vídeo...")
    image_files = request.files.getlist("images")
    audio_file = request.files.get("audio")
    filename = request.form.get("filename", "video_final.mp4")
    aspect_ratio = request.form.get("aspect_ratio", "9:16")
    green_duration = float(request.form.get("green_duration", "3.0"))
    print("🖼 Imagens recebidas:", len(image_files))
    print("🎵 Áudio recebido:", audio_file.filename if audio_file else "Nenhum")
    print("📄 Nome do arquivo de saída:", filename)
    print("📐 Aspect ratio:", aspect_ratio)
    print("🟢 Duração da tela verde:", green_duration)
    if not image_files or not audio_file:
        print("❌ Erro: Imagens ou áudio ausentes")
        return "Missing images or audio", 400
    for image in image_files:
        if not is_allowed(image.filename, ALLOWED_IMAGE_EXTENSIONS):
            print("❌ Formato de imagem inválido:", image.filename)
            return f"Formato inválido para imagem: {image.filename}", 400
    if not is_allowed(audio_file.filename, ALLOWED_AUDIO_EXTENSIONS):
        print("❌ Formato de áudio inválido:", audio_file.filename)
        return f"Formato inválido para áudio: {audio_file.filename}", 400
    uploaded_image_blobs = []
    for image in image_files:
        blob_name = f"uploads/{uuid.uuid4()}_{secure_filename(image.filename)}"
        print("☁️ Fazendo upload de imagem para o bucket:", blob_name)
        upload_to_bucket(BUCKET_NAME, image, blob_name)
        uploaded_image_blobs.append(blob_name)
    audio_blob_name = f"uploads/{uuid.uuid4()}_{secure_filename(audio_file.filename)}"
    print("☁️ Fazendo upload de áudio para o bucket:", audio_blob_name)
    upload_to_bucket(BUCKET_NAME, audio_file, audio_blob_name)
    with tempfile.TemporaryDirectory() as tmpdir:
        image_paths = []
        for blob_name in uploaded_image_blobs:
            local_path = os.path.join(tmpdir, os.path.basename(blob_name))
            print("⬇️ Baixando imagem do bucket:", blob_name)
            download_from_bucket(BUCKET_NAME, blob_name, local_path)
            image_paths.append(local_path)
        audio_path = os.path.join(tmpdir, os.path.basename(audio_blob_name))
        print("⬇️ Baixando áudio do bucket:", audio_blob_name)
        download_from_bucket(BUCKET_NAME, audio_blob_name, audio_path)
        output_path = os.path.join(tmpdir, secure_filename(filename))
        print("🛠 Iniciando geração do vídeo final...")
        try:
            generate_final_video(image_paths, audio_path, output_path, green_duration)
            print("✅ Vídeo criado com sucesso, enviando arquivo:", output_path)
            return send_file(output_path, as_attachment=True, download_name=filename)
        except Exception as e:
            print("❌ Erro ao criar vídeo:", str(e))
            return f"Erro ao criar vídeo: {str(e)}", 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)