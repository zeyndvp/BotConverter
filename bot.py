import os
import re
import json
import asyncio
import tempfile
import zipfile
import phonenumbers
import gradio as gr
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# === Konstanta dan Status ===
WAITING_FILENAME, WAITING_CONTACTNAME, WAITING_CHUNK_SIZE, WAITING_START_NUMBER, WAITING_INPUT_METHOD = range(5)
OWNER_ID = 7238904265
WHITELIST_PATH = "whitelist.json"
bot_status = "✅ Bot Telegram aktif dan siap digunakan."

# === Fungsi Whitelist ===
def load_whitelist():
    try:
        with open(WHITELIST_PATH, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_whitelist(whitelist):
    with open(WHITELIST_PATH, "w") as f:
        json.dump(list(whitelist), f)

def is_owner(user_id):
    return user_id == OWNER_ID

def is_whitelisted(user_id):
    return user_id in WHITELIST

WHITELIST = load_whitelist()
WHITELIST.add(OWNER_ID)
save_whitelist(WHITELIST)

def is_valid_phone(number: str) -> bool:
    try:
        number = number.strip()
        if not number.startswith("+"):
            number = "+" + number
        parsed = phonenumbers.parse(number, None)
        return phonenumbers.is_valid_number(parsed)
    except phonenumbers.NumberParseException:
        return False

# === Handler ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_whitelisted(user_id):
        await update.message.reply_text(
            f"🚫 Kamu tidak diizinkan menggunakan bot ini.\n🆔 ID kamu: `{user_id}`",
            parse_mode="Markdown")
        return ConversationHandler.END

    await update.message.reply_text("📝 Masukkan *nama dasar file VCF* (tanpa .vcf):", parse_mode="Markdown")
    return WAITING_FILENAME

async def get_filename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    filename = update.message.text.strip()
    if not filename:
        await update.message.reply_text("⚠️ Nama file tidak boleh kosong.")
        return WAITING_FILENAME
    context.user_data["filename"] = filename
    await update.message.reply_text("👤 Masukkan *format nama kontak* (contoh: Admin | 3 | Navy | 2):", parse_mode="Markdown")
    return WAITING_CONTACTNAME

async def get_contactname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    parts = [p.strip() for p in raw.split('|')]
    if len(parts) % 2 != 0:
        await update.message.reply_text("⚠️ Format tidak valid. Harus pasangan nama dan jumlah.")
        return WAITING_CONTACTNAME

    contact_plan = []
    for i in range(0, len(parts), 2):
        try:
            name = parts[i]
            count = int(parts[i+1])
            contact_plan.append((name, count))
        except:
            await update.message.reply_text("⚠️ Format salah di bagian: " + parts[i] + " | " + parts[i+1])
            return WAITING_CONTACTNAME

    context.user_data["contact_plan"] = contact_plan
    await update.message.reply_text("🔢 Masukkan jumlah *nomor per file VCF* (misal: 100):", parse_mode="Markdown")
    return WAITING_CHUNK_SIZE

async def get_chunk_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chunk_size = int(update.message.text.strip())
        if chunk_size < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Masukkan angka yang valid.")
        return WAITING_CHUNK_SIZE
    context.user_data["chunk_size"] = chunk_size
    await update.message.reply_text("🔢 Masukkan nomor awal untuk penomoran *file VCF* (misal: 1):")
    return WAITING_START_NUMBER

async def get_start_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        start_number = int(update.message.text.strip())
        if start_number < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Masukkan angka valid sebagai nomor awal.")
        return WAITING_START_NUMBER
    context.user_data["start_number"] = start_number
    await update.message.reply_text(
        "📥 Sekarang kirim daftar nomor:
1. Kirim *file .txt*
2. Atau langsung ketik/forward di chat (1 nomor per baris).",
        parse_mode="Markdown")
    return WAITING_INPUT_METHOD

async def handle_input_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document:
        return await handle_txt_file(update, context)
    elif update.message.text:
        return await handle_numbers_text(update, context)
    else:
        await update.message.reply_text("⚠️ Harap kirim file .txt atau daftar nomor langsung.")
        return WAITING_INPUT_METHOD

async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document: Document = update.message.document
    if document.mime_type != 'text/plain':
        await update.message.reply_text("❌ File bukan .txt.")
        return WAITING_INPUT_METHOD

    file_path = os.path.join(tempfile.gettempdir(), document.file_name)
    telegram_file = await context.bot.get_file(document.file_id)
    await telegram_file.download_to_drive(custom_path=file_path)
    with open(file_path, 'r', encoding='utf-8') as f:
        raw_lines = [line.strip() for line in f if line.strip()]
    os.remove(file_path)
    numbers = [line for line in raw_lines if is_valid_phone(line)]
    if not numbers:
        await update.message.reply_text("❌ Tidak ditemukan nomor telepon yang valid.")
        return WAITING_INPUT_METHOD
    return await process_numbers(update, context, numbers)

async def handle_numbers_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_lines = [line.strip() for line in update.message.text.splitlines() if line.strip()]
    numbers = [line for line in raw_lines if is_valid_phone(line)]
    if not numbers:
        await update.message.reply_text("❌ Tidak ditemukan nomor telepon yang valid.")
        return WAITING_INPUT_METHOD
    return await process_numbers(update, context, numbers)

async def process_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, numbers: list[str]):
    data = context.user_data
    chunk_size = data["chunk_size"]
    base_name = data["filename"]
    start_number = data["start_number"]
    contact_plan = data["contact_plan"]

    await update.message.reply_text("⏳ Sedang membuat file VCF...")

    vcf_files = []
    vcf_content = ""
    file_counter = start_number
    current_name_idx = 0
    current_name, remaining = contact_plan[current_name_idx]
    contact_counter = 1

    for i, raw_number in enumerate(numbers, 1):
        number = raw_number.strip()
        if not number.startswith("+"):
            number = "+" + number

        name = f"{current_name} {contact_counter}"
        vcf_entry = f"""BEGIN:VCARD
VERSION:3.0
FN:{name}
TEL;TYPE=CELL:{number}
END:VCARD
"""
        vcf_content += vcf_entry
        contact_counter += 1
        remaining -= 1

        if remaining == 0 and current_name_idx + 1 < len(contact_plan):
            current_name_idx += 1
            current_name, remaining = contact_plan[current_name_idx]
            contact_counter = 1

        if i % chunk_size == 0 or i == len(numbers):
            vcf_filename = f"{base_name}_{file_counter}.vcf"
            vcf_path = os.path.join(tempfile.gettempdir(), vcf_filename)
            with open(vcf_path, 'w', encoding='utf-8') as f:
                f.write(vcf_content)
            vcf_files.append(vcf_path)
            vcf_content = ""
            file_counter += 1

    if len(vcf_files) > 500:
        zip_path = os.path.join(tempfile.gettempdir(), f"{base_name}_all.zip")
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

    context.user_data.clear()
    await update.message.reply_text("✅ Semua file berhasil dibuat dan dikirim!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operasi dibatalkan.")
    context.user_data.clear()
    return ConversationHandler.END

async def add_to_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Hanya owner yang bisa menambah whitelist.")
        return
    try:
        new_user_id = int(context.args[0])
        WHITELIST.add(new_user_id)
        save_whitelist(WHITELIST)
        await update.message.reply_text(f"✅ User ID {new_user_id} berhasil ditambahkan ke whitelist.")
    except:
        await update.message.reply_text("⚠️ Gunakan format: /adduser <id_telegram>")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"⚠️ ERROR: {context.error}")

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

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("adduser", add_to_whitelist))
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