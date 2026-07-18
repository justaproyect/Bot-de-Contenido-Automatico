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
        "-t", "30",
        audio_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        return audio_path
    except Exception as e:
        logger.error(f"Error extracting audio: {e}")
        return ""


def analyze_audio_energy(video_path: str) -> list[dict]:
    duration = get_video_duration(video_path)
    audio_path = extract_audio(video_path)

    if not audio_path or not os.path.exists(audio_path):
        return [{"start": 0, "end": min(duration, CLIP_MAX_DURATION), "energy": 0.5}]

    try:
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=16000, duration=30)
            hop_length = 2048
            rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
            times = librosa.frames_to_time(
                np.arange(len(rms)), sr=sr, hop_length=hop_length
            )
            threshold = np.percentile(rms, ENERGY_THRESHOLD_PERCENTILE)

            best_start = 0
            best_energy = 0
            window_size = int(CLIP_MAX_DURATION * sr / hop_length)

            for i in range(0, len(rms) - window_size, window_size // 2):
                window_energy = float(np.mean(rms[i:i + window_size]))
                if window_energy > best_energy:
                    best_energy = window_energy
                    best_start = float(times[i])

            if best_energy > 0:
                return [{"start": best_start, "end": min(best_start + CLIP_MAX_DURATION, duration), "energy": best_energy}]
            else:
                return [{"start": 0, "end": min(duration, CLIP_MAX_DURATION), "energy": 0.5}]
        except ImportError:
            return [{"start": 0, "end": min(duration, CLIP_MAX_DURATION), "energy": 0.5}]
    finally:
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass


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
    frames_dir = tempfile.mkdtemp()
    frame_path = os.path.join(frames_dir, "frame.jpg")

    try:
        timestamp = duration / 2
        cmd = [
            "ffmpeg", "-y", "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1", "-q:v", "5",
            "-vf", "scale=480:-1",
            frame_path,
        ]
        subprocess.run(cmd, capture_output=True, timeout=15, check=True)

        if not os.path.exists(frame_path):
            return {
                "description": "Video para contenido",
                "hashtags": ["viral", "trending", "fyp", "content", "reels"],
                "suggested_text": "POV",
                "mood": "energetic",
            }

        import PIL.Image
        image = PIL.Image.open(frame_path)

        prompt = """Describe this video in 1 line. Give me JSON:
{"description":"short description","mood":"energetic/calm/funny","suggested_text":"POV text","hashtags":["10 hashtags"]}"""

        response = model.generate_content([prompt, image])
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
        if os.path.exists(frame_path):
            try:
                os.remove(frame_path)
            except Exception:
                pass
        try:
            os.rmdir(frames_dir)
        except Exception:
            pass
