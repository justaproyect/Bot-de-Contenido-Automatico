import os
import subprocess
import json
import tempfile
import logging

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from bot.config import GEMINI_API_KEY


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


def extract_frames(video_path: str, num_frames: int = 4) -> list[str]:
    duration = get_video_duration(video_path)
    frames_dir = tempfile.mkdtemp()
    frame_paths = []

    for i in range(num_frames):
        timestamp = (duration / (num_frames + 1)) * (i + 1)
        frame_path = os.path.join(frames_dir, f"frame_{i}.jpg")
        cmd = [
            "ffmpeg", "-y", "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1", "-q:v", "5",
            "-vf", "scale=320:-1",
            frame_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=10, check=True)
            if os.path.exists(frame_path):
                frame_paths.append(frame_path)
        except Exception:
            continue

    return frame_paths


def analyze_video(video_path: str) -> dict:
    duration = get_video_duration(video_path)

    if duration < 10:
        return default_analysis(duration)

    if not GEMINI_AVAILABLE or not GEMINI_API_KEY:
        return default_analysis(duration)

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    frame_paths = extract_frames(video_path, num_frames=2)

    if not frame_paths:
        return default_analysis(duration)

    try:
        import PIL.Image
        images = [PIL.Image.open(fp) for fp in frame_paths[:2] if os.path.exists(fp)]

        prompt = f"""Video Pokemon {duration:.0f}s. JSON solo:
{{
"productos":["lista"],
"texto":"MAX5 PALABRAS",
"estilo":"impactante/emocional/divertido/urgente",
"hashtags":["10 tags"],
"caption":"1 linea con emojis",
"mood":"energetic/calm/dramatic"
}}"""

        response = model.generate_content(
            [prompt] + images,
            generation_config=genai.GenerationConfig(
                max_output_tokens=300,
                temperature=0.7,
            )
        )
        text = response.text

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text.strip())

        result["clips"] = [{"start": 0, "end": min(6, duration), "energy": 1.0}]
        result["duration"] = duration
        result["frames_analyzed"] = len(images)

        if "productos" in result:
            result["productos_detectados"] = result.pop("productos")
        if "texto" in result:
            result["texto_principal"] = result.pop("texto")
            result["texto_secundario"] = ""
        if "estilo" in result:
            result["estilo_texto"] = result.pop("estilo")

        if "texto_principal" not in result:
            result["texto_principal"] = "POV"
        if "estilo_texto" not in result:
            result["estilo_texto"] = "impactante"
        if "posicion_texto" not in result:
            result["posicion_texto"] = "centro"
        if "call_to_action" not in result:
            result["call_to_action"] = "Visita nuestra tienda!"
        if "hashtag" in result:
            result["hashtags"] = result.pop("hashtag")

        return result

    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return default_analysis(duration)
    finally:
        for fp in frame_paths:
            if os.path.exists(fp):
                try: os.remove(fp)
                except: pass
        try:
            os.rmdir(os.path.dirname(frame_paths[0])) if frame_paths else None
        except: pass


def default_analysis(duration: float) -> dict:
    return {
        "productos_detectados": [],
        "texto_principal": "POKEMON EXCLUSIVO",
        "texto_secundario": "MIRA ESTO",
        "estilo_texto": "impactante",
        "posicion_texto": "centro",
        "hashtags": ["pokemon", "pokemonmerch", "pokemonunboxing", "viral", "fyp", "reels", "trending", "pokemonfan", "pokemoncollector", "pokemon toys", "anime", "gaming", "cute", "kawaii", "pokemonart"],
        "caption": "Productos Pokemon que NO te puedes perder! #pokemon",
        "call_to_action": "Visita nuestra tienda!",
        "mejor_momento_inicio": 0,
        "mejor_momento_fin": min(8, duration),
        "momentos_clave": [],
        "emocion_objetivo": "exclusividad y coleccionismo",
        "mood": "energetic",
        "clips": [{"start": 0, "end": min(8, duration), "energy": 1.0}],
        "duration": duration,
        "frames_analyzed": 0,
    }
