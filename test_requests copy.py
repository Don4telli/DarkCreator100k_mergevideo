import requests
import os

# Caminho dos seus arquivos
base_path = "/Users/admin/Desktop/APP/test_assets"
image_files = [f for f in os.listdir(base_path) if f.lower().endswith((".png", ".jpg"))]
image_paths = [os.path.join(base_path, f) for f in sorted(image_files)]

audio_path = os.path.join(base_path, "main_audio.mp3")

# Endpoint local
url = "http://localhost:8080/create_video"

# Payload
payload = {
    "image_paths": image_paths,
    "audio_path": audio_path
}

# Requisição
response = requests.post(url, json=payload)

# Ver resultado
if response.status_code == 200:
    with open("video_final.mp4", "wb") as f:
        f.write(response.content)
    print("✅ Vídeo salvo como video_final.mp4")
else:
    print("❌ Erro:", response.status_code)
    print(response.text)
