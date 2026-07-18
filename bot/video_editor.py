import os
import subprocess
import tempfile
import logging

from bot.config import (
    CLIP_MAX_DURATION,
    CLIP_MIN_DURATION,
    BACKGROUND_MUSIC_VOLUME,
    TEXT_OVERLAY,
    MUSIC_DIR,
)

logger = logging.getLogger(__name__)


def get_music_path() -> str:
    if os.path.exists(MUSIC_DIR):
        for f in os.listdir(MUSIC_DIR):
            if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
                return os.path.join(MUSIC_DIR, f)
    return ""


def run_ffmpeg(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=300
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr[:500]}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timed out")
        return False
    except FileNotFoundError:
        logger.error("FFmpeg not found")
        return False


def cut_clips(video_path: str, segments: list[dict], output_dir: str) -> list[str]:
    clip_paths = []
    for i, seg in enumerate(segments):
        start = seg["start"]
        duration = min(seg["end"] - seg["start"], CLIP_MAX_DURATION)
        if duration < CLIP_MIN_DURATION:
            continue

        clip_path = os.path.join(output_dir, f"clip_{i:03d}.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            clip_path,
        ]
        if run_ffmpeg(cmd) and os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
            clip_paths.append(clip_path)
    return clip_paths


def concatenate_clips(clip_paths: list[str], output_path: str) -> str:
    if not clip_paths:
        return ""

    if len(clip_paths) == 1:
        cmd = [
            "ffmpeg", "-y", "-i", clip_paths[0],
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output_path,
        ]
        if run_ffmpeg(cmd):
            return output_path
        return clip_paths[0]

    concat_file = tempfile.mktemp(suffix=".txt", dir=os.path.dirname(output_path))
    with open(concat_file, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    run_ffmpeg(cmd)
    if os.path.exists(concat_file):
        os.remove(concat_file)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return output_path
    return clip_paths[0]


def add_text_overlay(video_path: str, text: str, output_path: str) -> str:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    linux_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    ]
    for f in linux_fonts:
        if os.path.exists(f):
            font_path = f
            break

    win_fonts = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for f in win_fonts:
        if os.path.exists(f):
            font_path = f
            break

    escaped_text = text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")

    drawtext = (
        f"drawtext=fontfile='{font_path}'"
        f":text='{escaped_text}'"
        f":fontsize=60"
        f":fontcolor=white"
        f":x=(w-text_w)/2"
        f":y=(h-text_h)/2"
        f":borderw=3"
        f":bordercolor=black"
    )

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    if run_ffmpeg(cmd) and os.path.exists(output_path):
        return output_path
    return video_path


def add_background_music(video_path: str, music_path: str, output_path: str) -> str:
    if not music_path or not os.path.exists(music_path):
        return video_path

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        f"[0:a]volume=1.0[original];"
        f"[1:a]volume={BACKGROUND_MUSIC_VOLUME},aloop=loop=-1:size=2e+09[bg];"
        f"[original][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]
    if run_ffmpeg(cmd) and os.path.exists(output_path):
        return output_path
    return video_path


def edit_video(
    video_path: str,
    segments: list[dict],
    text_overlay: str = TEXT_OVERLAY,
    output_path: str | None = None,
) -> dict:
    temp_dir = tempfile.mkdtemp()

    result = {
        "original": video_path,
        "clips": [],
        "final": None,
        "text": text_overlay,
        "segments_used": len(segments),
    }

    try:
        clip_paths = cut_clips(video_path, segments, temp_dir)
        if not clip_paths:
            logger.error("No clips were created")
            return result

        result["clips"] = clip_paths

        if not output_path:
            base = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(temp_dir, f"{base}_edited.mp4")

        concatenated = os.path.join(temp_dir, "concatenated.mp4")
        concat_result = concatenate_clips(clip_paths, concatenated)

        if not concat_result or not os.path.exists(concat_result):
            logger.error("Concatenation failed")
            return result

        with_text = os.path.join(temp_dir, "with_text.mp4")
        text_result = add_text_overlay(concat_result, text_overlay, with_text)

        music_path = get_music_path()
        final_path = output_path
        final_result = add_background_music(text_result, music_path, final_path)

        if final_result and os.path.exists(final_result):
            result["final"] = final_result
        elif text_result and os.path.exists(text_result):
            import shutil
            shutil.copy2(text_result, output_path)
            result["final"] = output_path
        elif os.path.exists(concat_result):
            import shutil
            shutil.copy2(concat_result, output_path)
            result["final"] = output_path

    except Exception as e:
        logger.error(f"Error editing video: {e}")
        raise

    return result
