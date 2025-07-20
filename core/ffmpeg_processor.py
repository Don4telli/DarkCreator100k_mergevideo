# ─────────────────────────────────────────────────────────────────────────────
#  ffmpeg_processor.py  –  release “sem-surpresa”
# ─────────────────────────────────────────────────────────────────────────────
import os, re, json, logging, shutil, tempfile, subprocess, shlex
from collections import defaultdict
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ╭──────────────────────────────────────────────────────────────────────────╮
# │ 1. Funções utilitárias                                                  │
# ╰──────────────────────────────────────────────────────────────────────────╯
def _run(cmd: list[str]) -> None:
    """Executa subprocess, loga stderr se falhar."""
    logger.info("🖥️  %s", shlex.join(cmd))
    try:
        subprocess.run(cmd, check=True, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        logger.error("❌ FFmpeg erro:\n%s", e.stdout)
        raise

def _audio_duration(path: str) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_entries", "format=duration", path],
        text=True
    )
    return float(json.loads(out)["format"]["duration"])

def _resolution(ratio: str) -> Tuple[int, int]:
    return (1080, 1920) if ratio == "9:16" else (1920, 1080)

def group_images_by_prefix(imgs: List[str]):
    g = defaultdict(list)
    for p in imgs:
        m = re.match(r'^([A-Za-z]+)', os.path.basename(p))
        key = m.group(1).upper() if m else "DEFAULT"
        g[key].append(p)
    for lst in g.values():
        lst.sort(key=lambda x: int(re.findall(r'\d+', os.path.basename(x))[0]))
    logger.info("✅ Prefixos: %s", list(g))
    return g

# ╭──────────────────────────────────────────────────────────────────────────╮
# │ 2. Bloco A/B/C                                                         │
# ╰──────────────────────────────────────────────────────────────────────────╯
def _make_block(images: List[str], audio: str, out_mp4: str,
                res: Tuple[int, int], fps: int = 25) -> None:
    """Renderiza um bloco (imagens + áudio integral) na resolução `res`."""
    if not images:
        raise ValueError("Lista de imagens vazia")

    dur_a = _audio_duration(audio)
    dur_f = dur_a / len(images)
    w, h  = res
    logger.info("🖼️  %d imgs | %.2fs áudio → %.3fs/frame",
                len(images), dur_a, dur_f)

    # arquivo-lista para o concat
    concat_txt = tempfile.NamedTemporaryFile(delete=False, suffix=".txt").name
    with open(concat_txt, "w") as f:
        for img in images[:-1]:
            f.write(f"file '{img}'\n")
            f.write(f"duration {dur_f}\n")
        f.write(f"file '{images[-1]}'\n")

    # 1. vídeo silencioso escalado/pad
    vid_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
    _run([
        "ffmpeg", "-y",
        "-protocol_whitelist", "file,pipe",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-vsync", "vfr", "-r", str(fps),
        "-vf", (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"   # ← fix
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "veryfast",
        vid_tmp
    ])

    # 2. muxa áudio integral
    _run([
        "ffmpeg", "-y",
        "-i", vid_tmp, "-i", audio,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-map", "0:v:0", "-map", "1:a:0",
        out_mp4
    ])

    os.remove(concat_txt)
    os.remove(vid_tmp)
    logger.info("✅ Bloco pronto → %s", out_mp4)


# ╭──────────────────────────────────────────────────────────────────────────╮
# │ 3. Tela verde                                                          │
# ╰──────────────────────────────────────────────────────────────────────────╯
def _green(path: str, dur: int, res: Tuple[int, int]) -> None:
    w, h = res
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=00ff00:s={w}x{h}:d={dur}",
        "-f", "lavfi", "-i", "anullsrc=sample_rate=48000:cl=stereo",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-t", str(dur),
        path
    ])
    logger.info("🟩 Tela verde %ss", dur)

# ╭──────────────────────────────────────────────────────────────────────────╮
# │ 4. Pipeline final                                                      │
# ╰──────────────────────────────────────────────────────────────────────────╯
def generate_final_video(image_groups,
                         audio_path: str,
                         output_path: str,
                         green_sec: int,
                         aspect_ratio: str,
                         progress_cb):
    res  = _resolution(aspect_ratio)
    tmpd = tempfile.mkdtemp()
    parts = []

    total = len(image_groups)
    logger.info("🎬 %d blocos – resolução %s", total, res)

    for i, (pref, imgs) in enumerate(sorted(image_groups.items()), 1):
        progress_cb(10 + int((i-1)/total * 70))
        blk = os.path.join(tmpd, f"{pref}.mp4")
        _make_block(imgs, audio_path, blk, res)
        parts.append(blk)
        # dentro de generate_final_video, logo após criar part_path …
        if i != total:
            green = os.path.join(tmpd, f"green_{i}.mp4")
            _green(green, green_sec, res)     # ← ordem correta
            parts.append(green)


    progress_cb(90)

    concat = os.path.join(tmpd, "all.txt")
    with open(concat, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")

    _run([
        "ffmpeg", "-y", "-protocol_whitelist", "file,pipe",
        "-f", "concat", "-safe", "0", "-i", concat,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", output_path
    ])

    progress_cb(100)
    logger.info("🎉 Final → %s", output_path)
    shutil.rmtree(tmpd, ignore_errors=True)
# ─────────────────────────────────────────────────────────────────────────────
