import os
import requests
import logging
import tempfile
from bot.config import MUSIC_DIR, JAMENDO_CLIENT_ID

logger = logging.getLogger(__name__)

JAMENDO_API = "https://api.jamendo.com/v3.0"


def search_music(query: str, limit: int = 5) -> list[dict]:
    if not JAMENDO_CLIENT_ID:
        logger.warning("JAMENDO_CLIENT_ID not set, using sample music")
        return []

    try:
        params = {
            "client_id": JAMENDO_CLIENT_ID,
            "format": "json",
            "limit": limit,
            "search": query,
            "include": "musicinfo",
            "audiodownload_allowed": "true",
        }
        resp = requests.get(f"{JAMENDO_API}/tracks/", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])
    except Exception as e:
        logger.error(f"Jamendo search error: {e}")
        return []


def download_track(track_url: str, output_path: str) -> bool:
    try:
        resp = requests.get(track_url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


def get_local_music(mood: str) -> str:
    local_tracks = {
        "energetic": "funk_breakbeat.mp3",
        "calm": "moment_of_peace.mp3",
        "funny": "funk_breakbeat.mp3",
        "dramatic": "wonders_of_earth.mp3",
        "emotional": "moment_of_peace.mp3",
    }
    track = local_tracks.get(mood, "no_copyright_viral.mp3")
    path = os.path.join(MUSIC_DIR, track)
    if os.path.exists(path):
        return path
    return ""


def get_music_for_mood(mood: str, energy: float = 0.7) -> str:
    local = get_local_music(mood)
    if local:
        return local

    if not JAMENDO_CLIENT_ID:
        return get_sample_music()

    mood_queries = {
        "energetic": "upbeat electronic pop",
        "calm": "ambient chill lofi",
        "funny": "fun comedy quirky",
        "dramatic": "epic cinematic trailer",
        "emotional": "emotional piano sad",
    }
    query = mood_queries.get(mood, "upbeat pop electronic")

    tracks = search_music(query, limit=3)
    if not tracks:
        return get_sample_music()

    for track in tracks:
        audio_url = track.get("audio")
        if not audio_url:
            continue

        track_name = track.get("name", "track").replace(" ", "_")[:30]
        output_path = os.path.join(MUSIC_DIR, f"{track_name}.mp3")

        if os.path.exists(output_path):
            logger.info(f"Using cached music: {track_name}")
            return output_path

        if download_track(audio_url, output_path):
            logger.info(f"Downloaded: {track_name} for mood={mood}")
            return output_path

    return get_sample_music()


def get_sample_music() -> str:
    sample = os.path.join(MUSIC_DIR, "sample_beat.mp3")
    if os.path.exists(sample):
        return sample
    return ""


def get_music_path(mood: str = None) -> str:
    if mood:
        music = get_music_for_mood(mood)
        if music:
            return music

    existing = get_sample_music()
    if existing:
        return existing

    return ""
