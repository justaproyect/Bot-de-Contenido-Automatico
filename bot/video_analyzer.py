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


def extract_frames(video_path: str, num_frames: int = 8) -> list[str]:
    duration = get_video_duration(video_path)
    frames_dir = tempfile.mkdtemp()
    frame_paths = []

    for i in range(num_frames):
        timestamp = (duration / (num_frames + 1)) * (i + 1)
        frame_path = os.path.join(frames_dir, f"frame_{i}.jpg")
        cmd = [
            "ffmpeg", "-y", "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1", "-q:v", "3",
            "-vf", "scale=640:-1",
            frame_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=15, check=True)
            if os.path.exists(frame_path):
                frame_paths.append(frame_path)
        except Exception:
            continue

    return frame_paths


def analyze_video(video_path: str) -> dict:
    duration = get_video_duration(video_path)

    if not GEMINI_AVAILABLE or not GEMINI_API_KEY:
        return default_analysis(duration)

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    frame_paths = extract_frames(video_path, num_frames=8)

    if not frame_paths:
        return default_analysis(duration)

    try:
        import PIL.Image
        images = [PIL.Image.open(fp) for fp in frame_paths if os.path.exists(fp)]

        prompt = f"""Eres un editor profesional de contenido para Instagram Reels/TikTok. 
El video dura {duration:.1f} segundos.

Tu cliente vende ARTICULOS POKEMON (figuras, peluches, cartas, etc).
Tu tarea es analizar este video y crear el MEJOR contenido posible.

Analiza cada frame cuidadosamente. Identifica:
1. Que productos Pokemon aparecen
2. Que momentos son mas impactantes o llamativos
3. Que texto gancho funcionaria mejor
4. El mood general del video

Responde SOLO con este JSON (sin nada mas):
{{
    "productos_detectados": ["lista de productos Pokemon que ves"],
    "momentos_clave": [
        {{"inicio": 0.0, "fin": 5.0, "razon": "por que este momento es bueno"}}
    ],
    "texto_overlay": "TEXTO GANCHO que aparece en el video (maximo 6 palabras, estilo POV o gancho)",
    "hashtags": ["15 hashtags relevantes para Pokemon, merchandise, unboxing, reels, viral"],
    "descripcion_para_caption": "Caption llamativo para Instagram (1-2 lineas, con emojis)",
    "mood": "energetic/calm/funny/dramatic",
    "mejor_momento_inicio": 0.0,
    "mejor_momento_fin": 8.0,
    "consejo_edicion": "consejo especifico para editar este video"
}}"""

        response = model.generate_content([prompt] + images)
        text = response.text

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text.strip())

        result["clips"] = [{
            "start": result.get("mejor_momento_inicio", 0),
            "end": result.get("mejor_momento_fin", min(8, duration)),
            "energy": 1.0,
        }]

        if "momentos_clave" in result and result["momentos_clave"]:
            for momento in result["momentos_clave"]:
                if "inicio" in momento and "fin" in momento:
                    result["clips"].append({
                        "start": momento["inicio"],
                        "end": momento["fin"],
                        "energy": 0.9,
                    })

        result["clips"] = result["clips"][:3]
        result["duration"] = duration
        result["frames_analyzed"] = len(images)

        return result

    except Exception as e:
        logger.error(f"Gemini analysis error: {e}")
        return default_analysis(duration)
    finally:
        for fp in frame_paths:
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
        try:
            os.rmdir(os.path.dirname(frame_paths[0])) if frame_paths else None
        except Exception:
            pass


def default_analysis(duration: float) -> dict:
    return {
        "productos_detectados": [],
        "momentos_clave": [],
        "texto_overlay": "POV",
        "hashtags": ["pokemon", "pokemonmerch", "pokemonunboxing", "viral", "fyp", "reels", "trending", "pokemonfan", "pokemoncollector", "pokemon toys", "anime", "gaming", "cute", "kawaii", "pokemonart"],
        "descripcion_para_caption": "Momentos EPICOS con productos Pokemon! #pokemon",
        "mood": "energetic",
        "mejor_momento_inicio": 0,
        "mejor_momento_fin": min(8, duration),
        "consejo_edicion": "Cortar los momentos mas llamativos",
        "clips": [{"start": 0, "end": min(8, duration), "energy": 1.0}],
        "duration": duration,
        "frames_analyzed": 0,
    }
