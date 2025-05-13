import os
os.environ['MPLCONFIGDIR'] = '/tmp/matplotlib-cache'
import asyncio
import tempfile
import zipfile
import gradio as gr

from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# States
WAITING_FILENAME, WAITING_CONTACTNAME, WAITING_CHUNK_SIZE, WAITING_START_NUMBER, WAITING_FILE = range(5)
user_data = {}

# Status flag
bot_status = "✅ Bot Telegram aktif dan siap digunakan."

# === BOT HANDLERS ===
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

    # Simpan file .txt yang dikirim user
    file_name = document.file_name
    file_path = os.path.join("/tmp", file_name)
    telegram_file = await context.bot.get_file(document.file_id)
    await telegram_file.download_to_drive(custom_path=file_path)

    # Baca nomor dari file
    with open(file_path, 'r', encoding='utf-8') as f:
        numbers = [line.strip() for line in f if line.strip().isdigit()]
    os.remove(file_path)

    if not numbers:
        await update.message.reply_text("⚠️ File kosong atau tidak mengandung nomor valid.")
        return ConversationHandler.END

    # Ambil data dari user
    chunk_size = user_data[user_id]["chunk_size"]
    base_name = user_data[user_id]["filename"]
    contact_name = user_data[user_id]["contact_name"]
    start_number = user_data[user_id]["start_number"]

    # Buat file VCF secara berkelompok
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

    # Kirim file ZIP jika terlalu banyak
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
            await asyncio.sleep(1.5)  # Hindari rate-limit Telegram

    user_data.pop(user_id, None)
    await update.message.reply_text("✅ Semua file berhasil dibuat dan dikirim!")
    return ConversationHandler.END

# Fungsi untuk membatalkan
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operasi dibatalkan.")
    return ConversationHandler.END

# === GRADIO APP ===
def create_gradio_interface():
    def status_check():
        return bot_status

    iface = gr.Interface(fn=status_check, inputs=[], outputs="text", title="Status Bot Telegram", live=False, allow_flagging="never")
    iface.launch(server_name="0.0.0.0", server_port=7860)

# === MAIN FUNCTION ===
async def run_bot():
    # TOKEN = os.environ.get("BOT_TOKEN")
    # if not TOKEN:
    #     raise ValueError("❌ BOT_TOKEN tidak ditemukan di environment variable.")

    app = ApplicationBuilder().token("8022523573:AAHqvIHf3YRfSw2k38E_0Ti8OVmVSo4ngOM").build()

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
    print("🤖 Bot Telegram berjalan...")
    await app.run_polling()

# === START SCRIPT ===
if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    create_gradio_interface()
    asyncio.run(run_bot())