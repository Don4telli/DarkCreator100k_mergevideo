from flask import Flask, request, send_file, render_template_string
from core.ffmpeg_processor import generate_final_video
import tempfile
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    with open("index.html") as f:
        return render_template_string(f.read())

@app.route("/create_video", methods=["POST"])
def create_video():
    image_files = request.files.getlist("images")
    audio_file = request.files.get("audio")
    filename = request.form.get("filename", "video_final.mp4")
    aspect_ratio = request.form.get("aspect_ratio", "9:16")
    green_duration = float(request.form.get("green_duration", "3.0"))

    if not image_files or not audio_file:
        return "Missing images or audio", 400

    with tempfile.TemporaryDirectory() as tmpdir:
        image_paths = []
        for image in image_files:
            img_path = os.path.join(tmpdir, secure_filename(image.filename))
            image.save(img_path)
            image_paths.append(img_path)

        audio_path = os.path.join(tmpdir, secure_filename(audio_file.filename))
        audio_file.save(audio_path)

        output_path = os.path.join(tmpdir, secure_filename(filename))

        try:
            generate_final_video(image_paths, audio_path, output_path, green_duration)
            return send_file(output_path, as_attachment=True, download_name=filename)
        except Exception as e:
            return f"Erro ao criar vídeo: {str(e)}", 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)# trigger
# trigger
