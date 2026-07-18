import os
import subprocess
import tempfile
import logging

from bot.config import MUSIC_DIR

logger = logging.getLogger(__name__)


def get_music_path() -> str:
    if os.path.exists(MUSIC_DIR):
        for f in os.listdir(MUSIC_DIR):
            if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
                return os.path.join(MUSIC_DIR, f)
    return ""


def run_ffmpeg(cmd: list[str], timeout: int = 60) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr[:200]}")
            return False
        return True
    except Exception as e:
        logger.error(f"FFmpeg exception: {e}")
        return False


def edit_video(
    video_path: str,
    clips: list[dict],
    text_overlay: str = "POV",
    output_path: str | None = None,
) -> dict:
    temp_dir = tempfile.mkdtemp()

    result = {
        "original": video_path,
        "final": None,
        "text": text_overlay,
    }

    try:
        if not clips:
            clips = [{"start": 0, "end": 8, "energy": 1.0}]

        clip = clips[0]
        start = clip.get("start", 0)
        end = clip.get("end", 8)
        duration = min(end - start, 15)
        if duration < 2:
            duration = min(8, end - start)

        if not output_path:
            base = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(temp_dir, f"{base}_edited.mp4")

        font_path = None
        font_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/impact.ttf",
        ]
        for f in font_candidates:
            if os.path.exists(f):
                font_path = f
                break

        escaped_text = text_overlay.replace("'", "\\'").replace(":", "\\:")

        if font_path:
            vf = (
                f"scale=720:1280:force_original_aspect_ratio=decrease,"
                f"pad=720:1280:(ow-iw)/2:(oh-ih)/2,"
                f"drawtext=fontfile='{font_path}'"
                f":text='{escaped_text}'"
                f":fontsize=48"
                f":fontcolor=white"
                f":x=(w-text_w)/2"
                f":y=(h-text_h)/2"
                f":borderw=2"
                f":bordercolor=black"
            )
        else:
            vf = "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2"

        music_path = get_music_path()

        if music_path:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", video_path,
                "-i", music_path,
                "-t", str(duration),
                "-filter_complex",
                f"[0:v]{vf}[v];"
                f"[0:a]volume=1.0[orig];"
                f"[1:a]volume=0.12,aloop=loop=-1:size=2e+09[bg];"
                f"[orig][bg]amix=inputs=2:duration=first[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+faststart",
                output_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", video_path,
                "-t", str(duration),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+faststart",
                output_path,
            ]

        if run_ffmpeg(cmd, timeout=60) and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            result["final"] = output_path
        else:
            cmd_simple = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", video_path,
                "-t", str(duration),
                "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+faststart",
                output_path,
            ]
            if run_ffmpeg(cmd_simple, timeout=60) and os.path.exists(output_path):
                result["final"] = output_path

    except Exception as e:
        logger.error(f"Error editing video: {e}")
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
        "-movflags", "+faststart",
        output_path,
    ]
    if run_ffmpeg(cmd, timeout=60) and os.path.exists(output_path):
        return output_path
    return video_path
