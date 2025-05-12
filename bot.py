import os
import threading

# Fix untuk matplotlib error di Hugging Face
os.environ["MPLCONFIGDIR"] = "/tmp"

from flask import Flask
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import gradio as gr

# --- Telegram Bot Logic ---
WAITING_FILENAME, WAITING_CONTACTNAME, WAITING_CHUNK_SIZE, WAITING_START_NUMBER, WAITING_FILE = range(5)
user_data = {}
bot_status = "Aktif"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Masukkan *nama dasar file VCF* (tanpa .vcf):", parse_mode="Markdown")
    return WAITING_FILENAME

async def get_filename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    filename = update.message.text.strip()
    if not filename:
        await update.message.reply_text("⚠️ Nama file tidak boleh kosong.")
        return WAITING_FILENAME
    user_data[user_id] = {"filename": filename}
    await update.message.reply_text("👤 Masukkan *nama dasar kontak* (misal: Siswa):", parse_mode="Markdown")
    return WAITING_CONTACTNAME

async def get_contactname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    contact_name = update.message.text.strip()
    if not contact_name:
        await update.message.reply_text("⚠️ Nama kontak tidak boleh kosong.")
        return WAITING_CONTACTNAME
    user_data[user_id]["contact_name"] = contact_name
    await update.message.reply_text("🔢 Masukkan jumlah *nomor per file VCF* (misal: 100):", parse_mode="Markdown")
    return WAITING_CHUNK_SIZE

async def get_chunk_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        chunk_size = int(update.message.text.strip())
        if chunk_size < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Masukkan angka yang valid.")
        return WAITING_CHUNK_SIZE
    user_data[user_id]["chunk_size"] = chunk_size
    await update.message.reply_text("🔢 Masukkan nomor awal untuk penomoran kontak (misal: 40):")
    return WAITING_START_NUMBER

async def get_start_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        start_number = int(update.message.text.strip())
        if start_number < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Masukkan angka valid sebagai nomor awal.")
        return WAITING_START_NUMBER
    user_data[user_id]["start_number"] = start_number
    await update.message.reply_text("📄 Sekarang upload file `.txt` yang berisi daftar nomor (satu nomor per baris):")
    return WAITING_FILE

async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_data:
        await update.message.reply_text("⚠️ Silakan ketik /start terlebih dahulu.")
        return ConversationHandler.END

    document: Document = update.message.document
    if document.mime_type != 'text/plain':
        await update.message.reply_text("❌ File bukan .txt. Upload file yang benar.")
        return WAITING_FILE

    file = await context.bot.get_file(document.file_id)
    file_path = await file.download_to_drive()

    with open(file_path, 'r', encoding='utf-8') as f:
        numbers = [line.strip() for line in f if line.strip().isdigit()]
    os.remove(file_path)

    if not numbers:
        await update.message.reply_text("⚠️ File kosong atau tidak mengandung nomor valid.")
        return ConversationHandler.END

    chunk_size = user_data[user_id]["chunk_size"]
    base_name = user_data[user_id]["filename"]
    contact_name = user_data[user_id]["contact_name"]
    start_number = user_data[user_id]["start_number"]

    vcf_files = []
    counter = start_number
    for i in range(0, len(numbers), chunk_size):
        chunk = numbers[i:i+chunk_size]
        vcf_content = ""
        for number in chunk:
            vcf_content += f"""BEGIN:VCARD
VERSION:3.0
FN:{contact_name} {counter}
TEL;TYPE=CELL:{number}
END:VCARD
"""
            counter += 1
        filename = f"{base_name}_{(i//chunk_size)+1}.vcf"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(vcf_content)
        vcf_files.append(filename)

    for file in vcf_files:
        await update.message.reply_document(open(file, 'rb'))
        os.remove(file)

    user_data.pop(user_id, None)
    await update.message.reply_text("✅ Semua file berhasil dibuat dan dikirim!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operasi dibatalkan.")
    return ConversationHandler.END

# --- Run Bot in Thread ---
def run_bot():
    TOKEN = os.environ.get("BOT_TOKEN")  # Simpan token di Secrets atau env
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN tidak ditemukan. Atur BOT_TOKEN di Secrets Hugging Face!")
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FILENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_filename)],
            WAITING_CONTACTNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contactname)],
            WAITING_CHUNK_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_chunk_size)],
            WAITING_START_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_start_number)],
            WAITING_FILE: [MessageHandler(filters.Document.ALL, handle_txt_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    print("🤖 Bot Telegram sedang berjalan...")
    app.run_polling()

# --- Gradio Web UI (Index Page) ---
def create_gradio_interface():
    with gr.Blocks() as demo:
        gr.Markdown("## Status Bot Telegram VCF Generator")
        status_output = gr.Textbox(value=f"Bot Status: {bot_status}", label="Status Bot", interactive=False)
        check_btn = gr.Button("Check Status")
        check_btn.click(fn=lambda: f"Bot Status: {bot_status}", inputs=[], outputs=status_output)
    demo.launch(server_name="0.0.0.0", server_port=7860)

# --- Start Bot + Web Interface ---
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    create_gradio_interface()