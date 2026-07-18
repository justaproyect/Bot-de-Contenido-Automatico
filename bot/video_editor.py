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


def run_ffmpeg(cmd: list[str], timeout: int = 120) -> bool:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr[:300]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timed out")
        return False
    except Exception as e:
        logger.error(f"FFmpeg exception: {e}")
        return False


def get_video_info(video_path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=width,height,codec_name",
        "-of", "json", video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        import json
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        streams = data.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_name") in ["h264", "hevc", "vp9"]), streams[0] if streams else {})
        return {
            "duration": duration,
            "width": int(video_stream.get("width", 720)),
            "height": int(video_stream.get("height", 1280)),
        }
    except Exception:
        return {"duration": 0, "width": 720, "height": 1280}


def cut_single_clip(video_path: str, start: float, duration: float, output_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "64k", "-ar", "44100",
        "-movflags", "+faststart",
        "-max_muxing_queue_size", "1024",
        output_path,
    ]
    return run_ffmpeg(cmd, timeout=60)


def concatenate_clips(clip_paths: list[str], output_path: str) -> str:
    if not clip_paths:
        return ""

    if len(clip_paths) == 1:
        if cut_single_clip(clip_paths[0], 0, CLIP_MAX_DURATION, output_path):
            return output_path
        return clip_paths[0] if os.path.exists(clip_paths[0]) else ""

    concat_file = tempfile.mktemp(suffix=".txt", dir=os.path.dirname(output_path))
    with open(concat_file, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart",
        "-max_muxing_queue_size", "1024",
        output_path,
    ]
    run_ffmpeg(cmd, timeout=90)
    if os.path.exists(concat_file):
        os.remove(concat_file)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return output_path
    return clip_paths[0] if clip_paths else ""


def add_text_overlay(video_path: str, text: str, output_path: str) -> str:
    font_path = None
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/impact.ttf",
    ]
    for f in font_candidates:
        if os.path.exists(f):
            font_path = f
            break

    if not font_path:
        return video_path

    escaped_text = text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")

    drawtext = (
        f"drawtext=fontfile='{font_path}'"
        f":text='{escaped_text}'"
        f":fontsize=48"
        f":fontcolor=white"
        f":x=(w-text_w)/2"
        f":y=(h-text_h)/2"
        f":borderw=2"
        f":bordercolor=black"
    )

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    if run_ffmpeg(cmd, timeout=60) and os.path.exists(output_path):
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
        "-c:a", "aac", "-b:a", "64k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]
    if run_ffmpeg(cmd, timeout=60) and os.path.exists(output_path):
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
        video_info = get_video_info(video_path)
        max_clips = min(len(segments), 3)
        active_segments = segments[:max_clips]

        clip_paths = []
        for i, seg in enumerate(active_segments):
            start = seg["start"]
            duration = min(seg["end"] - seg["start"], CLIP_MAX_DURATION)
            if duration < CLIP_MIN_DURATION:
                continue

            clip_path = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
            if cut_single_clip(video_path, start, duration, clip_path):
                if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                    clip_paths.append(clip_path)

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
