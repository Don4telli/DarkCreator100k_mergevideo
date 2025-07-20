# ─────────────────────────────────────────────────────────────────────────────
#  ffmpeg_processor.py  –  versão unificada
# ─────────────────────────────────────────────────────────────────────────────
import os, re, json, logging, shutil, tempfile, subprocess
from collections import defaultdict
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ╭──────────────────────────────────────────────────────────────────────────╮
# │ 1. Utils básicos                                                        │
# ╰──────────────────────────────────────────────────────────────────────────╯
def _run(cmd: list[str]) -> None:
    """Executa FFmpeg/FFprobe com log bonito + check=True."""
    logger.info("🖥️  %s", " ".join(cmd))
    subprocess.run(cmd, check=True)

def _audio_duration(path: str) -> float:
    """Duração do áudio (segundos) via ffprobe."""
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_entries", "format=duration", path],
        text=True
    )
    return float(json.loads(out)["format"]["duration"])

def _resolution_from_ratio(ratio: str) -> Tuple[int, int]:
    """'9:16' → (1080,1920); '16:9' → (1920,1080)."""
    return (1080, 1920) if ratio == "9:16" else (1920, 1080)

def group_images_by_prefix(img_paths: List[str]):
    groups = defaultdict(list)
    for p in img_paths:
        m = re.match(r'^([A-Za-z]+)', os.path.basename(p))
        key = m.group(1).upper() if m else "DEFAULT"
        groups[key].append(p)
    for lst in groups.values():
        lst.sort(key=lambda x: int(re.findall(r'\d+', os.path.basename(x))[0]))
    logger.info("✅ Prefixos: %s", list(groups.keys()))
    return groups

# ╭──────────────────────────────────────────────────────────────────────────╮
# │ 2. Bloco A / B / C – imagens + áudio integral                           │
# ╰──────────────────────────────────────────────────────────────────────────╯
def _make_block(images: List[str], audio: str, out_mp4: str,
                resolution: Tuple[int, int], fps: int = 25) -> None:
    if not images:
        raise ValueError("Lista de imagens vazia")

    dur_audio = _audio_duration(audio)
    dur_frame = dur_audio / len(images)
    w, h      = resolution
    logger.info("🖼️  %d imgs  |  %.2fs áudio  →  %.3fs/frame", len(images),
                dur_audio, dur_frame)

    # lista-concat temporária
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        for img in images[:-1]:
            f.write(f"file '{img}'\n")
            f.write(f"duration {dur_frame}\n")
        f.write(f"file '{images[-1]}'\n")
        lst = f.name

    # 1. vídeo silencioso pad+scale
    vid_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
    _run([
        "ffmpeg", "-y", "-safe", "0", "-f", "concat", "-i", lst,
        "-vsync", "vfr", "-r", str(fps),
        "-vf", (f"scale={w}:{h}:force_original_aspect_ratio=cover,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"),
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
        vid_tmp
    ])

    # 2. muxa áudio integral (sem -shortest)
    _run([
        "ffmpeg", "-y",
        "-i", vid_tmp, "-i", audio,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-map", "0:v:0", "-map", "1:a:0",
        out_mp4
    ])

    os.remove(lst); os.remove(vid_tmp)
    logger.info("✅ Bloco salvo → %s", out_mp4)

# ╭──────────────────────────────────────────────────────────────────────────╮
# │ 3. Tela verde (silêncio + resolução correta)                            │
# ╰──────────────────────────────────────────────────────────────────────────╯
def _make_green(path: str, dur: int, resolution: Tuple[int, int]) -> None:
    w, h = resolution
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=00ff00:s={w}x{h}:d={dur}",
        "-f", "lavfi", "-i", "anullsrc=sample_rate=48000:cl=stereo",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-t", str(dur),
        path
    ])
    logger.info("🟩 Tela verde %ss → %s", dur, path)

# ╭──────────────────────────────────────────────────────────────────────────╮
# │ 4. Pipeline principal                                                   │
# ╰──────────────────────────────────────────────────────────────────────────╯
def generate_final_video(image_groups,
                         audio_path: str,
                         output_path: str,
                         green_duration: int,
                         aspect_ratio: str,
                         progress_cb):
    """
    Gera vídeo final com blocos A/B/C  +  telas-verdes.
    Progresso: 0-10-20-…-90-100.
    """
    res = _resolution_from_ratio(aspect_ratio)
    tmp  = tempfile.mkdtemp()
    parts = []

    total = len(image_groups)
    logger.info("🎬 %d blocos – resolução %s", total, res)

    for idx, (pref, imgs) in enumerate(sorted(image_groups.items()), 1):
        progress_cb(10 + int((idx-1)/total * 70))        # 10,20…
        out_blk = os.path.join(tmp, f"{pref}.mp4")
        _make_block(imgs, audio_path, out_blk, res)
        parts.append(out_blk)

        if idx != total:  # green entre blocos
            g = os.path.join(tmp, f"green_{idx}.mp4")
            _make_green(g, green_duration, res)
            parts.append(g)

    progress_cb(90)  # blocos prontos

    # concat final
    concat_txt = os.path.join(tmp, "list.txt")
    with open(concat_txt, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")

    _run([
        "ffmpeg", "-y", "-safe", "0", "-f", "concat", "-i", concat_txt,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path
    ])

    progress_cb(100)
    logger.info("🎉 Vídeo final → %s", output_path)
    shutil.rmtree(tmp, ignore_errors=True)
# ─────────────────────────────────────────────────────────────────────────────
