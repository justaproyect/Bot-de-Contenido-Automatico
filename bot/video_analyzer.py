import os
import subprocess
import json
import tempfile
import logging

logger = logging.getLogger(__name__)

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from bot.config import (
    GEMINI_API_KEY,
    ENERGY_THRESHOLD_PERCENTILE,
    NUM_CLIPS,
    CLIP_MIN_DURATION,
    CLIP_MAX_DURATION,
)


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 30.0


def extract_audio(video_path: str) -> str:
    audio_path = tempfile.mktemp(suffix=".wav", dir=os.path.dirname(video_path))
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-t", "60",
        audio_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=True)
        return audio_path
    except Exception as e:
        logger.error(f"Error extracting audio: {e}")
        return ""


def analyze_audio_energy(video_path: str) -> list[dict]:
    duration = get_video_duration(video_path)
    audio_path = extract_audio(video_path)

    if not audio_path or not os.path.exists(audio_path):
        return fallback_segments(duration)

    try:
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=16000, duration=60)
            hop_length = 1024
            rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
            times = librosa.frames_to_time(
                np.arange(len(rms)), sr=sr, hop_length=hop_length
            )
            threshold = np.percentile(rms, ENERGY_THRESHOLD_PERCENTILE)
            segments = extract_segments(rms, times, threshold, duration)
            return segments
        except ImportError:
            return analyze_with_ffmpeg(audio_path, duration)
    finally:
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass


def extract_segments(rms, times, threshold, duration) -> list[dict]:
    high_energy_mask = rms >= threshold
    segments = []
    in_segment = False
    start = 0

    for i, is_high in enumerate(high_energy_mask):
        if is_high and not in_segment:
            start = times[i]
            in_segment = True
        elif not is_high and in_segment:
            end = times[i]
            if end - start >= CLIP_MIN_DURATION:
                energy = float(np.mean(rms[(times >= start) & (times <= end)]))
                segments.append({
                    "start": float(start),
                    "end": min(float(end), duration),
                    "energy": energy,
                })
            in_segment = False

    if in_segment:
        end = times[-1]
        if end - start >= CLIP_MIN_DURATION:
            energy = float(np.mean(rms[(times >= start) & (times <= end)]))
            segments.append({
                "start": float(start),
                "end": min(float(end), duration),
                "energy": energy,
            })

    segments.sort(key=lambda s: s["energy"], reverse=True)
    segments = segments[:NUM_CLIPS]

    if not segments:
        return fallback_segments(duration)

    return segments


def analyze_with_ffmpeg(audio_path: str, duration: float) -> list[dict]:
    cmd = [
        "ffprobe", "-f", "lavfi",
        "-i", f"amovie={audio_path}:astats=metadata=1:reset=1",
        "-show_entries", "frame_tags=lavfi.astats.Overall.RMS_level",
        "-of", "json",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout)

        rms_values = []
        for frame in data.get("frames", []):
            tags = frame.get("tags", {})
            level = tags.get("lavfi.astats.Overall.RMS_level", "-inf")
            if level != "-inf":
                rms_values.append(float(level))

        if not rms_values:
            return fallback_segments(duration)

        frame_duration = duration / max(len(rms_values), 1)
        threshold = np.percentile(rms_values, ENERGY_THRESHOLD_PERCENTILE) if NUMPY_AVAILABLE else sorted(rms_values)[len(rms_values) // 4]

        segments = []
        for i, rms in enumerate(rms_values):
            if rms >= threshold:
                start = i * frame_duration
                end = min((i + 1) * frame_duration, duration)
                if end - start >= CLIP_MIN_DURATION:
                    segments.append({
                        "start": start,
                        "end": end,
                        "energy": rms,
                    })

        segments.sort(key=lambda s: s["energy"], reverse=True)
        return segments[:NUM_CLIPS] if segments else fallback_segments(duration)

    except Exception as e:
        logger.error(f"FFmpeg analysis failed: {e}")
        return fallback_segments(duration)


def fallback_segments(duration: float) -> list[dict]:
    chunk = duration / (NUM_CLIPS + 1)
    return [
        {"start": (i + 1) * chunk, "end": (i + 1) * chunk + min(5, chunk), "energy": 0.5}
        for i in range(NUM_CLIPS)
        if (i + 1) * chunk < duration
    ]


def analyze_video_content(video_path: str) -> dict:
    if not GEMINI_AVAILABLE or not GEMINI_API_KEY:
        return {
            "description": "Video para contenido",
            "hashtags": ["viral", "trending", "fyp", "content", "reels"],
            "suggested_text": "POV",
            "mood": "energetic",
        }

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    duration = get_video_duration(video_path)
    num_frames = 3
    frames_dir = tempfile.mkdtemp()
    frame_paths = []

    for i in range(num_frames):
        timestamp = (duration / (num_frames + 1)) * (i + 1)
        frame_path = os.path.join(frames_dir, f"frame_{i}.jpg")
        cmd = [
            "ffmpeg", "-y", "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1", "-q:v", "5",
            "-vf", "scale=640:-1",
            frame_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
            if os.path.exists(frame_path):
                frame_paths.append(frame_path)
        except Exception:
            continue

    if not frame_paths:
        return {
            "description": "Video para contenido",
            "hashtags": ["viral", "trending", "fyp", "content", "reels"],
            "suggested_text": "POV",
            "mood": "energetic",
        }

    try:
        import PIL.Image
        images = [PIL.Image.open(fp) for fp in frame_paths if os.path.exists(fp)]

        prompt = """Analiza estas frames de un video. Responde en JSON:
{
    "description": "descripcion del video en 1 linea",
    "mood": "energetic/calm/funny/dramatic",
    "suggested_text": "texto POV corto para Instagram Reels",
    "hashtags": ["15 hashtags relevantes en español e inglés"]
}"""

        response = model.generate_content([prompt] + images)
        text = response.text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return {
            "description": "Video para contenido",
            "hashtags": ["viral", "trending", "fyp", "content", "reels"],
            "suggested_text": "POV",
            "mood": "energetic",
        }
    finally:
        for fp in frame_paths:
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
        try:
            os.rmdir(frames_dir)
        except Exception:
            pass
