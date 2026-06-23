
import os
import logging
import asyncio
import aiohttp
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import yt_dlp

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("8692092820:AAGC_xzQaK-RPulpjZja02GJ3edb7hMg3V0", "")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit for bots

TERABOX_DOMAINS = [
    "terabox.com", "teraboxapp.com", "1024tera.com",
    "teraboxlink.com", "freeterabox.com", "mirrobox.com",
    "nephobox.com", "4funbox.co", "tibibox.com"
]


def is_terabox_link(url: str) -> bool:
    return any(domain in url.lower() for domain in TERABOX_DOMAINS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to Terabox Video Bot!*\n\n"
        "📤 Just send me a *Terabox link* and I'll download and send the video directly to you!\n\n"
        "✅ *Supported domains:*\n"
        "• terabox.com\n"
        "• teraboxapp.com\n"
        "• 1024tera.com\n"
        "• freeterabox.com\n"
        "• And more Terabox mirrors!\n\n"
        "⚠️ *Note:* Videos up to 50MB are sent directly. Larger files get a stream link.",
        parse_mode=ParseMode.MARKDOWN
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use this bot:*\n\n"
        "1️⃣ Copy a Terabox video link\n"
        "2️⃣ Paste it here in the chat\n"
        "3️⃣ Wait for the bot to process and send the video\n\n"
        "💡 *Tips:*\n"
        "• Make sure the Terabox link is public/shared\n"
        "• Works with direct video links\n"
        "• Videos >50MB will receive a direct download link\n\n"
        "🔧 *Commands:*\n"
        "/start - Welcome message\n"
        "/help - This help message",
        parse_mode=ParseMode.MARKDOWN
    )


def extract_terabox_info(url: str):
    """Extract video info using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'format': 'best[ext=mp4]/best',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info


async def download_video(url: str, output_path: str) -> bool:
    """Download video using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best[ext=mp4][filesize<50M]/best[filesize<50M]/best',
        'outtmpl': output_path,
        'merge_output_format': 'mp4',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_terabox_link(url):
        await update.message.reply_text(
            "❌ This doesn't look like a Terabox link.\n\n"
            "Please send a valid Terabox URL (e.g., terabox.com, teraboxapp.com, etc.)"
        )
        return

    status_msg = await update.message.reply_text("⏳ *Processing your Terabox link...*", parse_mode=ParseMode.MARKDOWN)

    try:
        # Extract info
        await status_msg.edit_text("🔍 *Fetching video info...*", parse_mode=ParseMode.MARKDOWN)
        loop = asyncio.get_event_loop()

        try:
            info = await loop.run_in_executor(None, extract_terabox_info, url)
        except Exception as e:
            logger.error(f"Info extraction error: {e}")
            await status_msg.edit_text(
                "❌ *Failed to fetch video info.*\n\n"
                "Possible reasons:\n"
                "• Link is private or expired\n"
                "• File is not a video\n"
                "• Terabox server is down\n\n"
                f"Error: `{str(e)[:200]}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        title = info.get('title', 'video')
        filesize = info.get('filesize') or info.get('filesize_approx') or 0
        duration = info.get('duration', 0)
        direct_url = info.get('url', '')
        ext = info.get('ext', 'mp4')

        # Format file size
        size_mb = filesize / (1024 * 1024) if filesize else 0
        size_str = f"{size_mb:.1f} MB" if size_mb > 0 else "Unknown"
        duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "Unknown"

        info_text = (
            f"📹 *{title[:50]}*\n"
            f"📦 Size: `{size_str}`\n"
            f"⏱ Duration: `{duration_str}`\n"
        )

        if filesize and filesize > MAX_FILE_SIZE:
            # File too large, send direct link
            keyboard = [[InlineKeyboardButton("⬇️ Direct Download", url=direct_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_msg.edit_text(
                info_text +
                f"\n⚠️ *File is too large ({size_str}) to send directly via Telegram.*\n"
                "Click below to download directly:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return

        # Download and send
        await status_msg.edit_text(
            info_text + "\n⬇️ *Downloading video...*",
            parse_mode=ParseMode.MARKDOWN
        )

        output_path = f"/tmp/{update.message.message_id}_{title[:20]}.%(ext)s"
        actual_path = f"/tmp/{update.message.message_id}_{title[:20]}.mp4"

        # Use sync download in executor
        def sync_download(u, p):
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best[ext=mp4][filesize<50M]/best[filesize<50M]/best',
                'outtmpl': p,
                'merge_output_format': 'mp4',
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([u])
                return True
            except Exception as e:
                logger.error(f"Sync download error: {e}")
                return False

        dl_success = await loop.run_in_executor(None, sync_download, url, output_path)

        # Find the actual downloaded file
        import glob
        files = glob.glob(f"/tmp/{update.message.message_id}_{title[:20]}.*")
        if not files or not dl_success:
            # Fallback: send direct link
            keyboard = [[InlineKeyboardButton("⬇️ Direct Download", url=direct_url)]] if direct_url else []
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            await status_msg.edit_text(
                "❌ *Download failed.*\n\nTry the direct link below:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return

        file_path = files[0]
        file_size = os.path.getsize(file_path)

        if file_size > MAX_FILE_SIZE:
            os.remove(file_path)
            keyboard = [[InlineKeyboardButton("⬇️ Direct Download", url=direct_url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_msg.edit_text(
                info_text +
                f"\n⚠️ *Downloaded file is too large to send via Telegram.*\n"
                "Use the direct link below:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return

        await status_msg.edit_text(
            info_text + "\n📤 *Uploading to Telegram...*",
            parse_mode=ParseMode.MARKDOWN
        )

        with open(file_path, 'rb') as video_file:
            await update.message.reply_video(
                video=video_file,
                caption=f"🎬 *{title[:100]}*\n\n📦 `{file_size / 1024 / 1024:.1f} MB`",
                parse_mode=ParseMode.MARKDOWN,
                supports_streaming=True,
                read_timeout=300,
                write_timeout=300
            )

        await status_msg.delete()
        os.remove(file_path)

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ *An unexpected error occurred.*\n\n`{str(e)[:300]}`",
            parse_mode=ParseMode.MARKDOWN
        )


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
      
