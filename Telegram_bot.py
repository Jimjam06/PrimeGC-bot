import html
import os
import secrets
import sqlite3
import string
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta

# Try importing turso_serverless for cloud SQLite support
try:
    import turso_serverless
    TURSO_AVAILABLE = True
except ImportError:
    TURSO_AVAILABLE = False

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = "8811516722:AAFT9OCvvRpd5TpKMt3fAOGPpCk2vsFV6q0"
BOT_USERNAME = "PrimeGC_Topup_Bot"
SUPPORT_USERNAME = "@PrimeGC_6"

ADMIN_USER_IDS = {
    1123404836,
}

ADMIN_CHAT_ID = None

IST = ZoneInfo("Asia/Kolkata")

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
DB_PATH = "codes.db"


# ============================================================
# RENDER DUMMY HTTP SERVER (Fixes Port Binding Error)
# ============================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

    def log_message(self, format, *args):
        return

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"🌐 HTTP health-check server listening on port {port}")
    httpd.serve_forever()


# ============================================================
# DATABASE UTILITIES (Cloud & Local Support)
# ============================================================

def get_db_connection():
    if TURSO_AVAILABLE and TURSO_URL:
        return turso_serverless.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    with get_db_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            order_name TEXT NOT NULL,
            duration_months INTEGER NOT NULL,
            activated INTEGER DEFAULT 0,
            activated_by TEXT,
            activated_user_id INTEGER,
            activated_at TEXT,
            expires_at TEXT
        )
        """)
        conn.commit()


# ============================================================
# HELPERS
# ============================================================

def is_admin(user) -> bool:
    if not user:
        return False
    if ADMIN_CHAT_ID and user.id == ADMIN_CHAT_ID:
        return True
    return user.id in ADMIN_USER_IDS


def get_user_display_name(user) -> str:
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)


def generate_code(length: int = 10) -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "KNG-" + "".join(secrets.choice(chars) for _ in range(length))
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM codes WHERE code = ?", (code,)
            ).fetchone()
            if not row:
                return code


def format_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S IST")


# ============================================================
# /START HANDLER
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_CHAT_ID
    user = update.effective_user
    if not update.message or not user:
        return

    if is_admin(user) and not ADMIN_CHAT_ID:
        ADMIN_CHAT_ID = update.effective_chat.id

    if not context.args:
        if is_admin(user):
            with get_db_connection() as conn:
                total_codes = conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
                activated_codes = conn.execute(
                    "SELECT COUNT(*) FROM codes WHERE activated = 1"
                ).fetchone()[0]

            available_codes = total_codes - activated_codes

            await update.message.reply_text(
                "👋 <b>Admin Dashboard</b>\n\n"
                "📊 <b>Link Report:</b>\n"
                f"• Total Links: {total_codes}\n"
                f"• Activated: {activated_codes}\n"
                f"• Available: {available_codes}\n\n"
                "<b>Commands:</b>\n"
                "• /generate - Generate links with quantity\n"
                "• /codes - View all generated codes",
                parse_mode="HTML"
            )
            return

        await update.message.reply_text(
            "👋 Welcome!\n\n"
            "This bot activates your Telegram Premium gifts purchased from Kinguin.\n"
            "Please click the activation link you received after purchase.\n\n"
            f"If you have any issues, contact {SUPPORT_USERNAME}"
        )
        return

    code = context.args[0].strip().upper()

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM codes WHERE code = ?", (code,)
        ).fetchone()

    if not row:
        await update.message.reply_text(
            "❌ Invalid or expired code.\n\n"
            f"If you believe this is an error, please contact support: {SUPPORT_USERNAME}"
        )
        return

    if row["activated"]:
        safe_order = html.escape(str(row['order_name']))
        safe_activated_by = html.escape(str(row['activated_by']))
        await update.message.reply_text(
            "⚠️ <b>This code has already been activated.</b>\n"
            f"📦 Order: {safe_order}\n"
            f"👤 Activated by: {safe_activated_by}\n"
            f"🕒 Activated at: {row['activated_at']}\n"
            f"📅 Expire at: {row['expires_at']}\n\n"
            f"If you believe this is an error, please contact support: {SUPPORT_USERNAME}",
            parse_mode="HTML"
        )
        return

    keyboard = [
        [InlineKeyboardButton("✅ Confirm & Activate Now", callback_data=f"confirm_claim:{code}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_claim")]
    ]

    safe_order_name = html.escape(str(row["order_name"]))
    safe_user_name = html.escape(get_user_display_name(user))

    await update.message.reply_text(
        f"🎁 <b>Telegram Premium Gift Found!</b>\n\n"
        f"📦 <b>Source:</b> {safe_order_name}\n"
        f"⏳ <b>Duration:</b> {row['duration_months']} Months\n"
        f"👤 <b>Target Account:</b> {safe_user_name}\n\n"
        "Click the button below to confirm and activate this gift on your current account:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


# ============================================================
# CLAIM CALLBACKS
# ============================================================

async def confirm_claim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    code = query.data.split(":", 1)[1]

    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM codes WHERE code = ?", (code,)).fetchone()

        if not row:
            await query.edit_message_text("❌ This code does not exist.")
            return

        if row["activated"]:
            await query.edit_message_text("⚠️ This code has already been claimed.")
            return

        username = get_user_display_name(user)
        activated_dt = datetime.now(IST)
        expires_dt = activated_dt + relativedelta(months=row["duration_months"])

        activated_time = format_time(activated_dt)
        expires_time = format_time(expires_dt)

        cursor = conn.execute("""
            UPDATE codes
            SET activated = 1,
                activated_by = ?,
                activated_user_id = ?,
                activated_at = ?,
                expires_at = ?
            WHERE code = ? AND activated = 0
        """, (username, user.id, activated_time, expires_time, code))
        conn.commit()

        if cursor.rowcount == 0:
            await query.edit_message_text("⚠️ This code was just claimed by another session.")
            return

    months_label = f"{row['duration_months']} months"

    await query.edit_message_text(
        f"✅ <b>Activation Successful!</b>\n\n"
        f"Your Telegram Premium ({months_label}) request has been received.\n\n"
        "⏳ It will be processed and activated within a few hours (working in GMT+8 timezone).\n\n"
        f"If you have any questions, please contact {SUPPORT_USERNAME}",
        parse_mode="HTML"
    )

    if ADMIN_CHAT_ID:
        safe_username = html.escape(username)
        safe_order = html.escape(row["order_name"])
        admin_alert = (
            "🔔 <b>New Link Activated!</b>\n\n"
            f"🔑 <b>Code:</b> <code>{code}</code>\n"
            f"📦 <b>Order:</b> {safe_order}\n"
            f"⏳ <b>Duration:</b> {months_label}\n"
            f"👤 <b>Activated by:</b> {safe_username} (ID: <code>{user.id}</code>)\n"
            f"🕒 <b>Date & Time:</b> {activated_time}"
        )
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_alert,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Failed to alert admin: {e}")


async def cancel_claim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Activation cancelled. Your code has not been used.")


# ============================================================
# /GENERATE & STEPPED CALLBACKS
# ============================================================

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_CHAT_ID
    user = update.effective_user
    if not is_admin(user):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not ADMIN_CHAT_ID:
        ADMIN_CHAT_ID = update.effective_chat.id

    keyboard = [
        [
            InlineKeyboardButton("📦 Kinguin", callback_data="order:Kinguin"),
            InlineKeyboardButton("📦 BSV", callback_data="order:BSV"),
            InlineKeyboardButton("📦 G2A", callback_data="order:G2A"),
        ]
    ]

    await update.message.reply_text(
        "📦 Select the order source:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def order_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user):
        await query.edit_message_text("❌ You are not authorized.")
        return

    order_name = query.data.split(":", 1)[1]
    context.user_data["selected_order"] = order_name

    keyboard = [
        [
            InlineKeyboardButton("3 Months", callback_data="duration:3"),
            InlineKeyboardButton("6 Months", callback_data="duration:6"),
            InlineKeyboardButton("12 Months", callback_data="duration:12"),
        ]
    ]

    await query.edit_message_text(
        f"📦 Order: {order_name}\n\n⏳ Select duration:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def duration_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user):
        await query.edit_message_text("❌ You are not authorized.")
        return

    duration = int(query.data.split(":", 1)[1])
    context.user_data["selected_duration"] = duration
    order_name = context.user_data.get("selected_order", "N/A")

    keyboard = [
        [
            InlineKeyboardButton("1x", callback_data="qty:1"),
            InlineKeyboardButton("3x", callback_data="qty:3"),
            InlineKeyboardButton("5x", callback_data="qty:5"),
            InlineKeyboardButton("10x", callback_data="qty:10"),
        ]
    ]

    await query.edit_message_text(
        f"📦 Order: {order_name}\n"
        f"⏳ Duration: {duration} Months\n\n"
        "🔢 Select quantity to generate:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def quantity_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user):
        await query.edit_message_text("❌ You are not authorized.")
        return

    qty = int(query.data.split(":", 1)[1])
    order_name = context.user_data.pop("selected_order", None)
    duration = context.user_data.pop("selected_duration", None)

    if not order_name or not duration:
        await query.edit_message_text("❌ Session expired. Please use /generate again.")
        return

    codes_to_insert = []
    generated_links = []

    for _ in range(qty):
        code = generate_code()
        codes_to_insert.append((code, order_name, duration))
        link = f"https://t.me/{BOT_USERNAME}?start={code}"
        generated_links.append(f"• <code>{code}</code>\n<a href=\"{link}\">{link}</a>")

    with get_db_connection() as conn:
        conn.executemany(
            "INSERT INTO codes (code, order_name, duration_months) VALUES (?, ?, ?)",
            codes_to_insert,
        )
        conn.commit()

    links_text = "\n\n".join(generated_links)

    full_text = (
        f"✅ <b>Generated {qty} link(s)!</b>\n\n"
        f"📦 <b>Order:</b> {html.escape(order_name)}\n"
        f"⏳ <b>Duration:</b> {duration} Months\n\n"
        f"{links_text}"
    )

    if len(full_text) > 4000:
        await query.edit_message_text(f"✅ Generated {qty} link(s) successfully! Sending details...", parse_mode="HTML")
        current_chunk = []
        current_length = 0
        for link_line in generated_links:
            if current_length + len(link_line) + 2 > 4000:
                await query.message.reply_text("\n\n".join(current_chunk), parse_mode="HTML", disable_web_page_preview=True)
                current_chunk = [link_line]
                current_length = len(link_line)
            else:
                current_chunk.append(link_line)
                current_length += len(link_line) + 2
        if current_chunk:
            await query.message.reply_text("\n\n".join(current_chunk), parse_mode="HTML", disable_web_page_preview=True)
    else:
        await query.edit_message_text(full_text, parse_mode="HTML", disable_web_page_preview=True)


# ============================================================
# /CODES
# ============================================================

async def codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user):
        await update.message.reply_text("❌ You are not authorized.")
        return

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM codes ORDER BY rowid DESC"
        ).fetchall()

    if not rows:
        await update.message.reply_text("📋 No codes have been generated yet.")
        return

    lines = ["📋 <b>All Activation Codes:</b>\n"]
    for row in rows:
        status = "⚠️ Activated" if row["activated"] else "🟢 Available"
        safe_order = html.escape(str(row['order_name']))
        line = f"🔑 <code>{row['code']}</code> | {safe_order} ({row['duration_months']}M) - {status}"
        if row["activated"]:
            safe_by = html.escape(str(row["activated_by"]))
            line += f"\n    └ By: {safe_by} on {row['activated_at']}"
        lines.append(line)

    current_chunk = []
    current_length = 0
    for line in lines:
        if current_length + len(line) + 1 > 4000:
            await update.message.reply_text("\n".join(current_chunk), parse_mode="HTML")
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += len(line) + 1

    if current_chunk:
        await update.message.reply_text("\n".join(current_chunk), parse_mode="HTML")


# ============================================================
# MAIN
# ============================================================

def main():
    init_db()

    server_thread = threading.Thread(target=run_http_server, daemon=True)
    server_thread.start()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("generate", generate))
    application.add_handler(CommandHandler("codes", codes))

    application.add_handler(CallbackQueryHandler(order_selected, pattern=r"^order:"))
    application.add_handler(CallbackQueryHandler(duration_selected, pattern=r"^duration:"))
    application.add_handler(CallbackQueryHandler(quantity_selected, pattern=r"^qty:"))

    application.add_handler(CallbackQueryHandler(confirm_claim_callback, pattern=r"^confirm_claim:"))
    application.add_handler(CallbackQueryHandler(cancel_claim_callback, pattern=r"^cancel_claim$"))

    print("🤖 Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
