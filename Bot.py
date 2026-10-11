import html
import secrets
import sqlite3
import string
from datetime import datetime
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta

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

BOT_TOKEN = "8811516722:AAEULsBWVF8HuqzPh77XGicj3nRPmRTiJG0"
BOT_USERNAME = "PrimeGC_Topup_Bot"
SUPPORT_USERNAME = "@PrimeGC_6"

# Admin handles without '@'
ADMIN_USERNAMES = {
    "primegc_6",
}

# Fallback numeric Telegram ID
ADMIN_CHAT_ID = 1123404836

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = "codes.db"

# ============================================================
# DATABASE UTILITIES
# ============================================================

def get_db_connection():
    """Create a thread-safe connection per operation."""
    conn = sqlite3.connect(DB_PATH)
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
        # Ensure index for quick lookups
        conn.execute("CREATE INDEX IF NOT EXISTS idx_codes_activated ON codes(activated);")
        conn.commit()


# ============================================================
# HELPERS
# ============================================================

def is_admin(user) -> bool:
    """Check if user has an admin username or matching admin chat ID."""
    if not user:
        return False
    if ADMIN_CHAT_ID and user.id == ADMIN_CHAT_ID:
        return True
    if not user.username:
        return False
    clean_username = user.username.lstrip("@").lower()
    return clean_username in {u.lstrip("@").lower() for u in ADMIN_USERNAMES}


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

    # Case 1: Plain /start without parameters
    if not context.args:
        if is_admin(user):
            with get_db_connection() as conn:
                total_codes = conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
                activated_codes = conn.execute(
                    "SELECT COUNT(*) FROM codes WHERE activated = 1"
                ).fetchone()[0]

            available_codes_count = total_codes - activated_codes

            await update.message.reply_text(
                "👋 <b>Admin Dashboard</b>\n\n"
                "📊 <b>Link Report:</b>\n"
                f"• Total Links: {total_codes}\n"
                f"• Activated: {activated_codes}\n"
                f"• Available: {available_codes_count}\n\n"
                "<b>Commands:</b>\n"
                "• /genlinks - Generate links with quantity\n"
                "• /available - View unused/available codes\n"
                "• /activated - View activated codes & user details",
                parse_mode="HTML"
            )
            return

        # Regular user landing page
        await update.message.reply_text(
            "👋 Welcome!\n\n"
            "This bot activates your Telegram Premium gifts purchased from Kinguin.\n"
            "Please click the activation link you received after purchase.\n\n"
            f"If you have any issues, contact {SUPPORT_USERNAME}"
        )
        return

    # Case 2: Link opened with code parameter
    code = context.args[0].strip().upper()

    if not is_admin(user) and not user.username:
        await update.message.reply_text(
            "⚠️ <b>Username Required!</b>\n\n"
            "To activate your Telegram Premium gift, you need to have a public Telegram username.\n\n"
            "Please go to your <b>Telegram Settings</b> ➡️ <b>Set a Username</b> (e.g., <code>@yourname</code>), and then click your activation link again!",
            parse_mode="HTML"
        )
        return

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

    username = get_user_display_name(user)
    activated_dt = datetime.now(IST)

    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM codes WHERE code = ?", (code,)).fetchone()
        if not row:
            await query.edit_message_text("❌ This code does not exist.")
            return

        if row["activated"]:
            await query.edit_message_text("⚠️ This code has already been claimed.")
            return

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
        "⏳ It will be processed and activated within a few hours.\n\n"
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
# /GENLINKS & STEPPED CALLBACKS
# ============================================================

async def genlinks(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await query.edit_message_text("❌ Session expired. Please use /genlinks again.")
        return

    codes_to_insert = []
    generated_links = []

    for _ in range(qty):
        code = generate_code()
        codes_to_insert.append((code, order_name, duration))
        link = f"https://t.me/{BOT_USERNAME}?start={code}"
        generated_links.append(link)

    with get_db_connection() as conn:
        conn.executemany(
            "INSERT INTO codes (code, order_name, duration_months) VALUES (?, ?, ?)",
            codes_to_insert,
        )
        conn.commit()

    links_text = "\n".join(generated_links)

    await query.edit_message_text(
        links_text,
        disable_web_page_preview=True
    )


# ============================================================
# /AVAILABLE (PAGINATED + GROUPED SUMMARY)
# ============================================================

async def available_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user):
        await update.message.reply_text("❌ You are not authorized.")
        return

    await send_available_page(update.message, 0, context, is_callback=False)


async def send_available_page(target, page: int, context: ContextTypes.DEFAULT_TYPE, is_callback: bool = False):
    PER_PAGE = 10
    offset = page * PER_PAGE

    with get_db_connection() as conn:
        total_count = conn.execute("SELECT COUNT(*) FROM codes WHERE activated = 0").fetchone()[0]

        summary_rows = conn.execute("""
            SELECT order_name, duration_months, COUNT(*) as count
            FROM codes WHERE activated = 0
            GROUP BY order_name, duration_months
            ORDER BY order_name, duration_months
        """).fetchall()

        rows = conn.execute(
            "SELECT * FROM codes WHERE activated = 0 ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (PER_PAGE, offset)
        ).fetchall()

    if total_count == 0:
        text = "🟢 No available codes found in stock."
        if is_callback:
            await target.edit_message_text(text)
        else:
            await target.reply_text(text)
        return

    lines = ["📊 <b>Stock Summary (Unused Codes):</b>"]
    for row in summary_rows:
        safe_order = html.escape(str(row['order_name']))
        lines.append(f"• <b>{safe_order} ({row['duration_months']}M):</b> {row['count']} available")

    total_pages = (total_count + PER_PAGE - 1) // PER_PAGE
    lines.append(f"\n📦 <b>Total Unused Stock:</b> {total_count}")
    lines.append("\n-----------------------------------")
    lines.append(f"🟢 <b>Available Codes (Page {page + 1} of {total_pages}):</b>\n")

    for row in rows:
        safe_order = html.escape(str(row['order_name']))
        link = f"https://t.me/{BOT_USERNAME}?start={row['code']}"
        lines.append(
            f"🔑 <code>{row['code']}</code> | {safe_order} ({row['duration_months']}M)\n"
            f"🔗 <a href=\"{link}\">{link}</a>\n"
        )

    keyboard = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"avail_page:{page - 1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"avail_page:{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    message_text = "\n".join(lines)

    if is_callback:
        await target.edit_message_text(message_text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await target.reply_text(message_text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)


async def available_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user):
        await query.edit_message_text("❌ You are not authorized.")
        return

    page = int(query.data.split(":", 1)[1])
    await send_available_page(query, page, context, is_callback=True)


# ============================================================
# /ACTIVATED COMMAND
# ============================================================

async def activated_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user):
        await update.message.reply_text("❌ You are not authorized.")
        return

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM codes WHERE activated = 1 ORDER BY rowid DESC LIMIT 50"
        ).fetchall()

    if not rows:
        await update.message.reply_text("⚠️ No activated codes found.")
        return

    lines = ["⚠️ <b>Activated Codes & User Details (Latest 50):</b>\n"]
    for row in rows:
        safe_order = html.escape(str(row['order_name']))
        safe_by = html.escape(str(row["activated_by"]))
        lines.append(
            f"🔑 <code>{row['code']}</code> | {safe_order} ({row['duration_months']}M)\n"
            f"👤 By: {safe_by} (ID: <code>{row['activated_user_id']}</code>)\n"
            f"🕒 At: {row['activated_at']}\n"
            f"📅 Expires: {row['expires_at']}\n"
        )

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

    application = Application.builder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("genlinks", genlinks))
    application.add_handler(CommandHandler("available", available_codes))
    application.add_handler(CommandHandler("activated", activated_codes))

    # Stepped Generation Callbacks
    application.add_handler(CallbackQueryHandler(order_selected, pattern=r"^order:"))
    application.add_handler(CallbackQueryHandler(duration_selected, pattern=r"^duration:"))
    application.add_handler(CallbackQueryHandler(quantity_selected, pattern=r"^qty:"))

    # Pagination Callback for Available Codes
    application.add_handler(CallbackQueryHandler(available_page_callback, pattern=r"^avail_page:"))

    # Stepped Activation Callbacks
    application.add_handler(CallbackQueryHandler(confirm_claim_callback, pattern=r"^confirm_claim:"))
    application.add_handler(CallbackQueryHandler(cancel_claim_callback, pattern=r"^cancel_claim$"))

    print("🤖 Bot is running...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
