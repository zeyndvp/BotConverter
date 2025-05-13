import os
import asyncio
import tempfile
import zipfile
import gradio as gr
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

from dotenv import load_dotenv
load_dotenv()

WAITING_FILENAME, WAITING_CONTACTNAME, WAITING_CHUNK_SIZE, WAITING_START_NUMBER, WAITING_FILE = range(5)
user_data = {}
bot_status = "✅ Bot Telegram aktif dan siap digunakan."

# === HANDLERS ===

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
    await update.message.reply_text("📄 Upload file `.txt` berisi nomor telepon (satu nomor per baris):")
    return WAITING_FILE

async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data:
        await update.message.reply_text("⚠️ Silakan ketik /start terlebih dahulu.")
        return ConversationHandler.END

    document: Document = update.message.document
    if document.mime_type != 'text/plain':
        await update.message.reply_text("❌ File bukan .txt.")
        return WAITING_FILE

    file_path = os.path.join("/tmp", document.file_name)
    telegram_file = await context.bot.get_file(document.file_id)
    await telegram_file.download_to_drive(custom_path=file_path)

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
    vcf_content = ""
    counter = start_number + 1
    file_index = 1

    for i, number in enumerate(numbers, 1):
        vcf_entry = f"""BEGIN:VCARD
VERSION:3.0
FN:{contact_name} {counter}
TEL;TYPE=CELL:{number}
END:VCARD
"""
        vcf_content += vcf_entry
        counter += 1

        if i % chunk_size == 0 or i == len(numbers):
            vcf_filename = f"{base_name}_{file_index}.vcf"
            vcf_path = os.path.join("/tmp", vcf_filename)
            with open(vcf_path, 'w', encoding='utf-8') as f:
                f.write(vcf_content)
            vcf_files.append(vcf_path)
            vcf_content = ""
            file_index += 1

    if len(vcf_files) > 500:
        zip_path = os.path.join("/tmp", f"{base_name}_all.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file in vcf_files:
                zipf.write(file, os.path.basename(file))
                os.remove(file)
        with open(zip_path, 'rb') as f:
            await update.message.reply_document(document=f, filename=os.path.basename(zip_path))
        os.remove(zip_path)
    else:
        for file in vcf_files:
            with open(file, 'rb') as f:
                await update.message.reply_document(document=f, filename=os.path.basename(file))
            os.remove(file)
            await asyncio.sleep(1.5)

    user_data.pop(user_id, None)
    await update.message.reply_text("✅ Semua file berhasil dibuat dan dikirim!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operasi dibatalkan.")
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"⚠️ ERROR: {context.error}")

async def run_bot():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN tidak ditemukan di .env")
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
    app.add_error_handler(error_handler)
    await app.run_polling()

# === START ===
if __name__ == "__main__":
    import threading
    import nest_asyncio
    nest_asyncio.apply()

    def start_bot():
        asyncio.run(run_bot())

    threading.Thread(target=start_bot).start()

    gr.Interface(
        fn=lambda: bot_status,
        inputs=[],
        outputs="text",
        title="Status Bot Telegram",
        live=False,
        allow_flagging="never"
    ).launch(server_name="0.0.0.0", server_port=7860, share=False)