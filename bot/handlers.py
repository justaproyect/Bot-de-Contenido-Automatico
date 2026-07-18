import os
import asyncio
import shutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)

from bot.config import TELEGRAM_BOT_TOKEN, OUTPUT_DIR, TEMP_DIR, ALLOWED_USERS
from bot.video_analyzer import analyze_audio_energy, analyze_video_content
from bot.video_editor import edit_video
from bot.storage import upload_video, delete_video, cleanup_local_files

WAITING_VIDEO, WAITING_APPROVAL = range(2)

user_sessions = {}


def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    allowed = [int(uid.strip()) for uid in ALLOWED_USERS.split(",") if uid.strip()]
    return user_id in allowed


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("No tienes acceso a este bot.")
        return ConversationHandler.END

    await update.message.reply_text(
        "Hola! Soy tu bot de edicion de contenido automatico.\n\n"
        "Envia un video y lo editare automaticamente:\n"
        "- Analizare los mejores momentos por audio\n"
        "- Cortare los clips mas energeticos\n"
        "- Agregare texto POV y musica\n"
        "- Te enviare el resultado para que apruebes\n\n"
        "Envia tu video ahora!"
    )
    return WAITING_VIDEO


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("No tienes acceso a este bot.")
        return ConversationHandler.END

    video = update.message.video or update.message.document
    if not video:
        await update.message.reply_text("Por favor envia un video.")
        return WAITING_VIDEO

    if video.file_size and video.file_size > 2 * 1024 * 1024 * 1024:
        await update.message.reply_text(
            "El video es muy grande (maximo 2GB). Comprimelo e intenta de nuevo."
        )
        return WAITING_VIDEO

    status_msg = await update.message.reply_text("Recibido! Descargando video...")

    try:
        file = await context.bot.get_file(video.file_id)
        ext = ".mp4"
        if video.file_name:
            ext = os.path.splitext(video.file_name)[1] or ".mp4"

        video_path = os.path.join(TEMP_DIR, f"{update.effective_user.id}{ext}")
        await file.download_to_drive(video_path)

        await status_msg.edit_text("Analizando audio y detectando momentos energeticos...")
        segments = analyze_audio_energy(video_path)

        await status_msg.edit_text("Analizando contenido del video con IA...")
        video_info = await asyncio.to_thread(analyze_video_content, video_path)

        await status_msg.edit_text(
            f"Editando video...\n"
            f"Encontre {len(segments)} momentos energeticos\n"
            f"IA detecto: {video_info.get('mood', 'desconocido')}"
        )

        user_id = update.effective_user.id
        output_path = os.path.join(TEMP_DIR, f"{user_id}_edited.mp4")

        edit_result = await asyncio.to_thread(
            edit_video,
            video_path,
            segments,
            video_info.get("suggested_text", "POV"),
            output_path,
        )

        hashtags = video_info.get("hashtags", ["viral", "trending", "fyp"])
        hashtag_str = " ".join([f"#{h}" for h in hashtags])

        if not edit_result.get("final") or not os.path.exists(edit_result["final"]):
            await status_msg.edit_text("Error al editar el video. Intenta con otro video.")
            cleanup_local_files(video_path)
            return WAITING_VIDEO

        cloud_result = upload_video(edit_result["final"], folder="edited-videos")

        user_sessions[user_id] = {
            "video_path": video_path,
            "edited_path": edit_result["final"],
            "cloud_url": cloud_result.get("url"),
            "cloud_public_id": cloud_result.get("public_id"),
            "hashtags": hashtag_str,
            "video_info": video_info,
            "segments": segments,
        }

        keyboard = [
            [
                InlineKeyboardButton("Aprobar", callback_data="approve"),
                InlineKeyboardButton("Rechazar", callback_data="reject"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text("Video editado! Revisalo:")

        with open(edit_result["final"], "rb") as video_file:
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_file,
                caption=(
                    f"Video editado automaticamente\n\n"
                    f"Hashtags para Instagram:\n{hashtag_str}\n\n"
                    f"Descripcion IA: {video_info.get('description', 'N/A')}"
                ),
            )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Aprobado? Haz clic en el boton:",
            reply_markup=reply_markup,
        )

        cleanup_local_files(edit_result["final"])

        return WAITING_APPROVAL

    except Exception as e:
        await status_msg.edit_text(f"Error procesando video: {str(e)}")
        cleanup_local_files(video_path)
        return WAITING_VIDEO


async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    session = user_sessions.get(user_id)

    if not session:
        await query.edit_message_text("No hay video pendiente de aprobacion.")
        return ConversationHandler.END

    if query.data == "approve":
        approved_dir = os.path.join(OUTPUT_DIR, "approved")
        os.makedirs(approved_dir, exist_ok=True)

        hashtag_file = os.path.join(approved_dir, f"approved_{user_id}_hashtags.txt")
        with open(hashtag_file, "w") as f:
            f.write(session["hashtags"])

        caption = (
            f"Video aprobado!\n\n"
            f"Hashtags:\n{session['hashtags']}\n\n"
        )

        if session.get("cloud_url"):
            caption += f"Link del video: {session['cloud_url']}\n\n"
            caption += "Descarga el video desde el link y subelo a Instagram."
        else:
            caption += "El video se guardo localmente."

        await query.edit_message_text(caption)

        cleanup_local_files(session.get("video_path"), session.get("edited_path"))
        del user_sessions[user_id]
        return ConversationHandler.END

    elif query.data == "reject":
        await query.edit_message_text(
            "Video rechazado. Envia otro video para intentar de nuevo."
        )

        delete_video(session.get("cloud_public_id"))
        cleanup_local_files(session.get("video_path"), session.get("edited_path"))

        del user_sessions[user_id]
        return WAITING_VIDEO


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        session = user_sessions.pop(user_id)
        delete_video(session.get("cloud_public_id"))
        cleanup_local_files(session.get("video_path"), session.get("edited_path"))

    await update.message.reply_text("Sesion cancelada.")
    return ConversationHandler.END


def get_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_VIDEO: [
                MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive_video),
                CommandHandler("cancel", cancel),
            ],
            WAITING_APPROVAL: [
                CallbackQueryHandler(handle_approval, pattern="^(approve|reject)$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
