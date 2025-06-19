
import os
import re
import asyncio
import tempfile
import zipfile
import phonenumbers
import gradio as gr
from telegram import Update, Document, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, ConversationHandler
)
from pymongo import MongoClient

# === Konstanta dan Status ===
WAITING_FILENAME, WAITING_CONTACTNAME, WAITING_CHUNK_SIZE, WAITING_START_NUMBER, WAITING_INPUT_METHOD, WAITING_VCF_FILE, WAITING_VCF_OPTION = range(7)
OWNER_ID = 7238904265
bot_status = "✅ Bot Telegram aktif dan siap digunakan."

# === Koneksi MongoDB ===
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://zeyndevv:zeyn123663@cluster0.vt3xi.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
client = MongoClient(MONGO_URI)
db = client["vcf_bot"]
whitelist_col = db["whitelist"]

# === Fungsi Whitelist ===
def is_owner(user_id):
    return int(user_id) == OWNER_ID

def is_whitelisted(user_id):
    return whitelist_col.find_one({"user_id": int(user_id)}) is not None or is_owner(user_id)

def add_to_whitelist_db(user_id: int):
    if not is_whitelisted(user_id):
        whitelist_col.insert_one({"user_id": int(user_id)})

# === Fungsi Validasi Nomor ===
def is_valid_phone(number: str) -> bool:
    try:
        number = number.strip()
        if not number.startswith("+"):
            number = "+" + number
        parsed = phonenumbers.parse(number, None)
        return phonenumbers.is_valid_number(parsed)
    except phonenumbers.NumberParseException:
        return False

# === VCF to TXT ===
async def start_vcf_to_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_whitelisted(update.effective_user.id):
        await update.message.reply_text("❌ Kamu tidak diizinkan menggunakan fitur ini.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📛 Nama & Nomor", callback_data="with_name")],
        [InlineKeyboardButton("📱 Nomor Saja", callback_data="number_only")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Pilih format output TXT:", reply_markup=reply_markup)
    return WAITING_VCF_OPTION

async def choose_vcf_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["vcf_output_mode"] = query.data
    await query.edit_message_text("📤 Silakan kirim file `.vcf` yang ingin dikonversi.")
    return WAITING_VCF_FILE

async def handle_vcf_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document: Document = update.message.document
    if not document.file_name.endswith(".vcf"):
        await update.message.reply_text("⚠️ File yang dikirim bukan file .vcf.")
        return WAITING_VCF_FILE

    file_path = os.path.join(tempfile.gettempdir(), document.file_name)
    telegram_file = await context.bot.get_file(document.file_id)
    await telegram_file.download_to_drive(custom_path=file_path)

    output_lines = []
    with open(file_path, 'r', encoding='utf-8') as f:
        name, phone = None, None
        for line in f:
            if line.startswith("FN:"):
                name = line.strip().replace("FN:", "")
            elif line.startswith("TEL"):
                phone = line.strip().split(":")[-1]
                if phone:
                    if context.user_data.get("vcf_output_mode") == "with_name" and name:
                        output_lines.append(f"{name} - {phone}")
                    else:
                        output_lines.append(phone)
                    name, phone = None, None

    os.remove(file_path)

    if not output_lines:
        await update.message.reply_text("❌ Tidak ditemukan data kontak dalam file.")
        return ConversationHandler.END

    txt_output = "".join(output_lines)
    txt_filename = "converted.txt"
    txt_path = os.path.join(tempfile.gettempdir(), txt_filename)

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(txt_output)

    with open(txt_path, 'rb') as f:
        await update.message.reply_document(document=f, filename=txt_filename)
    os.remove(txt_path)

    await update.message.reply_text("✅ File berhasil dikonversi!")
    return ConversationHandler.END

# === Whitelist ===
async def add_to_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Hanya owner yang bisa menambah whitelist.")
        return
    try:
        new_user_id = int(context.args[0])
        add_to_whitelist_db(new_user_id)
        await update.message.reply_text(f"✅ User ID {new_user_id} berhasil ditambahkan ke whitelist.")
    except:
        await update.message.reply_text("⚠️ Gunakan format: /adduser <id_telegram>")

async def check_user_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status = (
        f"🆔 ID kamu: `{user_id}`
"
        f"👑 Owner: {'Ya' if is_owner(user_id) else 'Tidak'}
"
        f"✅ Whitelisted: {'Ya' if is_whitelisted(user_id) else 'Tidak'}"
    )
    await update.message.reply_text(status, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operasi dibatalkan.")
    context.user_data.clear()
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"⚠️ ERROR: {context.error}")

async def run_bot():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN tidak ditemukan di environment variable.")
    app = ApplicationBuilder().token(TOKEN).build()

    vcf_to_txt_conv = ConversationHandler(
        entry_points=[CommandHandler("vcftotxt", start_vcf_to_txt)],
        states={
            WAITING_VCF_OPTION: [CallbackQueryHandler(choose_vcf_option)],
            WAITING_VCF_FILE: [MessageHandler(filters.Document.ALL, handle_vcf_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(vcf_to_txt_conv)
    app.add_handler(CommandHandler("adduser", add_to_whitelist))
    app.add_handler(CommandHandler("cekuser", check_user_status))
    app.add_error_handler(error_handler)
    await app.run_polling()

# === START ===
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
