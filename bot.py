
import os
import re
import asyncio
import tempfile
import zipfile
import phonenumbers
import gradio as gr
import threading
import nest_asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, ConversationHandler
)
from pymongo import MongoClient

# ===== Konstanta & DB =====
WAITING_FILENAME, WAITING_CONTACTNAME, WAITING_CHUNK_SIZE, WAITING_START_NUMBER, WAITING_INPUT_METHOD, WAITING_VCF_FILE, WAITING_VCF_OPTION = range(7)
OWNER_ID = 7238904265
bot_status = "✅ Bot Telegram aktif dan siap digunakan."
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://zeyndevv:zeyn123663@cluster0.vt3xi.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
client = MongoClient(MONGO_URI)
db = client["vcf_bot"]
whitelist_col = db["whitelist"]

# ===== Helper =====
def is_owner(user_id): return int(user_id) == OWNER_ID
def is_whitelisted(user_id): return whitelist_col.find_one({"user_id": int(user_id)}) or is_owner(user_id)
def add_to_whitelist_db(user_id: int): 
    if not is_whitelisted(user_id): whitelist_col.insert_one({"user_id": int(user_id)})
def remove_from_whitelist_db(user_id: int): whitelist_col.delete_one({"user_id": int(user_id)})
def is_valid_phone(number: str) -> bool:
    try:
        number = number.strip()
        if not number.startswith("+"): number = "+" + number
        parsed = phonenumbers.parse(number, None)
        return phonenumbers.is_valid_number(parsed)
    except phonenumbers.NumberParseException:
        return False

# ===== Fitur utama (potongan, tidak diubah) =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_whitelisted(user_id):
        await update.message.reply_text("🚫 Kamu tidak diizinkan menggunakan bot ini.\n🆔 ID kamu: `{}`".format(user_id), parse_mode="Markdown")
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
            await update.message.reply_text("⚠️ Format salah di bagian: {} | {}".format(parts[i], parts[i+1]))
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
        "📥 Sekarang kirim daftar nomor:\n\n"
        "1. Kirim *file .txt*\n"
        "2. Atau langsung ketik/forward di chat (1 nomor per baris).",
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
    document = update.message.document
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

async def process_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, numbers: list):
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

        name = "{} {}".format(current_name, contact_counter)
        vcf_entry = "BEGIN:VCARD\nVERSION:3.0\nFN:{}\nTEL;TYPE=CELL:{}\nEND:VCARD\n".format(name, number)
        vcf_content += vcf_entry
        contact_counter += 1
        remaining -= 1

        if remaining == 0 and current_name_idx + 1 < len(contact_plan):
            current_name_idx += 1
            current_name, remaining = contact_plan[current_name_idx]
            contact_counter = 1

        if i % chunk_size == 0 or i == len(numbers):
            vcf_filename = "{}_{}.vcf".format(base_name, file_counter)
            vcf_path = os.path.join(tempfile.gettempdir(), vcf_filename)
            with open(vcf_path, 'w', encoding='utf-8') as f:
                f.write(vcf_content)
            vcf_files.append(vcf_path)
            vcf_content = ""
            file_counter += 1

    for file in vcf_files:
        with open(file, 'rb') as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file))
        os.remove(file)
        await asyncio.sleep(1.5)

    context.user_data.clear()
    await update.message.reply_text("✅ Semua file berhasil dibuat dan dikirim!")
    return ConversationHandler.END

# === FITUR VCF TO TXT ===
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
    document = update.message.document
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
                        output_lines.append("{} - {}".format(name, phone))
                    else:
                        output_lines.append(phone)
                    name, phone = None, None

    os.remove(file_path)

    if not output_lines:
        await update.message.reply_text("❌ Tidak ditemukan data kontak dalam file.")
        return ConversationHandler.END

    txt_output = "\n".join(output_lines)
    txt_path = os.path.join(tempfile.gettempdir(), "converted.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(txt_output)

    with open(txt_path, 'rb') as f:
        await update.message.reply_document(document=f, filename="converted.txt")
    os.remove(txt_path)
    await update.message.reply_text("✅ File berhasil dikonversi!")
    return ConversationHandler.END

# === WHITELIST CONTROL ===
async def add_to_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Hanya owner yang bisa menambah whitelist.")
        return
    try:
        new_user_id = int(context.args[0])
        add_to_whitelist_db(new_user_id)
        await update.message.reply_text("✅ User ID {} berhasil ditambahkan ke whitelist.".format(new_user_id))
    except:
        await update.message.reply_text("⚠️ Gunakan format: /adduser <id_telegram>")

async def delete_from_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Hanya owner yang bisa menghapus whitelist.")
        return
    try:
        target_user_id = int(context.args[0])
        remove_from_whitelist_db(target_user_id)
        await update.message.reply_text("🗑️ User ID {} berhasil dihapus dari whitelist.".format(target_user_id))
    except:
        await update.message.reply_text("⚠️ Gunakan format: /deluser <id_telegram>")

async def check_user_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status = "🆔 ID kamu: `{}`\n👑 Owner: {}\n✅ Whitelisted: {}".format(
        user_id,
        "Ya" if is_owner(user_id) else "Tidak",
        "Ya" if is_whitelisted(user_id) else "Tidak"
    )
    await update.message.reply_text(status, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operasi dibatalkan.")
    context.user_data.clear()
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("⚠️ ERROR: {}".format(context.error))

# ===== Run Bot =====
async def run_bot():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN tidak ditemukan di environment variable.")
    app = ApplicationBuilder().token(TOKEN).build()

    from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler

    # Import handler fungsinya dari kode asli pengguna
    from bot_handlers import *

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

# ===== Main Runner =====
def start_gradio():
    gr.Interface(
        fn=lambda: bot_status,
        inputs=[],
        outputs="text",
        title="Status Bot Telegram",
        live=False,
        flagging_mode="never"
    ).launch(server_name="0.0.0.0", server_port=7860, share=False)

if __name__ == "__main__":
    nest_asyncio.apply()
    threading.Thread(target=start_gradio).start()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_bot())
