import os
import re
import logging
import tempfile
import subprocess
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["BOT_TOKEN"]
IG_USER = os.environ.get("IG_USERNAME", "")
IG_PASS = os.environ.get("IG_PASSWORD", "")

# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_username(text: str):
    text = text.strip().rstrip("/")
    patterns = [
        r"instagram\.com/([A-Za-z0-9_.]+)",
        r"^@([A-Za-z0-9_.]+)$",
        r"^([A-Za-z0-9_.]{3,30})$",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            u = m.group(1)
            if u not in ("p", "reel", "reels", "stories", "explore", "accounts", "tv"):
                return u
    return None


def ydl_cookies_args():
    """Return yt-dlp auth args if credentials are set."""
    if IG_USER and IG_PASS:
        return ["--username", IG_USER, "--password", IG_PASS]
    return []


def choice_keyboard(username: str) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("🎬 Reels", callback_data=f"reels|{username}"),
            InlineKeyboardButton("🖼️ Photos", callback_data=f"photos|{username}"),
        ],
        [
            InlineKeyboardButton("📖 Stories", callback_data=f"stories|{username}"),
            InlineKeyboardButton("⭐ Stories à la une", callback_data=f"highlights|{username}"),
        ],
        [
            InlineKeyboardButton("📦 Tout télécharger", callback_data=f"all|{username}"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


async def send_files_in_dir(chat_id, context, tmpdir: str, caption: str):
    """Send all media files found in tmpdir."""
    files = sorted(
        [f for f in Path(tmpdir).rglob("*") if f.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png", ".webp")],
        key=lambda f: f.stat().st_size
    )
    if not files:
        await context.bot.send_message(chat_id, "❌ Aucun contenu trouvé (compte privé ou vide).")
        return 0

    count = 0
    for f in files:
        try:
            size_mb = f.stat().st_size / (1024 * 1024)
            if size_mb > 49:
                await context.bot.send_message(chat_id, f"⚠️ Fichier trop lourd ignoré : {f.name} ({size_mb:.1f} Mo)")
                continue
            if f.suffix.lower() == ".mp4":
                with open(f, "rb") as fh:
                    await context.bot.send_video(chat_id=chat_id, video=fh, caption=caption[:1024], supports_streaming=True)
            else:
                with open(f, "rb") as fh:
                    await context.bot.send_photo(chat_id=chat_id, photo=fh, caption=caption[:1024])
            count += 1
        except Exception as e:
            logger.error(f"Erreur envoi {f.name}: {e}")

    return count


def run_ytdlp(args: list) -> tuple[bool, str]:
    """Run yt-dlp and return (success, output)."""
    cmd = ["yt-dlp", "--no-warnings", "--quiet"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.returncode == 0, result.stderr


# ── Download functions ────────────────────────────────────────────────────────

async def download_reels(username, chat_id, context):
    await context.bot.send_message(chat_id, f"🎬 Téléchargement des Reels de @{username}…")
    with tempfile.TemporaryDirectory() as tmpdir:
        url = f"https://www.instagram.com/{username}/reels/"
        args = [
            url,
            "-o", f"{tmpdir}/%(id)s.%(ext)s",
            "--playlist-end", "20",
            "--format", "mp4",
            "--extractor-args", "instagram:player_url_template=https://www.instagram.com/",
        ] + ydl_cookies_args()
        ok, err = run_ytdlp(args)
        count = await send_files_in_dir(chat_id, context, tmpdir, f"🎬 Reel @{username}")
        if count > 0:
            await context.bot.send_message(chat_id, f"✅ {count} Reel(s) envoyé(s) !")
        elif not ok:
            await context.bot.send_message(chat_id, "❌ Impossible de récupérer les Reels.\nLe compte est peut-être privé.")


async def download_photos(username, chat_id, context):
    await context.bot.send_message(chat_id, f"🖼️ Téléchargement des Photos de @{username}…")
    with tempfile.TemporaryDirectory() as tmpdir:
        url = f"https://www.instagram.com/{username}/"
        args = [
            url,
            "-o", f"{tmpdir}/%(id)s.%(ext)s",
            "--playlist-end", "30",
            "--format", "jpg/best",
            "--match-filter", "!is_live",
        ] + ydl_cookies_args()
        ok, err = run_ytdlp(args)
        count = await send_files_in_dir(chat_id, context, tmpdir, f"🖼️ Photo @{username}")
        if count > 0:
            await context.bot.send_message(chat_id, f"✅ {count} photo(s) envoyée(s) !")
        elif not ok:
            await context.bot.send_message(chat_id, "❌ Impossible de récupérer les photos.\nLe compte est peut-être privé.")


async def download_stories(username, chat_id, context):
    if not (IG_USER and IG_PASS):
        await context.bot.send_message(
            chat_id,
            "⚠️ Les Stories nécessitent un compte Instagram.\n"
            "Ajoute IG_USERNAME et IG_PASSWORD dans Railway → Variables."
        )
        return
    await context.bot.send_message(chat_id, f"📖 Téléchargement des Stories de @{username}…")
    with tempfile.TemporaryDirectory() as tmpdir:
        url = f"https://www.instagram.com/stories/{username}/"
        args = [
            url,
            "-o", f"{tmpdir}/%(id)s.%(ext)s",
        ] + ydl_cookies_args()
        ok, err = run_ytdlp(args)
        count = await send_files_in_dir(chat_id, context, tmpdir, f"📖 Story @{username}")
        if count > 0:
            await context.bot.send_message(chat_id, f"✅ {count} story(ies) envoyée(s) !")
        else:
            await context.bot.send_message(chat_id, "❌ Aucune story active trouvée.")


async def download_highlights(username, chat_id, context):
    if not (IG_USER and IG_PASS):
        await context.bot.send_message(
            chat_id,
            "⚠️ Les Stories à la une nécessitent un compte Instagram.\n"
            "Ajoute IG_USERNAME et IG_PASSWORD dans Railway → Variables."
        )
        return
    await context.bot.send_message(chat_id, f"⭐ Téléchargement des Stories à la une de @{username}…")
    with tempfile.TemporaryDirectory() as tmpdir:
        url = f"https://www.instagram.com/{username}/highlights/"
        args = [
            url,
            "-o", f"{tmpdir}/%(id)s.%(ext)s",
        ] + ydl_cookies_args()
        ok, err = run_ytdlp(args)
        count = await send_files_in_dir(chat_id, context, tmpdir, f"⭐ Highlight @{username}")
        if count > 0:
            await context.bot.send_message(chat_id, f"✅ {count} média(s) envoyé(s) !")
        else:
            await context.bot.send_message(chat_id, "❌ Aucune story à la une trouvée.")


async def download_all(username, chat_id, context):
    await download_reels(username, chat_id, context)
    await download_photos(username, chat_id, context)
    await download_stories(username, chat_id, context)
    await download_highlights(username, chat_id, context)


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bonjour ! Je suis ton bot Instagram.\n\n"
        "📌 Envoie-moi un lien ou un pseudo :\n"
        "• https://www.instagram.com/nasa\n"
        "• @nasa\n"
        "• nasa\n\n"
        "Je te proposerai ensuite quoi télécharger 😊"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    username = extract_username(text)
    if not username:
        await update.message.reply_text(
            "❓ Lien non reconnu. Essaie :\n"
            "• https://www.instagram.com/nasa\n"
            "• @nasa"
        )
        return
    await update.message.reply_text(
        f"✅ Profil : @{username}\n\nQue veux-tu télécharger ?",
        reply_markup=choice_keyboard(username),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, username = query.data.split("|", 1)
    chat_id = query.effective_chat.id
    await query.edit_message_text(f"⏳ Téléchargement en cours pour @{username}…")

    dispatch = {
        "reels": download_reels,
        "photos": download_photos,
        "stories": download_stories,
        "highlights": download_highlights,
        "all": download_all,
    }
    if action in dispatch:
        await dispatch[action](username, chat_id, context)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("🚀 Bot Instagram démarré !")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
