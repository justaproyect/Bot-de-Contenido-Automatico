import os
import asyncio
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
from bot.video_analyzer import analyze_video
from bot.video_editor import edit_video, compress_for_telegram
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
        "Hola! Soy tu editor de contenido Pokemon.\n\n"
        "Envia un video y yo:\n"
        "- Analizo que Pokemon y productos aparecen\n"
        "- Selecciono los mejores momentos\n"
        "- Creo texto gancho y hashtags\n"
        "- Editos el video automaticamente\n\n"
        "Envia tu video!"
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

    status_msg = await update.message.reply_text("Recibido! Analizando video con IA...")
    video_path = None

    try:
        file = await context.bot.get_file(video.file_id)
        ext = ".mp4"
        if video.file_name:
            ext = os.path.splitext(video.file_name)[1] or ".mp4"

        video_path = os.path.join(TEMP_DIR, f"{update.effective_user.id}{ext}")
        await file.download_to_drive(video_path)

        await status_msg.edit_text("Gemini esta analizando el video...")

        analysis = await asyncio.to_thread(analyze_video, video_path)

        productos = analysis.get("productos_detectados", [])
        texto = analysis.get("texto_overlay", "POV")
        mood = analysis.get("mood", "energetic")
        consejo = analysis.get("consejo_edicion", "")

        productos_str = ", ".join(productos[:5]) if productos else "Detectando..."

        await status_msg.edit_text(
            f"Gemini detecto:\n"
            f"- Productos: {productos_str}\n"
            f"- Mood: {mood}\n"
            f"- Texto: {texto}\n"
            f"- Editando..."
        )

        clips = analysis.get("clips", [{"start": 0, "end": 8, "energy": 1.0}])

        user_id = update.effective_user.id
        output_path = os.path.join(TEMP_DIR, f"{user_id}_edited.mp4")

        edit_result = await asyncio.to_thread(
            edit_video,
            video_path,
            clips,
            texto,
            output_path,
        )

        hashtags = analysis.get("hashtags", ["pokemon", "viral", "fyp"])
        hashtag_str = " ".join([f"#{h}" for h in hashtags])

        caption = analysis.get("descripcion_para_caption", "Pokemon content!")

        if not edit_result.get("final") or not os.path.exists(edit_result["final"]):
            await status_msg.edit_text("Error al editar. Intenta con otro video.")
            cleanup_local_files(video_path)
            return WAITING_VIDEO

        await status_msg.edit_text("Subiendo video...")
        cloud_result = upload_video(edit_result["final"], folder="pokemon-content")

        user_sessions[user_id] = {
            "video_path": video_path,
            "edited_path": edit_result["final"],
            "cloud_url": cloud_result.get("url"),
            "cloud_public_id": cloud_result.get("public_id"),
            "hashtags": hashtag_str,
            "caption": caption,
            "analysis": analysis,
        }

        keyboard = [
            [
                InlineKeyboardButton("Aprobar", callback_data="approve"),
                InlineKeyboardButton("Rechazar", callback_data="reject"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text("Video listo!")

        send_path = edit_result["final"]
        compressed_path = os.path.join(TEMP_DIR, f"{user_id}_compressed.mp4")
        send_path = compress_for_telegram(edit_result["final"], compressed_path)

        with open(send_path, "rb") as video_file:
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_file,
                caption=f"{caption}\n\n{hashtag_str}",
            )

        analysis_msg = (
            f"Analisis Gemini:\n"
            f"- Productos: {productos_str}\n"
            f"- Momentos clave: {len(analysis.get('momentos_clave', []))}\n"
            f"- Frames analizados: {analysis.get('frames_analyzed', 0)}\n"
        )
        if consejo:
            analysis_msg += f"- Consejo: {consejo}\n"

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=analysis_msg,
            reply_markup=reply_markup,
        )

        cleanup_local_files(edit_result["final"], compressed_path)
        return WAITING_APPROVAL

    except Exception as e:
        import traceback
        print(f"ERROR: {traceback.format_exc()}")
        await status_msg.edit_text(
            f"Error: {str(e)[:200]}\nIntenta con otro video."
        )
        if video_path:
            cleanup_local_files(video_path)
        return WAITING_VIDEO


async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    session = user_sessions.get(user_id)

    if not session:
        await query.edit_message_text("No hay video pendiente.")
        return ConversationHandler.END

    if query.data == "approve":
        approved_dir = os.path.join(OUTPUT_DIR, "approved")
        os.makedirs(approved_dir, exist_ok=True)

        info_file = os.path.join(approved_dir, f"approved_{user_id}_info.txt")
        with open(info_file, "w", encoding="utf-8") as f:
            f.write(f"Caption: {session['caption']}\n\n")
            f.write(f"Hashtags: {session['hashtags']}\n\n")
            if session.get("analysis"):
                import json
                f.write(f"Analisis completo:\n{json.dumps(session['analysis'], indent=2, ensure_ascii=False)}")

        caption = f"Video aprobado!\n\nCaption:\n{session['caption']}\n\nHashtags:\n{session['hashtags']}"

        if session.get("cloud_url"):
            caption += f"\n\nLink: {session['cloud_url']}"

        await query.edit_message_text(caption)
        cleanup_local_files(session.get("video_path"), session.get("edited_path"))
        del user_sessions[user_id]
        return ConversationHandler.END

    elif query.data == "reject":
        await query.edit_message_text("Rechazado. Envia otro video.")
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
    await update.message.reply_text("Cancelado.")
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
