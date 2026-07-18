import os
import subprocess
import tempfile
import logging

logger = logging.getLogger(__name__)

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

from bot.config import MUSIC_DIR


def get_music_path() -> str:
    if not os.path.exists(MUSIC_DIR):
        return ""
    files = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg"))]
    if files:
        return os.path.join(MUSIC_DIR, files[0])
    return ""


def run_ffmpeg(cmd: list[str], timeout: int = 90) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"FFmpeg: {result.stderr[:300]}")
            return False
        return True
    except Exception as e:
        logger.error(f"FFmpeg exception: {e}")
        return False


def get_duration(path: str) -> float:
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(__import__("json").loads(r.stdout)["format"]["duration"])
    except Exception:
        return 10.0


def detect_music_beats(music_path: str) -> list[dict]:
    if not LIBROSA_AVAILABLE or not os.path.exists(music_path):
        return []

    try:
        y, sr = librosa.load(music_path, sr=22050, duration=60)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        if NUMPY_AVAILABLE and len(beat_times) > 1:
            intervals = np.diff(beat_times)
            beats = []
            for i in range(len(beat_times) - 1):
                beats.append({
                    "time": float(beat_times[i]),
                    "duration": float(intervals[i]),
                })
            return beats

        return [{"time": float(t), "duration": 0.5} for t in beat_times]
    except Exception as e:
        logger.error(f"Beat detection error: {e}")
        return []


def create_clip_with_zoom(
    video_path: str,
    start: float,
    duration: float,
    output_path: str,
    zoom_type: str = "in",
    text: str = "",
    font_path: str = "",
) -> bool:

    total_frames = int(duration * 30)

    if zoom_type == "in":
        zoom_filter = (
            f"zoompan=z='min(zoom+0.0015,1.3)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={total_frames}:s=720x1280:fps=30"
        )
    elif zoom_type == "out":
        zoom_filter = (
            f"zoompan=z='if(eq(on,1),1.3,max(zoom-0.0015,1.0))'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={total_frames}:s=720x1280:fps=30"
        )
    else:
        zoom_filter = (
            f"zoompan=z='1.05'"
            f":x='iw/2-(iw/zoom/2)+sin(on/15)*20'"
            f":y='ih/2-(ih/zoom/2)+cos(on/12)*15'"
            f":d={total_frames}:s=720x1280:fps=30"
        )

    if text and font_path:
        escaped = text.replace("'", "\\'").replace(":", "\\:")
        vf = (
            f"{zoom_filter},"
            f"drawtext=fontfile='{font_path}'"
            f":text='{escaped}'"
            f":fontsize=42"
            f":fontcolor=white"
            f":x=(w-text_w)/2"
            f":y=h*0.85"
            f":borderw=2"
            f":bordercolor=black"
        )
    else:
        vf = zoom_filter

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        output_path,
    ]
    return run_ffmpeg(cmd, timeout=90)


def merge_clips_with_music(
    clip_paths: list[str],
    music_path: str,
    output_path: str,
    music_volume: float = 0.25,
) -> bool:

    concat_file = tempfile.mktemp(suffix=".txt")
    with open(concat_file, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    temp_concat = tempfile.mktemp(suffix=".mp4")
    cmd_concat = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        temp_concat,
    ]
    run_ffmpeg(cmd_concat, timeout=60)

    if not os.path.exists(temp_concat):
        return False

    if music_path and os.path.exists(music_path):
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_concat,
            "-i", music_path,
            "-filter_complex",
            f"[0:a]volume=1.5[orig];"
            f"[1:a]volume={music_volume},aloop=loop=-1:size=2e+09,atrim=0:{get_duration(temp_concat)}[bg];"
            f"[orig][bg]amix=inputs=2:duration=first:dropout_transition=2[mixed];"
            f"[mixed]loudnorm=I=-16:TP=-1.5:LRA=11[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
        success = run_ffmpeg(cmd, timeout=90)
    else:
        cmd = [
            "ffmpeg", "-y", "-i", temp_concat,
            "-c:v", "copy", "-c:a", "aac",
            "-movflags", "+faststart",
            output_path,
        ]
        success = run_ffmpeg(cmd, timeout=60)

    for f in [concat_file, temp_concat]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass

    return success and os.path.exists(output_path)


def edit_video(
    video_path: str,
    clips: list[dict],
    text_overlay: str = "POV",
    output_path: str | None = None,
) -> dict:

    temp_dir = tempfile.mkdtemp()
    result = {"original": video_path, "final": None, "text": text_overlay}

    try:
        font_path = ""
        for f in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/impact.ttf",
        ]:
            if os.path.exists(f):
                font_path = f
                break

        music_path = get_music_path()
        beats = detect_music_beats(music_path) if music_path else []

        video_duration = get_duration(video_path)

        if not output_path:
            base = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(temp_dir, f"{base}_final.mp4")

        clip_paths = []
        zoom_types = ["in", "out", "pan"]

        if beats and len(beats) >= 3:
            num_clips = min(len(beats), 6)
            step = max(1, len(beats) // num_clips)

            for i in range(num_clips):
                beat_idx = i * step
                if beat_idx >= len(beats):
                    break

                start = beats[beat_idx]["time"]
                clip_dur = beats[beat_idx]["duration"] * 2
                clip_dur = max(1.5, min(clip_dur, 4.0))

                if start + clip_dur > video_duration:
                    clip_dur = video_duration - start
                if clip_dur < 1.0:
                    continue

                clip_path = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
                zoom = zoom_types[i % len(zoom_types)]
                text = text_overlay if i == 0 else ""

                if create_clip_with_zoom(video_path, start, clip_dur, clip_path, zoom, text, font_path):
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                        clip_paths.append(clip_path)

        if not clip_paths and clips:
            for i, clip in enumerate(clips[:4]):
                start = clip.get("start", 0)
                dur = min(clip.get("end", 8) - start, 5)
                if dur < 1.5:
                    dur = 3.0

                clip_path = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
                zoom = zoom_types[i % len(zoom_types)]
                text = text_overlay if i == 0 else ""

                if create_clip_with_zoom(video_path, start, dur, clip_path, zoom, text, font_path):
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                        clip_paths.append(clip_path)

        if not clip_paths:
            clip_path = os.path.join(temp_dir, "clip_default.mp4")
            zoom = "in"
            if create_clip_with_zoom(video_path, 0, min(8, video_duration), clip_path, zoom, text_overlay, font_path):
                if os.path.exists(clip_path):
                    clip_paths.append(clip_path)

        if not clip_paths:
            return result

        if merge_clips_with_music(clip_paths, music_path, output_path):
            result["final"] = output_path
        elif clip_paths:
            import shutil
            shutil.copy2(clip_paths[0], output_path)
            result["final"] = output_path

    except Exception as e:
        logger.error(f"Error: {e}")
        raise

    return result


def compress_for_telegram(video_path: str, output_path: str, max_size_mb: int = 45) -> str:
    if not os.path.exists(video_path):
        return video_path

    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    if size_mb <= max_size_mb:
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
