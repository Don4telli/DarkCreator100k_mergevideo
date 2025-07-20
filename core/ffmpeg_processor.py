
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


def create_green_clip(path, duration, resolution):
    """
    Gera um clipe de tela verde com faixa de silêncio.
    """
    w, h = resolution.split('x')
    logger.info("🟩 Criando tela verde %ss (%s×%s)…", duration, w, h)

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=00ff00:s={w}x{h}:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264", "-preset", "veryfast",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        path
    ], check=True)

    logger.info("✅ Tela verde pronta → %s", path)


def generate_final_video(image_groups, audio_path, output_path,
                         green_duration, resolution, progress_cb):
    """
    Cria cada bloco (A, B, C…) com áudio completo, insere clipes verde-silenciosos
    e concatena tudo num único vídeo final.
    """
    tmpdir = tempfile.mkdtemp()
    part_videos = []

    total_groups = len(image_groups)
    logger.info("🎞️ Iniciando geração – %d grupos de imagens", total_groups)

    for idx, (prefix, images) in enumerate(sorted(image_groups.items()), 1):
        logger.info("📂 Grupo %d/%d «%s» – %d imagens",
                    idx, total_groups, prefix, len(images))
        progress_cb(int(idx / total_groups * 40))

        # 1️⃣ Arquivo-texto para concat interna do grupo
        img_list = os.path.join(tmpdir, f"{prefix}.txt")
        with open(img_list, "w") as f:
            for img in images:
                f.write(f"file '{img}'\n")
                f.write("duration 1\n")
            f.write(f"file '{images[-1]}'\n")  # bug-workaround

        part_path = os.path.join(tmpdir, f"{prefix}.mp4")
        logger.info("🛠️  Gerando bloco «%s»…", prefix)
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", img_list,
            "-i", audio_path,
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac",
            "-shortest",
            "-pix_fmt", "yuv420p",
            part_path
        ], check=True)
        logger.info("✅ Bloco «%s» pronto → %s", prefix, part_path)
        part_videos.append(part_path)

        # 2️⃣ Tela verde entre blocos
        if idx != total_groups:
            green_clip = os.path.join(tmpdir, f"green_{idx}.mp4")
            create_green_clip(green_clip, green_duration, resolution)
            part_videos.append(green_clip)

    progress_cb(60)
    logger.info("🔗 Concat final (%d partes)…", len(part_videos))

    # 3️⃣ Lista para concat final
    concat_list = os.path.join(tmpdir, "all.txt")
    with open(concat_list, "w") as f:
        for p in part_videos:
            f.write(f"file '{p}'\n")

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c:v", "copy",                 # vídeo já codificado
        "-c:a", "aac", "-b:a", "192k",  # remuxa áudio contínuo
        "-movflags", "+faststart",
        output_path
    ], check=True)

    logger.info("🎉 Vídeo final criado → %s", output_path)
    progress_cb(100)

    shutil.rmtree(tmpdir, ignore_errors=True)
    logger.info("🧹 Limpeza temporários concluída")

