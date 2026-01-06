# =========================================================
# LOFIBOT — FINAL BUILD
# Telegram → Instagram DM Sender
# ENV auto-load | Ultra speed | Clean commands
# =========================================================

import os
import json
import time
import asyncio
import logging
from typing import Dict

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright

from msg import (
    parse_messages,
    send_loop,
    stop as stop_task,
    pause,
    resume,
    set_speed,
)

# =========================================================
# ENV AUTO LOAD (IMPORTANT)
# =========================================================
load_dotenv()   # <-- .env automatically loaded from same folder

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_TG_ID")

if not BOT_TOKEN or not OWNER_ID:
    raise RuntimeError(
        "ENV ERROR: BOT_TOKEN or OWNER_TG_ID missing.\n"
        "Check your .env file."
    )

OWNER_ID = int(OWNER_ID)

# =========================================================
# LOGGING
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("LOFIBOT")

# =========================================================
# GLOBAL STATE
# =========================================================
RUNNING: Dict[int, Dict] = {}
SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

# =========================================================
# PERMISSION
# =========================================================
def only_owner(fn):
    async def wrap(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            return
        return await fn(update, context)
    return wrap

# =========================================================
# PLAYWRIGHT HELPERS
# =========================================================
async def create_page(storage_state):
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    ctx = await browser.new_context(
        storage_state=storage_state,
        user_agent="Mozilla/5.0 (Linux; Android 13) Chrome/119 Mobile",
        viewport={"width": 412, "height": 915},
        is_mobile=True,
        has_touch=True,
    )
    page = await ctx.new_page()
    return p, browser, ctx, page

async def destroy(p, browser, ctx):
    try: await ctx.close()
    except: pass
    try: await browser.close()
    except: pass
    try: await p.stop()
    except: pass

# =========================================================
# COMMANDS
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 LofiBot Online\n"
        "Use /help to see commands."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 *LofiBot Help*\n\n"
        "*Login*\n"
        "/login <user> <pass>\n"
        "/login_session <sessionid>\n\n"
        "*Send*\n"
        "/attack <ig_thread_url>\n"
        "↳ reply with text or .txt file\n\n"
        "*Control*\n"
        "/pause <id>\n"
        "/resume <id>\n"
        "/stop <id>\n"
        "/speed <id> <delay>\n\n"
        "*Info*\n"
        "/tasks",
        parse_mode="Markdown"
    )

# -------------------------
# IG LOGIN (USER/PASS)
# -------------------------
@only_owner
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /login <username> <password>")
        return

    user, pwd = context.args
    out = os.path.join(SESSIONS_DIR, "default_state.json")

    await update.message.reply_text("🔐 Logging in… browser will open")

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
    ctx = await browser.new_context()
    page = await ctx.new_page()

    await page.goto("https://www.instagram.com/accounts/login/", timeout=60000)
    await page.fill('input[name="username"]', user)
    await page.fill('input[name="password"]', pwd)
    await page.click('button[type="submit"]')
    await page.wait_for_timeout(8000)

    await ctx.storage_state(path=out)
    await update.message.reply_text("✅ Login successful. Session saved.")

    await destroy(p, browser, ctx)

# -------------------------
# IG LOGIN (SESSION ID)
# -------------------------
@only_owner
async def login_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /login_session <sessionid>")
        return

    sid = context.args[0]
    out = os.path.join(SESSIONS_DIR, "default_state.json")

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = await browser.new_context()

    await ctx.add_cookies([{
        "name": "sessionid",
        "value": sid,
        "domain": ".instagram.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
    }])

    page = await ctx.new_page()
    await page.goto("https://www.instagram.com/", timeout=60000)
    await ctx.storage_state(path=out)

    await update.message.reply_text("✅ Session login saved.")
    await destroy(p, browser, ctx)

# -------------------------
# ATTACK
# -------------------------
@only_owner
async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not update.message.reply_to_message:
        await update.message.reply_text(
            "Usage: /attack <ig_thread_url>\nReply with text or .txt file"
        )
        return

    thread = context.args[0]

    if update.message.reply_to_message.document:
        doc = update.message.reply_to_message.document
        file = await context.bot.get_file(doc.file_id)
        text = (await file.download_as_bytearray()).decode("utf-8", "ignore")
    else:
        text = update.message.reply_to_message.text

    messages = parse_messages(text)

    state_path = os.path.join(SESSIONS_DIR, "default_state.json")
    if not os.path.exists(state_path):
        await update.message.reply_text("❌ Login first")
        return

    storage = json.load(open(state_path))
    p, b, c, page = await create_page(storage)

    tid = int(time.time())
    task = asyncio.create_task(send_loop(tid, pa
