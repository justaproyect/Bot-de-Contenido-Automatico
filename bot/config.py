import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "temp")
MUSIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "music")
FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

MAX_VIDEO_DURATION = 120
CLIP_MIN_DURATION = 2
CLIP_MAX_DURATION = 8
ENERGY_THRESHOLD_PERCENTILE = 75
NUM_CLIPS = 5
BACKGROUND_MUSIC_VOLUME = 0.15
TEXT_OVERLAY = "POV"
