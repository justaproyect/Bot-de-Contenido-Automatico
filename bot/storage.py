import os
import tempfile
import cloudinary
import cloudinary.uploader
import cloudinary.api

from bot.config import OUTPUT_DIR

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", ""),
    api_key=os.getenv("CLOUDINARY_API_KEY", ""),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", ""),
)


def upload_video(video_path: str, folder: str = "telegram-bot") -> dict:
    if not os.getenv("CLOUDINARY_CLOUD_NAME"):
        return {"url": video_path, "public_id": None, "use_local": True}

    try:
        result = cloudinary.uploader.upload(
            video_path,
            resource_type="video",
            folder=folder,
            overwrite=True,
        )
        return {
            "url": result.get("secure_url", video_path),
            "public_id": result.get("public_id"),
            "use_local": False,
        }
    except Exception as e:
        print(f"Error uploading to Cloudinary: {e}")
        return {"url": video_path, "public_id": None, "use_local": True}


def download_video(public_id: str, output_path: str) -> str:
    if not public_id:
        return output_path

    try:
        url = cloudinary.CloudinaryImage(public_id).build_url(
            resource_type="video",
            format="mp4",
        )
        import urllib.request
        urllib.request.urlretrieve(url, output_path)
        return output_path
    except Exception as e:
        print(f"Error downloading from Cloudinary: {e}")
        return output_path


def delete_video(public_id: str):
    if not public_id:
        return
    try:
        cloudinary.uploader.destroy(public_id, resource_type="video")
    except Exception:
        pass


def cleanup_local_files(*paths):
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
