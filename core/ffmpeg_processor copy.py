
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
    logger.info("🔍 Agrupando imagens por prefixo...")
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
    logger.info(f"✅ Grupos criados: {list(groups.keys())}")
    return groups


def get_audio_duration(audio_path: str) -> float:
    if audio_path is None:
        return 0.0
    logger.info(f"⏱ Calculando duração do áudio: {audio_path}")
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        duration = float(result.stdout)
        logger.info(f"📏 Duração: {duration}")
        return duration
    except Exception as e:
        logger.exception(f"❌ Erro ao calcular duração do áudio: {str(e)}")
        raise


def create_video_from_images_and_audio(image_paths: List[str], audio_path: str, output_path: str):
    logger.info("🎥 Criando vídeo a partir de imagens...")
    
    if audio_path:
        logger.info(f"🎵 Com áudio: {audio_path}")
        duration = get_audio_duration(audio_path)
        logger.info(f"⏳ Duração total do áudio: {duration}")
        frame_duration = duration / len(image_paths)
    else:
        logger.info("🔇 Sem áudio - usando duração padrão de 2s por imagem")
        frame_duration = 2.0  # 2 segundos por imagem quando não há áudio
    
    logger.info(f"🖼 Número de imagens: {len(image_paths)}")
    logger.info(f"🕒 Duração por frame: {frame_duration}")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        input_txt_path = os.path.join(tmpdir, "input.txt")
        with open(input_txt_path, "w") as f:
            for img in image_paths:
                f.write(f"file '{img}'\n")
                f.write(f"duration {frame_duration}\n")
            f.write(f"file '{image_paths[-1]}'\n")
        
        if audio_path:
            command = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", input_txt_path,
                "-i", audio_path, "-shortest", "-vsync", "vfr",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                output_path
            ]
        else:
            command = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", input_txt_path,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                output_path
            ]
        
        logger.info("🚀 Executando comando FFmpeg para criar vídeo...")
        subprocess.run(command, check=True)
        logger.info(f"✅ Vídeo criado em: {output_path}")


def create_green_clip(output_path: str, duration: int = 3, resolution=(1080, 1920), with_audio=True):
    logger.info("🟢 Criando clipe verde...")
    width, height = resolution
    
    if with_audio:
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
    else:
        command = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=green:s={width}x{height}:d={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            output_path
        ]
    
    try:
        subprocess.run(command, check=True)
        logger.info(f"✅ Clipe verde criado em: {output_path}")
    except Exception as e:
        logger.exception(f"❌ Erro ao criar clipe verde: {str(e)}")
        raise


def generate_final_video(image_paths: List[str], audio_path: str, output_path: str, green_duration: float = 3.0, aspect_ratio: str = "9:16", progress_callback=None):
    logger.info("🛠 Gerando vídeo final...")
    
    # Determinar resolução baseada no aspect ratio
    if aspect_ratio == "9:16":
        resolution = (1080, 1920)  # Portrait
    elif aspect_ratio == "16:9":
        resolution = (1920, 1080)  # Landscape
    else:
        resolution = (1080, 1920)  # Default para portrait
    
    logger.info(f"📐 Aspect ratio: {aspect_ratio}, Resolução: {resolution}")
    
    groups = group_images_by_prefix(image_paths)
    logger.info(f"📁 Grupos de imagens: {list(groups.keys())}")
    
    has_audio = audio_path is not None
    logger.info(f"🎵 Áudio presente: {has_audio}")
    
    total_groups = len(groups)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        part_videos = []
        green_clip_path = os.path.join(tmpdir, "green.mp4")
        
        if progress_callback:
            progress_callback("Creating green screen clips", 0, total_groups)
        create_green_clip(green_clip_path, duration=int(green_duration), resolution=resolution, with_audio=has_audio)
        
        for i, (prefix, images) in enumerate(sorted(groups.items())):
            if progress_callback:
                progress_callback(f"Processing video group {prefix}", i, total_groups)
            
            logger.info(f"📽 Criando parte do vídeo para prefixo {prefix} com {len(images)} imagens...")
            video_part_path = os.path.join(tmpdir, f"{prefix}.mp4")
            create_video_from_images_and_audio(images, audio_path, video_part_path)
            logger.info(f"✅ Parte {prefix} criada em: {video_part_path}")
            part_videos.append(video_part_path)
            part_videos.append(green_clip_path)
        
        if part_videos and part_videos[-1] == green_clip_path:
            part_videos.pop()  # remove tela verde do final
        
        if progress_callback:
            progress_callback("Concatenating video segments", total_groups, total_groups)
        
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            for video in part_videos:
                f.write(f"file '{video}'\n")
        
        logger.info("🔗 Preparando lista de concatenação...")
        command = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_list,
            "-c", "copy", output_path
        ]
        logger.info("🚀 Concatenando vídeos...")
        subprocess.run(command, check=True)
        logger.info(f"🎉 Vídeo final gerado em: {output_path}")
