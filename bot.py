import os
import re
import asyncio
import tempfile
import phonenumbers
import gradio as gr
from telegram import Update, Document, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, ConversationHandler
)
from pymongo import MongoClient

WAITING_FILENAME, WAITING_CONTACTNAME, WAITING_CHUNK_SIZE, WAITING_START_NUMBER, WAITING_INPUT_METHOD, WAITING_VCF_FILE, WAITING_VCF_OPTION = range(7)
OWNER_ID = 7238904265
bot_status = "✅ Bot Telegram aktif dan siap digunakan."

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://zeyndevv:zeyn123663@cluster0.vt3xi.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
client = MongoClient(MONGO_URI)
db = client["vcf_bot"]
whitelist_col = db["whitelist"]

def is_owner(user_id):
    return int(user_id) == OWNER_ID

def is_whitelisted(user_id):
    return whitelist_col.find_one({"user_id": int(user_id)}) is not None or is_owner(user_id)

def add_to_whitelist_db(user_id: int):
    if not is_whitelisted(user_id):
        whitelist_col.insert_one({"user_id": int(user_id)})

def remove_from_whitelist_db(user_id: int):
    whitelist_col.delete_one({"user_id": int(user_id)})

def is_valid_phone(number: str) -> bool:
    try:
        number = number.strip()
        if not number.startswith("+"):
            number = "+" + number
        parsed = phonenumbers.parse(number, None)
        return phonenumbers.is_valid_number(parsed)
    except phonenumbers.NumberParseException:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not (is_whitelisted(user_id) or is_owner(user_id)):
        await update.message.reply_text(f"🚫 Kamu tidak diizinkan menggunakan bot ini.\n🆔 ID kamu: `{user_id}`", parse_mode="Markdown")
        return ConversationHandler.END

    await update.message.reply_text("📝 Masukkan *nama dasar file VCF* (tanpa .vcf):", parse_mode="Markdown")
    return WAITING_FILENAME

# (... lanjutkan semua fungsi kamu seperti sebelumnya tanpa U+00A0)

# === Gradio & Run ===
async def run_bot():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN tidak ditemukan di environment variable.")
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FILENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename)],
            WAITING_CONTACTNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contactname)],
            WAITING_CHUNK_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_chunk_size)],
            WAITING_START_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_start_number)],
            WAITING_INPUT_METHOD: [MessageHandler(filters.ALL, handle_input_method)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    vcf_to_txt_conv = ConversationHandler(
        entry_points=[CommandHandler("vcftotxt", start_vcf_to_txt)],
        states={
            WAITING_VCF_OPTION: [CallbackQueryHandler(choose_vcf_option)],
            WAITING_VCF_FILE: [MessageHandler(filters.Document.ALL, handle_vcf_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(vcf_to_txt_conv)
    app.add_handler(CommandHandler("adduser", add_to_whitelist))
    app.add_handler(CommandHandler("deluser", delete_from_whitelist))
    app.add_handler(CommandHandler("cekuser", check_user_status))
    app.add_error_handler(error_handler)
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    async def main():
        bot_task = asyncio.create_task(run_bot())
        gradio_interface = gr.Interface(
            fn=lambda: bot_status,
            inputs=[],
            outputs="text",
            title="Status Bot Telegram",
            live=False,
            flagging_mode="never"
        )
        gradio_task = asyncio.to_thread(gradio_interface.launch, server_name="0.0.0.0", server_port=7860, share=False)
        await asyncio.gather(bot_task, gradio_task)

    asyncio.run(main())
    
