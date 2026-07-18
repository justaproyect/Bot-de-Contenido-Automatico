import os
import subprocess
import json
import tempfile
import numpy as np

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

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


def extract_audio(video_path: str) -> str:
    audio_path = tempfile.mktemp(suffix=".wav", dir=os.path.dirname(video_path))
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1",
        audio_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return audio_path


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def analyze_audio_energy(video_path: str) -> list[dict]:
    if not LIBROSA_AVAILABLE:
        return fallback_energy_analysis(video_path)

    audio_path = extract_audio(video_path)
    try:
        y, sr = librosa.load(audio_path, sr=22050)
        hop_length = 512
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        times = librosa.frames_to_time(
            np.arange(len(rms)), sr=sr, hop_length=hop_length
        )

        threshold = np.percentile(rms, ENERGY_THRESHOLD_PERCENTILE)
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
                    energy = float(np.mean(rms[
                        (times >= start) & (times <= end)
                    ]))
                    segments.append({
                        "start": float(start),
                        "end": float(end),
                        "energy": energy,
                    })
                in_segment = False

        if in_segment:
            end = times[-1]
            if end - start >= CLIP_MIN_DURATION:
                energy = float(np.mean(rms[(times >= start) & (times <= end)]))
                segments.append({
                    "start": float(start),
                    "end": float(end),
                    "energy": energy,
                })

        segments.sort(key=lambda s: s["energy"], reverse=True)
        return segments[:NUM_CLIPS]

    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


def fallback_energy_analysis(video_path: str) -> list[dict]:
    duration = get_video_duration(video_path)
    audio_path = extract_audio(video_path)
    try:
        cmd = [
            "ffprobe", "-f", "lavfi",
            "-i", f"amovie={audio_path}:astats=metadata=1:reset=1",
            "-show_entries", "frame_tags=lavfi.astats.Overall.RMS_level",
            "-of", "json", audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)

        rms_values = []
        for frame in data.get("frames", []):
            tags = frame.get("tags", {})
            level = tags.get("lavfi.astats.Overall.RMS_level", "-inf")
            if level != "-inf":
                rms_values.append(float(level))

        if not rms_values:
            chunk = duration / NUM_CLIPS
            return [
                {"start": i * chunk, "end": (i + 1) * chunk, "energy": 0.5}
                for i in range(NUM_CLIPS)
            ]

        frame_duration = duration / max(len(rms_values), 1)
        threshold = np.percentile(rms_values, ENERGY_THRESHOLD_PERCENTILE)

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

        if not segments:
            chunk = duration / NUM_CLIPS
            segments = [
                {"start": i * chunk, "end": (i + 1) * chunk, "energy": 0.5}
                for i in range(NUM_CLIPS)
            ]

        segments.sort(key=lambda s: s["energy"], reverse=True)
        return segments[:NUM_CLIPS]

    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


def analyze_video_content(video_path: str) -> dict:
    if not GEMINI_AVAILABLE or not GEMINI_API_KEY:
        return {
            "description": "Video user uploaded",
            "hashtags": ["viral", "trending", "fyp", "content"],
            "suggested_text": "POV",
            "mood": "energetic",
        }

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,r_frame_rate",
        "-of", "json", video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    video_info = json.loads(result.stdout)

    num_frames = 5
    duration = float(video_info["streams"][0].get("duration", 10))
    frames_dir = tempfile.mkdtemp()
    frame_paths = []

    for i in range(num_frames):
        timestamp = (duration / (num_frames + 1)) * (i + 1)
        frame_path = os.path.join(frames_dir, f"frame_{i}.jpg")
        cmd = [
            "ffmpeg", "-y", "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1", "-q:v", "2",
            frame_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        if os.path.exists(frame_path):
            frame_paths.append(frame_path)

    import PIL.Image
    images = []
    for fp in frame_paths:
        if os.path.exists(fp):
            images.append(PIL.Image.open(fp))

    prompt = """Analyze these frames from a video. Based on the visual content:
1. Describe what is happening in the video (1-2 sentences)
2. Determine the mood/energy (energetic, calm, funny, dramatic, informative)
3. Suggest a catchy POV text overlay that would work for Instagram Reels
4. Generate 15-20 relevant hashtags for Instagram in Spanish and English

Respond in JSON format:
{
    "description": "description of the video",
    "mood": "energetic/calm/funny/dramatic",
    "suggested_text": "POV text suggestion",
    "hashtags": ["hashtag1", "hashtag2", ...]
}"""

    try:
        response = model.generate_content([prompt] + images)
        text = response.text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except Exception as e:
        print(f"Error analyzing video with Gemini: {e}")
        return {
            "description": "Video user uploaded",
            "hashtags": ["viral", "trending", "fyp", "content"],
            "suggested_text": "POV",
            "mood": "energetic",
        }
    finally:
        for fp in frame_paths:
            if os.path.exists(fp):
                os.remove(fp)
        if os.path.exists(frames_dir):
            os.rmdir(frames_dir)
