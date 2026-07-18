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
    return os.path.join(MUSIC_DIR, files[0]) if files else ""


def run_ffmpeg(cmd: list[str], timeout: int = 90) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"FFmpeg: {result.stderr[:300]}")
            return False
        return True
    except Exception as e:
        logger.error(f"FFmpeg: {e}")
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
            return [{"time": float(beat_times[i]), "duration": float(intervals[i])} for i in range(len(beat_times) - 1)]
        return [{"time": float(t), "duration": 0.5} for t in beat_times]
    except Exception as e:
        logger.error(f"Beat error: {e}")
        return []


def get_font_path() -> str:
    for f in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/impact.ttf",
    ]:
        if os.path.exists(f):
            return f
    return ""


def build_text_filter(text: str, font_path: str, estilo: str = "impactante", posicion: str = "centro", fontsize: int = 48) -> str:
    if not text or not font_path:
        return ""

    escaped = text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")

    pos_map = {
        "centro": "(w-text_w)/2:(h-text_h)/2",
        "arriba": "(w-text_w)/2:h*0.08",
        "abajo": "(w-text_w)/2:h*0.85",
    }
    xy = pos_map.get(posicion, pos_map["centro"])

    color_map = {
        "impactante": "white",
        "emocional": "#FFD700",
        "curioso": "#00FFFF",
        "divertido": "#FF69B4",
        "urgente": "#FF4444",
    }
    color = color_map.get(estilo, "white")

    size_map = {
        "impactante": 56,
        "emocional": 44,
        "curioso": 48,
        "divertido": 50,
        "urgente": 54,
    }
    final_size = size_map.get(estilo, fontsize)

    return (
        f"drawtext=fontfile='{font_path}'"
        f":text='{escaped}'"
        f":fontsize={final_size}"
        f":fontcolor={color}"
        f":x={xy.split(':')[0]}"
        f":y={xy.split(':')[1]}"
        f":borderw=3"
        f":bordercolor=black"
        f":shadowcolor=black@0.6"
        f":shadowx=3"
        f":shadowy=3"
    )


def build_dual_text_filter(text1: str, text2: str, font_path: str, estilo: str, posicion: str) -> str:
    if not font_path:
        return ""

    filter_parts = []

    if text1:
        e1 = text1.replace("'", "\\'").replace(":", "\\:")
        pos1 = "centro" if posicion == "centro" else "arriba"
        y1 = "(h-text_h)/2-40" if pos1 == "centro" else "h*0.08"

        color_map = {"impactante": "white", "emocional": "#FFD700", "curioso": "#00FFFF", "divertido": "#FF69B4", "urgente": "#FF4444"}
        color1 = color_map.get(estilo, "white")

        filter_parts.append(
            f"drawtext=fontfile='{font_path}'"
            f":text='{e1}'"
            f":fontsize=52"
            f":fontcolor={color1}"
            f":x=(w-text_w)/2:y={y1}"
            f":borderw=3:bordercolor=black"
        )

    if text2:
        e2 = text2.replace("'", "\\'").replace(":", "\\:")
        y2 = "(h-text_h)/2+40" if posicion == "centro" else "h*0.85"

        filter_parts.append(
            f"drawtext=fontfile='{font_path}'"
            f":text='{e2}'"
            f":fontsize=38"
            f":fontcolor=white@0.9"
            f":x=(w-text_w)/2:y={y2}"
            f":borderw=2:bordercolor=black@0.8"
        )

    return ",".join(filter_parts)


def create_clip(
    video_path: str,
    start: float,
    duration: float,
    output_path: str,
    zoom_type: str = "in",
    text_filter: str = "",
) -> bool:

    total_frames = int(duration * 30)

    zoom_map = {
        "in": f"zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=720x1280:fps=30",
        "out": f"zoompan=z='if(eq(on,1),1.3,max(zoom-0.0015,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=720x1280:fps=30",
        "pan": f"zoompan=z='1.08':x='iw/2-(iw/zoom/2)+sin(on/15)*25':y='ih/2-(ih/zoom/2)+cos(on/12)*20':d={total_frames}:s=720x1280:fps=30",
        "shake": f"zoompan=z='1.05':x='iw/2-(iw/zoom/2)+sin(on/8)*30':y='ih/2-(ih/zoom/2)+cos(on/6)*25':d={total_frames}:s=720x1280:fps=30",
        "slide": f"zoompan=z='1.0':x='if(eq(on,1),0,min(x+3,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={total_frames}:s=720x1280:fps=30",
    }

    zoom = zoom_map.get(zoom_type, zoom_map["in"])

    if text_filter:
        vf = f"{zoom},{text_filter}"
    else:
        vf = zoom

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


def merge_clips(clip_paths: list[str], music_path: str, output_path: str) -> bool:
    if not clip_paths:
        return False

    concat_file = tempfile.mktemp(suffix=".txt")
    with open(concat_file, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    temp_concat = tempfile.mktemp(suffix=".mp4")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", temp_concat]
    run_ffmpeg(cmd, timeout=60)

    if not os.path.exists(temp_concat):
        return False

    if music_path and os.path.exists(music_path):
        concat_dur = get_duration(temp_concat)
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_concat,
            "-i", music_path,
            "-filter_complex",
            f"[0:a]volume=2.0[orig];"
            f"[1:a]volume=0.2,aloop=loop=-1:size=2e+09,atrim=0:{concat_dur}[bg];"
            f"[orig][bg]amix=inputs=2:duration=first:dropout_transition=2[mixed];"
            f"[mixed]loudnorm=I=-16:TP=-1.5:LRA=11[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            output_path,
        ]
        success = run_ffmpeg(cmd, timeout=90)
    else:
        cmd = ["ffmpeg", "-y", "-i", temp_concat, "-c", "copy", "-movflags", "+faststart", output_path]
        success = run_ffmpeg(cmd, timeout=60)

    for f in [concat_file, temp_concat]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass

    return success and os.path.exists(output_path)


def edit_video(video_path: str, clips: list[dict], analysis: dict, output_path: str | None = None) -> dict:
    temp_dir = tempfile.mkdtemp()
    result = {"original": video_path, "final": None}

    try:
        font_path = get_font_path()
        music_path = get_music_path()
        beats = detect_music_beats(music_path) if music_path else []
        video_duration = get_duration(video_path)

        if not output_path:
            base = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(temp_dir, f"{base}_final.mp4")

        texto1 = analysis.get("texto_principal", "POV")
        texto2 = analysis.get("texto_secundario", "")
        estilo = analysis.get("estilo_texto", "impactante")
        posicion = analysis.get("posicion_texto", "centro")

        text_filter = build_dual_text_filter(texto1, texto2, font_path, estilo, posicion)

        clip_paths = []
        zoom_types = ["in", "out", "pan", "shake", "slide"]

        if beats and len(beats) >= 3:
            num_clips = min(len(beats), 6)
            step = max(1, len(beats) // num_clips)
            for i in range(num_clips):
                idx = i * step
                if idx >= len(beats):
                    break
                start = beats[idx]["time"]
                dur = max(1.5, min(beats[idx]["duration"] * 2, 4.0))
                if start + dur > video_duration:
                    dur = video_duration - start
                if dur < 1.0:
                    continue

                clip_path = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
                zoom = zoom_types[i % len(zoom_types)]
                tf = text_filter if i == 0 else ""
                if create_clip(video_path, start, dur, clip_path, zoom, tf):
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
                tf = text_filter if i == 0 else ""
                if create_clip(video_path, start, dur, clip_path, zoom, tf):
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                        clip_paths.append(clip_path)

        if not clip_paths:
            clip_path = os.path.join(temp_dir, "default.mp4")
            if create_clip(video_path, 0, min(8, video_duration), clip_path, "in", text_filter):
                if os.path.exists(clip_path):
                    clip_paths.append(clip_path)

        if clip_paths and merge_clips(clip_paths, music_path, output_path):
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
        "-movflags", "+faststart", output_path,
    ]
    if run_ffmpeg(cmd, timeout=60) and os.path.exists(output_path):
        return output_path
    return video_path
