
import os
import subprocess
import tempfile
import re
from typing import List
from pathlib import Path
from collections import defaultdict
import logging

tmp_dir = "/tmp"
input_txt_path = os.path.join(tmp_dir, "input.txt")
concat_list = os.path.join(tmp_dir, "concat.txt")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def group_images_by_prefix(image_paths: List[str]):
    print("🔍 Agrupando imagens por prefixo...")
    groups = defaultdict(list)
    for path in image_paths:
        filename = os.path.basename(path)
        match = re.match(r'^([A-Za-z]+)', filename)
        if match:
            prefix = match.group(1).upper()
            groups[prefix].append(path)
        else:
            groups['DEFAULT'].append(path)
    for prefix in groups:
        groups[prefix].sort(key=lambda x: int(re.findall(r'\d+', os.path.basename(x))[0]))
    print("✅ Grupos criados:", list(groups.keys()))
    return groups


def get_audio_duration(audio_path: str) -> float:
    print("⏱ Calculando duração do áudio:", audio_path)
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    duration = float(result.stdout)
    print("📏 Duração:", duration)
    return duration


def create_video_from_images_and_audio(image_paths: List[str], audio_path: str, output_path: str):
    print("🎥 Criando vídeo a partir de imagens e áudio...")
    duration = get_audio_duration(audio_path)
    print("⏳ Duração total do áudio:", duration)
    print("🖼 Número de imagens:", len(image_paths))
    frame_duration = duration / len(image_paths)
    print("🕒 Duração por frame:", frame_duration)
    with tempfile.TemporaryDirectory() as tmpdir:
        input_txt_path = os.path.join(tmpdir, "input.txt")
        with open(input_txt_path, "w") as f:
            for img in image_paths:
                f.write(f"file '{img}'\n")
                f.write(f"duration {frame_duration}\n")
            f.write(f"file '{image_paths[-1]}'\n")
        command = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", input_txt_path,
            "-i", audio_path, "-shortest", "-vsync", "vfr",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            output_path
        ]
        print("🚀 Executando comando FFmpeg para criar vídeo...")
        subprocess.run(command, check=True)
        print("✅ Vídeo criado em:", output_path)


def create_green_clip(output_path: str, duration: int = 3, resolution=(1080, 1920)):
    print("🟢 Criando clipe verde...")
    width, height = resolution
    command = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=green:s={width}x{height}:d={duration}",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-shortest",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        output_path
    ]
    subprocess.run(command, check=True)
    print("✅ Clipe verde criado em:", output_path)


def generate_final_video(image_paths: List[str], audio_path: str, output_path: str, green_duration: int = 3):
    print("🛠 Gerando vídeo final...")
    groups = group_images_by_prefix(image_paths)
    print("📁 Grupos de imagens:", list(groups.keys()))
    with tempfile.TemporaryDirectory() as tmpdir:
        part_videos = []
        green_clip_path = os.path.join(tmpdir, "green.mp4")
        create_green_clip(green_clip_path, duration=green_duration)
        for prefix, images in sorted(groups.items()):
            print(f"📽 Criando parte do vídeo para prefixo {prefix} com {len(images)} imagens...")
            video_part_path = os.path.join(tmpdir, f"{prefix}.mp4")
            create_video_from_images_and_audio(images, audio_path, video_part_path)
            print(f"✅ Parte {prefix} criada em:", video_part_path)
            part_videos.append(video_part_path)
            part_videos.append(green_clip_path)
        if part_videos and part_videos[-1] == green_clip_path:
            part_videos.pop()  # remove tela verde do final
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            for video in part_videos:
                f.write(f"file '{video}'\n")
        print("🔗 Preparando lista de concatenação...")
        command = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_list,
            "-c", "copy", output_path
        ]
        print("🚀 Concatenando vídeos...")
        subprocess.run(command, check=True)
        print("🎉 Vídeo final gerado em:", output_path)
