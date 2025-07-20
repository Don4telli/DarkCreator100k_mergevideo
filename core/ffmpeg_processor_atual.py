# ──────────────────────────────────────────────────────────────────────────────
#  core/ffmpeg_processor.py
# ──────────────────────────────────────────────────────────────────────────────
import os, re, json, logging, shutil, tempfile, subprocess
from collections import defaultdict
from typing import List

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 1. UTILITÁRIOS
# ──────────────────────────────────────────────────────────────────────────────
def _run(cmd: list[str], quiet=False) -> None:
    """Wrapper de subprocess.run com logging bonito."""
    log_cmd = " ".join(cmd)
    logger.info("🖥️  %s", log_cmd if not quiet else cmd[0])
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE if quiet else None,
                   stderr=subprocess.STDOUT if quiet else None)


def _audio_duration(path: str) -> float:
    """Retorna a duração (seg) do arquivo de áudio via ffprobe."""
    out = subprocess.check_output([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_entries", "format=duration", path
    ], text=True)
    return float(json.loads(out)["format"]["duration"])


def group_images_by_prefix(image_paths: List[str]):
    logger.info("🔍 Agrupando imagens por prefixo...")
    groups = defaultdict(list)
    for p in image_paths:
        filename = os.path.basename(p)
        m = re.match(r'^([A-Za-z]+)', filename)
        prefix = m.group(1).upper() if m else "DEFAULT"
        groups[prefix].append(p)

    # ordena A1, A2 … A15 corretamente
    for lst in groups.values():
        lst.sort(key=lambda x: int(re.findall(r'\d+', os.path.basename(x))[0]))
    logger.info("✅ Grupos criados: %s", list(groups.keys()))
    return groups


# ──────────────────────────────────────────────────────────────────────────────
# 2. BLOCO A / B / C …  (imagem + áudio completo, sem -shortest)
# ──────────────────────────────────────────────────────────────────────────────
def make_block(images: list[str], audio_path: str, output_path: str,
               fps: int = 25) -> None:
    """
    Cria um MP4 com todas as imagens + áudio integral.
    Cada imagem fica   duração_áudio / N.
    """
    if not images:
        raise ValueError("Lista de imagens vazia")

    dur_audio = _audio_duration(audio_path)
    dur_frame = dur_audio / len(images)
    logger.info("🖼️  %d imgs  |  Áudio %.2fs  → %.3fs por frame",
                len(images), dur_audio, dur_frame)

    # lista concat
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as ftxt:
        for img in images[:-1]:
            ftxt.write(f"file '{img}'\n")
            ftxt.write(f"duration {dur_frame}\n")
        ftxt.write(f"file '{images[-1]}'\n")
        list_path = ftxt.name

    # step 1: renderiza vídeo silencioso
    tmp_vid = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
    _run(["ffmpeg", "-y", "-safe", "0", "-f", "concat", "-i", list_path,
          "-vsync", "vfr", "-r", str(fps),
          "-pix_fmt", "yuv420p", "-c:v", "libx264", tmp_vid], quiet=True)

    # step 2: muxa com áudio (sem -shortest)
    _run(["ffmpeg", "-y", "-i", tmp_vid, "-i", audio_path,
          "-c:v", "copy", "-c:a", "aac",
          "-map", "0:v:0", "-map", "1:a:0", output_path], quiet=True)

    os.remove(list_path); os.remove(tmp_vid)
    logger.info("✅ Bloco pronto → %s", output_path)


# ──────────────────────────────────────────────────────────────────────────────
# 3. TELA VERDE (clipe filler com silêncio)
# ──────────────────────────────────────────────────────────────────────────────
def create_green_clip(path, duration, resolution):
    w, h = resolution.split('x')
    _run(["ffmpeg", "-y",
          "-f", "lavfi", "-i", f"color=c=00ff00:s={w}x{h}:d={duration}",
          "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
          "-c:v", "libx264", "-t", str(duration),
          "-pix_fmt", "yuv420p", "-c:a", "aac", path], quiet=True)
    logger.info("🟩 Tela verde criada %ss → %s", duration, path)


# ──────────────────────────────────────────────────────────────────────────────
# 4. PIPELINE FINAL
# ──────────────────────────────────────────────────────────────────────────────
def generate_final_video(image_groups, audio_path, output_path,
                         green_duration, resolution, progress_cb):
    """
    Para cada grupo A/B/C:
      • renderiza bloco com make_block (áudio completo)
      • insere tela verde silenciosa entre blocos
    Concatena tudo sem recodificar vídeo; áudio contínuo.
    Envia progress em ~10 %  →  100 %.
    """
    tmpdir = tempfile.mkdtemp()
    part_videos = []

    total = len(image_groups)
    logger.info("🎞️ Começando geração – %d blocos", total)

    # ---- loop pelos blocos ----
    for idx, (prefix, imgs) in enumerate(sorted(image_groups.items()), 1):
        logger.info("📂 [%d/%d] Bloco «%s» (%d imgs)",
                    idx, total, prefix, len(imgs))

        part_path = os.path.join(tmpdir, f"{prefix}.mp4")
        make_block(imgs, audio_path, part_path)
        part_videos.append(part_path)

        if idx != total:  # tela verde entre blocos
            green = os.path.join(tmpdir, f"green_{idx}.mp4")
            create_green_clip(green, green_duration, resolution)
            part_videos.append(green)

        # progresso em steps de 10 %  (10 → 80)
        progress_cb(10 + int(idx / total * 70))

    progress_cb(90)  # blocos prontos
    logger.info("🔗 Concat final com %d partes", len(part_videos))

    # ---- concat final ----
    concat_list = os.path.join(tmpdir, "concat.txt")
    with open(concat_list, "w") as f:
        for p in part_videos:
            f.write(f"file '{p}'\n")

    _run(["ffmpeg", "-y", "-safe", "0", "-f", "concat", "-i", concat_list,
          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-movflags", "+faststart", output_path], quiet=True)

    progress_cb(100)
    logger.info("🎉 Vídeo final → %s", output_path)
    shutil.rmtree(tmpdir, ignore_errors=True)
# ──────────────────────────────────────────────────────────────────────────────
