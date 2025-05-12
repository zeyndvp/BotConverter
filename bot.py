import gradio as gr
import threading
from flask import Flask
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import os

# Membuat instance Flask untuk halaman status
app = Flask(__name__)

# Variabel status bot
bot_status = "Aktif"

@app.route('/')
def index():
    return f"Bot Status: {bot_status}"

# Fungsi Flask untuk menjalankan server
def run_flask():
    app.run(host="0.0.0.0", port=7860)

# States
WAITING_FILENAME, WAITING_CONTACTNAME, WAITING_CHUNK_SIZE, WAITING_START_NUMBER, WAITING_FILE = range(5)

user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_status
    bot_status = "Aktif"  # Update status bot
    await update.message.reply_text("📝 Masukkan *nama dasar file VCF* (tanpa .vcf):", parse_mode="Markdown")
    return WAITING_FILENAME

# Handler lainnya tetap sama ...

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_status
    bot_status = "Off"  # Update status bot
    await update.message.reply_text("❌ Operasi dibatalkan.")
    return ConversationHandler.END

# Menjalankan bot Telegram
def run_bot():
    TOKEN = "8022523573:AAEP41EIKN5svqqqJafV7g7lfPN3PRk7Cyg"
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
    print("🤖 Bot sedang berjalan...")
    app.run_polling()

# Menambahkan Gradio untuk antarmuka pengguna
def create_gradio_interface():
    with gr.Blocks() as demo:
        gr.Markdown("## Status Bot Telegram")
        status_output = gr.Textbox(value="Bot Status: Aktif", label="Status Bot", interactive=False)
        gr.Button("Check Status").click(lambda: bot_status, outputs=status_output)
    
    demo.launch(server_name="0.0.0.0", server_port=7860)

if __name__ == '__main__':
    # Jalankan Flask di thread terpisah
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Jalankan Telegram bot di thread lain
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Jalankan Gradio untuk halaman status
    create_gradio_interface()
