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
from bot.music_downloader import get_music_path as get_music_file


def get_music_path() -> str:
    if not os.path.exists(MUSIC_DIR):
        return ""
    files = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg"))]
    return os.path.join(MUSIC_DIR, files[0]) if files else ""


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


def detect_beats(music_path: str) -> list[dict]:
    if not LIBROSA_AVAILABLE or not os.path.exists(music_path):
        return []
    try:
        y, sr = librosa.load(music_path, sr=22050, duration=30)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        if NUMPY_AVAILABLE and len(beat_times) > 1:
            intervals = np.diff(beat_times)
            return [{"time": float(beat_times[i]), "dur": float(intervals[i])} for i in range(len(beat_times) - 1)]
        return [{"time": float(t), "dur": 0.5} for t in beat_times]
    except Exception as e:
        logger.error(f"Beat error: {e}")
        return []


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


def make_clip(video_path: str, start: float, dur: float, output: str, effect: str, text_f: str = "") -> bool:
    effects = {
        "zoom_in": f"scale=840:1500,crop=720:1280:60:110",
        "zoom_out": f"scale=600:1067,crop=720:1280:-60:-106",
        "pan_left": f"scale=900:1600,crop=720:1280:180:160",
        "pan_right": f"scale=900:1600,crop=720:1280:0:160",
        "shake": f"scale=780:1387,crop=720:1280:30:53",
        "slide": f"scale=800:1422,crop=720:1280:40:71",
    }

    vf = effects.get(effect, effects["zoom_in"])
    if text_f:
        vf = f"{vf},{text_f}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(dur),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-an",
        "-movflags", "+faststart",
        output,
    ]
    return run_ffmpeg(cmd, timeout=45)


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


def concat_clips(clips: list[str], output: str) -> bool:
    if not clips:
        return False

    if len(clips) == 1:
        import shutil
        shutil.copy2(clips[0], output)
        return os.path.exists(output)

    concat_file = tempfile.mktemp(suffix=".txt")
    with open(concat_file, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")

    ok = run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        "-movflags", "+faststart",
        output,
    ], timeout=60)

    if os.path.exists(concat_file):
        try: os.remove(concat_file)
        except: pass

    return ok and os.path.exists(output) and os.path.getsize(output) > 0


def add_music(video_path: str, music_path: str, output: str) -> bool:
    if not music_path or not os.path.exists(music_path):
        import shutil
        shutil.copy2(video_path, output)
        return True

    dur = get_duration(video_path)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        f"[1:a]volume=0.25,aloop=loop=-1:size=2e+09,atrim=0:{dur},afade=t=in:st=0:d=1,afade=t=out:st={dur-1}:d=1[bg];"
        f"[0:a]volume=1.8[orig];"
        f"[orig][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        output,
    ]
    return run_ffmpeg(cmd, timeout=60)


def edit_video(video_path: str, clips: list[dict], analysis: dict, output_path: str | None = None) -> dict:
    temp_dir = tempfile.mkdtemp()
    result = {"original": video_path, "final": None}

    try:
        font = get_font()
        mood = analysis.get("mood", "energetic")
        music = get_music_file(mood)
        beats = detect_beats(music) if music else []
        vid_dur = get_duration(video_path)

        texto1 = analysis.get("texto_principal", "POKEMON")
        texto2 = analysis.get("texto_secundario", "")
        estilo = analysis.get("estilo_texto", "impactante")
        color_map = {"impactante": "white", "emocional": "#FFD700", "curioso": "#00FFFF", "divertido": "#FF69B4", "urgente": "#FF4444"}
        color = color_map.get(estilo, "white")
        text_f = make_text_filter(texto1, font, color)

        if not output_path:
            base = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(temp_dir, f"{base}_final.mp4")

        effects = ["zoom_in", "zoom_out", "pan_left", "pan_right", "shake", "slide"]
        clip_paths = []

        if beats and len(beats) >= 4:
            usable = [b for b in beats if b["time"] + 1.5 < vid_dur]
            step = max(1, len(usable) // 6)
            selected = usable[::step][:6]

            for i, beat in enumerate(selected):
                start = beat["time"]
                dur = min(max(beat["dur"] * 2, 1.5), 3.5)
                if start + dur > vid_dur:
                    dur = vid_dur - start
                if dur < 1.0:
                    continue

                clip_path = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
                effect = effects[i % len(effects)]
                tf = text_f if i == 0 else ""

                if make_clip(video_path, start, dur, clip_path, effect, tf):
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                        clip_paths.append(clip_path)
                        logger.info(f"Clip {i}: {effect} at {start:.1f}s OK")

        if not clip_paths:
            logger.info("No beat clips, making default clips")
            positions = [0, vid_dur * 0.25, vid_dur * 0.5, vid_dur * 0.75]
            for i, pos in enumerate(positions[:4]):
                if pos + 2 > vid_dur:
                    continue
                clip_path = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
                effect = effects[i % len(effects)]
                tf = text_f if i == 0 else ""
                if make_clip(video_path, pos, 2.5, clip_path, effect, tf):
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                        clip_paths.append(clip_path)

        if not clip_paths:
            clip_path = os.path.join(temp_dir, "single.mp4")
            if make_clip(video_path, 0, min(6, vid_dur), clip_path, "zoom_in", text_f):
                if os.path.exists(clip_path):
                    clip_paths.append(clip_path)

        logger.info(f"Total clips created: {len(clip_paths)}")

        concat_path = os.path.join(temp_dir, "concat.mp4")
        if concat_clips(clip_paths, concat_path):
            logger.info("Concat OK, adding music")
            if music:
                if add_music(concat_path, music, output_path):
                    result["final"] = output_path
                    logger.info("Final video with music OK")
            else:
                import shutil
                shutil.copy2(concat_path, output_path)
                result["final"] = output_path
        else:
            logger.error("Concat failed")
            if clip_paths:
                import shutil
                shutil.copy2(clip_paths[0], output_path)
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
    if os.path.getsize(video_path) / (1024 * 1024) <= max_size_mb:
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
