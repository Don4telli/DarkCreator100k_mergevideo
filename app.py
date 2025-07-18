
from flask import Flask, request, jsonify, send_file
from core.ffmpeg_processor import generate_final_video
import tempfile
import os

app = Flask(__name__)

@app.route("/create_video", methods=["POST"])
def create_video():
    data = request.get_json()
    image_paths = data.get("image_paths", [])
    audio_path = data.get("audio_path")

    if not image_paths or not audio_path:
        return jsonify({"error": "Missing image_paths or audio_path"}), 400

    output_dir = tempfile.mkdtemp()
    output_path = os.path.join(output_dir, "final_video.mp4")

    try:
        generate_final_video(image_paths, audio_path, output_path, green_duration=3)

        return send_file(output_path, as_attachment=True, download_name="video_final.mp4")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
