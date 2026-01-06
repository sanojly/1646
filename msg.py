# =========================================================
# LOFIBOT — Telegram → Instagram DM Sender
# SEND ONLY | Clean Commands | Linux VPS / WSL
# Compatible with msg.py (verbose engine)
# =========================================================

import os
import json
import time
import asyncio
import logging
from typing import Dict

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from playwright.async_api import async_playwright

# ===== MSG ENGINE =====
from msg import (
    parse_messages,
    send_loop,
    stop as stop_task,
    pause as pause_task,
    resume as resume_task,
    set_speed,
)

# =========================================================
# ENV / LOGGING
# =========================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_TG_ID", "0"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("LOFIBOT")

# =========================================================
# GLOBAL STATE
# =========================================================
RUNNING: Dict[int, Dict] = {}   # task_id -> runtime data
SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

# =========================================================
# PERMISSION
# =========================================================
def only_owner(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("❌ Not authorized")
            return
        return await func(update, context)
    return wrapper

# =========================================================
# PLAYWRIGHT HELPERS
# =========================================================
async def create_page(storage_state: dict):
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    context = await browser.new_context(
        storage_state=storage_state,
        user_agent=(
            "Mozilla/5.0 (Linux; Android 13) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/119.0.0.0 Mobile Safari/537.36"
        ),
        viewport={"width": 412, "height": 915},
        is_mobile=True,
        has_touch=True,
    )
    page = await context.new_page()
    return p, browser, context, page

async def destroy_page(p, browser, context):
    try:
        await context.close()
    except Exception:
        pass
    try:
        await browser.close()
    except Exception:
        pass
    try:
        await p.stop()
    except Exception:
        pass

# =========================================================
# IG LOGIN — USER/PASS
# =========================================================
LOGIN_URL = "https://www.instagram.com/accounts/login/"

@only_owner
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /login <username> <password>
    """
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /login <username> <password>")
        return

    user, pwd = context.args
    out_file = os.path.join(SESSIONS_DIR, "default_state.json")

    await update.message.reply_text("🔐 Logging in… browser will open")

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=False, args=["--no-sandbox"])
    ctx = await browser.new_context()
    page = await ctx.new_page()

    await page.goto(LOGIN_URL, timeout=60000)
    await page.wait_for_selector('input[name="username"]', timeout=30000)
    await page.fill('input[name="username"]', user)
    await page.fill('input[name="password"]', pwd)
    await page.click('button[type="submit"]')
    await page.wait_for_timeout(8000)

    if "challenge" in page.url or "two_factor" in page.url:
        await update.message.reply_text(
            "⚠️ OTP/Challenge detected.\n"
            "Complete it in the browser, then run /login again."
        )
    else:
        await ctx.storage_state(path=out_file)
        await update.message.reply_text("✅ Login successful. Session saved.")

    await ctx.close()
    await browser.close()
    await p.stop()

# =========================================================
# IG LOGIN — SESSION ID
# =========================================================
@only_owner
async def login_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /login_session <sessionid>
    """
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /login_session <sessionid>")
        return

    sessionid = context.args[0].strip()
    out_file = os.path.join(SESSIONS_DIR, "default_state.json")

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = await browser.new_context()

    await ctx.add_cookies([{
        "name": "sessionid",
        "value": sessionid,
        "domain": ".instagram.com",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax"
    }])

    page = await ctx.new_page()
    await page.goto("https://www.instagram.com/", timeout=60000)
    await page.wait_for_timeout(5000)

    if "login" in page.url:
        await update.message.reply_text("❌ Invalid sessionid")
    else:
        await ctx.storage_state(path=out_file)
        await update.message.reply_text("✅ SessionID login successful")

    await ctx.close()
    await browser.close()
    await p.stop()

# =========================================================
# COMMANDS — CORE
# =========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 LofiBot Online\n\n"
        "/login <user> <pass>\n"
        "/login_session <sessionid>\n\n"
        "/attack <ig_thread_url>\n"
        "(reply with text or .txt file)\n\n"
        "/pause <id>\n"
        "/resume <id>\n"
        "/stop <id>\n"
        "/speed <id> <delay>\n"
        "/tasks"
    )

@only_owner
async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /attack <ig_thread_url>\n"
            "Reply to text or .txt file"
        )
        return

    thread_url = context.args[0]

    # ===== SOURCE: TEXT or FILE =====
    if update.message.reply_to_message and update.message.reply_to_message.document:
        doc = update.message.reply_to_message.document
        if not doc.file_name.endswith(".txt"):
            await update.message.reply_text("❌ Only .txt file allowed")
            return
        file = await context.bot.get_file(doc.file_id)
        content = (await file.download_as_bytearray()).decode(
            "utf-8", errors="ignore"
        )
        messages = parse_messages(content)

    elif update.message.reply_to_message and update.message.reply_to_message.text:
        messages = parse_messages(update.message.reply_to_message.text)

    else:
        await update.message.reply_text("Reply with text or .txt file")
        return

    state_file = os.path.join(SESSIONS_DIR, "default_state.json")
    if not os.path.exists(state_file):
        await update.message.reply_text("❌ Login first")
        return

    storage_state = json.load(open(state_file))
    p, browser, ctx, page = await create_page(storage_state)

    task_id = int(time.time())
    task = asyncio.create_task(
        send_loop(task_id, page, thread_url, messages)
    )

    RUNNING[task_id] = {
        "task": task,
        "p": p,
        "browser": browser,
        "context": ctx,
        "status": "running",
        "started": time.strftime("%H:%M:%S"),
    }

    await update.message.reply_text(
        f"🚀 Attack started\nTask ID: `{task_id}`"
    )

@only_owner
async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /pause <task_id>")
        return
    tid = int(context.args[0])
    if tid not in RUNNING:
        await update.message.reply_text("Task not found")
        return
    pause_task(tid)
    RUNNING[tid]["status"] = "paused"
    await update.message.reply_text(f"⏸️ Paused: {tid}")

@only_owner
async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /resume <task_id>")
        return
    tid = int(context.args[0])
    if tid not in RUNNING:
        await update.message.reply_text("Task not found")
        return
    resume_task(tid)
    RUNNING[tid]["status"] = "running"
    await update.message.reply_text(f"▶️ Resumed: {tid}")

@only_owner
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /stop <task_id>")
        return
    tid = int(context.args[0])
    data = RUNNING.pop(tid, None)
    if not data:
        await update.message.reply_text("Task not found")
        return

    stop_task(tid)
    await data["task"]
    await destroy_page(data["p"], data["browser"], data["context"])
    await update.message.reply_text(f"🛑 Stopped: {tid}")

@only_owner
async def speed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /speed <task_id> <delay>")
        return
    tid = int(context.args[0])
    delay = float(context.args[1])
    if tid not in RUNNING:
        await update.message.reply_text("Task not found")
        return
    set_speed(tid, delay)
    await update.message.reply_text(f"⚡ Speed updated: {delay}s")

@only_owner
async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not RUNNING:
        await update.message.reply_text("No running tasks")
        return
    lines = ["📋 Active Tasks:"]
    for tid, d in RUNNING.items():
        lines.append(
            f"- {tid} | {d['status']} | since {d['started']}"
        )
    await update.message.reply_text("\n".join(lines))

# =========================================================
# MAIN
# =========================================================
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("login_session", login_session))
    app.add_handler(CommandHandler("attack", attack))
    app.add_handler(CommandHandler("pause", pause))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("speed", speed))
    app.add_handler(CommandHandler("tasks", tasks))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    log.info("LofiBot started")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
