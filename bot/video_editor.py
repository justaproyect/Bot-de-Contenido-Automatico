import os
import subprocess
import tempfile
import random

from bot.config import (
    CLIP_MAX_DURATION,
    CLIP_MIN_DURATION,
    BACKGROUND_MUSIC_VOLUME,
    TEXT_OVERLAY,
    FONTS_DIR,
    MUSIC_DIR,
)


def get_font_path() -> str:
    font_candidates = [
        os.path.join(FONTS_DIR, "Impact.ttf"),
        os.path.join(FONTS_DIR, "arial.ttf"),
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for font in font_candidates:
        if os.path.exists(font):
            return font
    return "C:/Windows/Fonts/arial.ttf"


def get_music_path() -> str:
    if os.path.exists(MUSIC_DIR):
        for f in os.listdir(MUSIC_DIR):
            if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
                return os.path.join(MUSIC_DIR, f)
    return ""


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
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            clip_path,
        ]
        result = subprocess.run(cmd, capture_output=True, check=True)
        if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
            clip_paths.append(clip_path)
    return clip_paths


def concatenate_clips(clip_paths: list[str], output_path: str) -> str:
    if len(clip_paths) == 1:
        cmd = [
            "ffmpeg", "-y", "-i", clip_paths[0],
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    concat_file = tempfile.mktemp(suffix=".txt", dir=os.path.dirname(output_path))
    with open(concat_file, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    if os.path.exists(concat_file):
        os.remove(concat_file)
    return output_path


def add_text_overlay(
    video_path: str,
    text: str,
    output_path: str,
    font_size: int = 72,
    color: str = "white",
    position: str = "center",
) -> str:
    font_path = get_font_path().replace("\\", "/").replace(":", "\\:")

    if position == "top":
        y_pos = "h*0.1"
    elif position == "bottom":
        y_pos = "h*0.85"
    else:
        y_pos = "(h-text_h)/2"

    escaped_text = text.replace("'", "'\\''").replace(":", "\\:")

    drawtext = (
        f"drawtext=fontfile='{font_path}'"
        f":text='{escaped_text}'"
        f":fontsize={font_size}"
        f":fontcolor={color}"
        f":x=(w-text_w)/2"
        f":y={y_pos}"
        f":borderw=3"
        f":bordercolor=black"
        f":shadowcolor=black@0.5"
        f":shadowx=2"
        f":shadowy=2"
    )

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def add_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    volume: float = BACKGROUND_MUSIC_VOLUME,
) -> str:
    if not music_path or not os.path.exists(music_path):
        return video_path

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        f"[0:a]volume=1.0[original];"
        f"[1:a]volume={volume},aloop=loop=-1:size=2e+09[bg];"
        f"[original][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def edit_video(
    video_path: str,
    segments: list[dict],
    text_overlay: str = TEXT_OVERLAY,
    output_path: str | None = None,
) -> dict:
    temp_dir = tempfile.mkdtemp()
    out_dir = os.path.dirname(output_path) if output_path else os.path.dirname(video_path)

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
            return result

        result["clips"] = clip_paths

        if not output_path:
            base = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(
                output_dir, f"{base}_edited.mp4"
            )

        concatenated = os.path.join(temp_dir, "concatenated.mp4")
        concatenate_clips(clip_paths, concatenated)

        with_text = os.path.join(temp_dir, "with_text.mp4")
        add_text_overlay(concatenated, text_overlay, with_text)

        music_path = get_music_path()
        final_path = output_path
        add_background_music(with_text, music_path, final_path)

        result["final"] = final_path

    except Exception as e:
        print(f"Error editing video: {e}")
        raise

    return result
