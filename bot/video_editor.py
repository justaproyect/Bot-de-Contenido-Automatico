import os
import subprocess
import tempfile
import logging
import shutil

logger = logging.getLogger(__name__)


def run_ffmpeg(cmd: list[str], timeout: int = 60) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"FFmpeg err: {result.stderr[:300]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timeout")
        return False
    except Exception as e:
        logger.error(f"FFmpeg: {e}")
        return False


def get_duration(path: str) -> float:
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(__import__("json").loads(r.stdout)["format"]["duration"])
    except Exception:
        return 10.0


def get_font() -> str:
    for f in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/impact.ttf",
    ]:
        if os.path.exists(f):
            return f
    return ""


def make_text_filter(text: str, font: str, color: str = "white", y_pos: str = "(h-text_h)/2") -> str:
    if not text or not font:
        return ""
    t = text.replace("'", "\\'").replace(":", "\\:")
    return f"drawtext=fontfile='{font}':text='{t}':fontsize=48:fontcolor={color}:x=(w-text_w)/2:y={y_pos}:borderw=3:bordercolor=black"


def validate_video(video_path: str) -> bool:
    if not os.path.exists(video_path):
        return False
    if os.path.getsize(video_path) < 1000:
        return False
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video_path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = __import__("json").loads(r.stdout)
        duration = float(data["format"]["duration"])
        return 1.0 < duration < 300.0
    except Exception:
        return False


def edit_video(video_path: str, clips: list[dict], analysis: dict, output_path: str | None = None) -> dict:
    temp_dir = tempfile.mkdtemp()
    result = {"original": video_path, "final": None}

    try:
        font = get_font()
        mood = analysis.get("mood", "energetic")
        vid_dur = get_duration(video_path)

        texto1 = analysis.get("texto_principal", "POKEMON")
        estilo = analysis.get("estilo_texto", "impactante")
        color_map = {"impactante": "white", "emocional": "#FFD700", "curioso": "#00FFFF", "divertido": "#FF69B4", "urgente": "#FF4444"}
        color = color_map.get(estilo, "white")
        text_f = make_text_filter(texto1, font, color)

        if not output_path:
            base = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(temp_dir, f"{base}_final.mp4")

        start = 0
        dur = min(6, vid_dur)
        if clips and len(clips) > 0:
            start = clips[0].get("start", 0)
            dur = min(clips[0].get("end", 6) - start, vid_dur - start, 6)
            if dur < 1:
                dur = min(6, vid_dur)
                start = 0

        effects = ["zoom_in", "zoom_out", "pan_left", "pan_right", "shake", "slide"]
        effect = effects[hash(str(start)) % len(effects)]

        clip_path = os.path.join(temp_dir, "clip.mp4")

        vf = {
            "zoom_in": f"scale=840:1500,crop=720:1280:60:110",
            "zoom_out": f"scale=600:1067,crop=720:1280:-60:-106",
            "pan_left": f"scale=900:1600,crop=720:1280:180:160",
            "pan_right": f"scale=900:1600,crop=720:1280:0:160",
            "shake": f"scale=780:1387,crop=720:1280:30:53",
            "slide": f"scale=800:1422,crop=720:1280:40:71",
        }.get(effect, "scale=840:1500,crop=720:1280:60:110")

        if text_f:
            vf = f"{vf},{text_f}"

        clip_ok = run_ffmpeg([
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(dur),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an",
            "-movflags", "+faststart",
            clip_path,
        ], timeout=45)

        if not clip_ok or not os.path.exists(clip_path):
            logger.error("Clip creation failed")
            return result

        from bot.music_downloader import get_music_path as get_music_file
        music = get_music_file(mood)

        if music and os.path.exists(music):
            music_dur = get_duration(music)
            if music_dur < 1:
                music = ""

        if music and os.path.exists(music):
            music_ok = run_ffmpeg([
                "ffmpeg", "-y",
                "-i", clip_path,
                "-i", music,
                "-filter_complex",
                f"[1:a]volume=0.3,atrim=0:{dur},afade=t=in:st=0:d=0.5,afade=t=out:st={max(dur-0.5,0)}:d=0.5[bg]",
                "-map", "0:v", "-map", "[bg]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-movflags", "+faststart",
                output_path,
            ], timeout=45)

            if music_ok and os.path.exists(output_path):
                result["final"] = output_path
                logger.info("Final video with music OK")
        else:
            shutil.copy2(clip_path, output_path)
            result["final"] = output_path
            logger.info("Final video without music OK")

        if not result["final"]:
            shutil.copy2(clip_path, output_path)
            result["final"] = output_path

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        raise

    return result


def compress_for_telegram(video_path: str, output_path: str, max_size_mb: int = 45) -> str:
    if not os.path.exists(video_path):
        return video_path
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if file_size_mb <= max_size_mb:
        return video_path

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
        "-vf", "scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2",
        "-c:a", "aac", "-b:a", "32k",
        "-movflags", "+faststart", output_path,
    ]
    if run_ffmpeg(cmd, timeout=60) and os.path.exists(output_path):
        return output_path
    return video_path
