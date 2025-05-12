import os
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)
import gradio as gr
from threading import Thread

# ===== Konfigurasi Token dan Status Bot =====
TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")  # Ganti dengan token kamu atau set di HuggingFace Secrets
bot_status = "✅ Bot aktif dan siap digunakan."

# ===== Fungsi Handler Telegram =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo! Bot Telegram berhasil dijalankan di Hugging Face Spaces.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Kamu berkata: {update.message.text}")

# ===== Fungsi Status untuk Gradio =====
def status_check():
    return bot_status

# ===== Fungsi Gradio =====
def create_gradio_interface():
    iface = gr.Interface(
        fn=status_check,
        inputs=[],
        outputs="text",
        title="Status Bot Telegram",
        allow_flagging="never"  # Hindari error write ke 'flagged'
    )
    iface.launch(server_name="0.0.0.0", server_port=7860)

# ===== Fungsi Bot Telegram =====
async def run_bot():
    if TOKEN == "YOUR_TOKEN_HERE":
        print("⚠️ Harap set environment variable BOT_TOKEN.")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("🤖 Bot Telegram berjalan...")
    await app.run_polling()

# ===== Main =====
if __name__ == "__main__":
    # Jalankan Gradio di thread terpisah
    Thread(target=create_gradio_interface).start()

    # Jalankan Bot Telegram di event loop yang sama
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    loop.run_forever()
