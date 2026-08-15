import os
import re
import json
import time
import hmac
import html
import base64
import random
import string
import hashlib
import sqlite3
import logging
import tempfile
import threading
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import telebot
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
)
from telebot.storage import StateMemoryStorage
from telebot.handler_backends import State, StatesGroup
from telebot.custom_filters import StateFilter, SimpleCustomFilter
from telebot.apihelper import ApiTelegramException

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION & INITIALIZATION
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# CHANNELS & GROUP LINKS
CHANNEL_1_USERNAME = "@leakmethodfree" 
CHANNEL_2_USERNAME = "@sabkijayhokhush" 
GROUP_LINK = "https://t.me/findyourskills" 

BOT_TOKEN = "8917517848:AAGeUBgYmKSPzirbFHKKNZ49MPwZ_IHZBJc"
ADMIN_IDS = [6860106371]

PRODUCT_CODE = "8902102126232"
MASTER_KEY = "660395654"
BASE_URL = "https://www.ujalahappiestonam.com/api/users"
DB_FILE = "ujala_pro_railway.db"

REFERRAL_TARGET = 25

state_storage = StateMemoryStorage()
bot = telebot.TeleBot(BOT_TOKEN, state_storage=state_storage)

# ═══════════════════════════════════════════════════════════════
# PREMIUM UI MENU BUTTONS
# ═══════════════════════════════════════════════════════════════
BTN_PREMIUM_VOUCHER = "🛍 Premium Voucher"
BTN_MY_ORDERS = "🛍 My orders"
BTN_VIP_PROFILE = "👑 VIP Profile"
BTN_ACCOUNT_WALLET = "💰 Account Wallet"
BTN_REFERRED_BONUS = "🎁 Referred Bonus"
BTN_HOW_TO_USE = "📝 How to use"
BTN_SUPPORT = "📞 Support"

MENU_BUTTONS = [
    BTN_PREMIUM_VOUCHER, BTN_MY_ORDERS, BTN_VIP_PROFILE, 
    BTN_ACCOUNT_WALLET, BTN_REFERRED_BONUS, BTN_HOW_TO_USE, BTN_SUPPORT,
    "/cancel", "/start", "/menu", "/admin"
]

def get_premium_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(BTN_PREMIUM_VOUCHER))
    markup.row(KeyboardButton(BTN_MY_ORDERS), KeyboardButton(BTN_VIP_PROFILE))
    markup.row(KeyboardButton(BTN_ACCOUNT_WALLET), KeyboardButton(BTN_REFERRED_BONUS))
    markup.row(KeyboardButton(BTN_HOW_TO_USE), KeyboardButton(BTN_SUPPORT))
    return markup

def force_join_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 Join Channel 1", url=f"https://t.me/{CHANNEL_1_USERNAME.replace('@', '')}"))
    markup.add(InlineKeyboardButton("📢 Join Channel 2", url=f"https://t.me/{CHANNEL_2_USERNAME.replace('@', '')}"))
    markup.add(InlineKeyboardButton("💬 Join Discussion Group", url=GROUP_LINK))
    markup.add(InlineKeyboardButton("✅ I Have Joined", callback_data="check_join"))
    return markup

def check_force_join(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    
    for channel in [CHANNEL_1_USERNAME, CHANNEL_2_USERNAME]:
        try:
            status = bot.get_chat_member(channel, user_id).status
            if status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.error(f"Force join error on {channel}: {e}")
            # YAHAN FIX KIYA GAYA HAI: Ab error aane par sidha block hoga
            return False 
    return True

# ═══════════════════════════════════════════════════════════════
# DATABASE & REFERRAL ENGINE WITH PENALTY SYSTEM
# ═══════════════════════════════════════════════════════════════
def init_db():
    with sqlite3.connect(DB_FILE, timeout=30) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            joined_at TIMESTAMP,
            referred_by INTEGER,
            coins INTEGER DEFAULT 1,
            referral_count INTEGER DEFAULT 0,
            bonus_5_received BOOLEAN DEFAULT 0
        )''')

def get_all_users() -> List[int]:
    try:
        with sqlite3.connect(DB_FILE, timeout=30) as conn:
            return [row[0] for row in conn.execute("SELECT user_id FROM users").fetchall()]
    except Exception: return []

def track_user(user_id: int, first_name: str, referred_by: int = None):
    try:
        with sqlite3.connect(DB_FILE, timeout=30) as conn:
            cursor = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            if not cursor.fetchone():
                conn.execute("INSERT INTO users (user_id, first_name, joined_at, referred_by, coins) VALUES (?, ?, ?, ?, 1)", 
                             (user_id, first_name, datetime.now().isoformat(), referred_by))
                
                if referred_by and referred_by != user_id:
                    conn.execute("UPDATE users SET coins = coins + 1, referral_count = referral_count + 1 WHERE user_id = ?", (referred_by,))
                    
                    c2 = conn.execute("SELECT referral_count, bonus_5_received FROM users WHERE user_id = ?", (referred_by,))
                    row = c2.fetchone()
                    if row and row[0] >= 5 and not row[1]:
                        conn.execute("UPDATE users SET coins = coins + 1, bonus_5_received = 1 WHERE user_id = ?", (referred_by,))
                        safe_send_message(referred_by, "🎉 <b>BONUS UNLOCKED!</b>\nAapne 5 doston ko invite kiya! Aapko +1 Bonus Coin mila hai.", parse_mode="HTML")
                    
                    safe_send_message(referred_by, f"🔔 <b>New Referral!</b>\n{first_name} ne aapke link se join kiya. Aapko +1 Coin mila!", parse_mode="HTML")
                    notify_admin(f"👤 <b>New Referral Alert</b>\nReferrer: <code>{referred_by}</code>\nReferred: <code>{user_id}</code> ({first_name})")
    except Exception as e:
        logger.error(f"DB Error: {e}")

def get_user_stats(user_id: int):
    try:
        with sqlite3.connect(DB_FILE, timeout=30) as conn:
            cursor = conn.execute("SELECT coins, referral_count FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return {"coins": row[0], "referrals": row[1]}
    except Exception: pass
    return {"coins": 0, "referrals": 0}

def deduct_coin(user_id: int):
    try:
        with sqlite3.connect(DB_FILE, timeout=30) as conn:
            conn.execute("UPDATE users SET coins = coins - 1 WHERE user_id = ? AND coins > 0", (user_id,))
    except Exception: pass

def handle_penalty(user_id: int):
    try:
        with sqlite3.connect(DB_FILE, timeout=30) as conn:
            c = conn.execute("SELECT joined_at, referred_by, first_name FROM users WHERE user_id=?", (user_id,))
            row = c.fetchone()
            if row:
                joined_at, referred_by, fname = datetime.fromisoformat(row[0]), row[1], row[2]
                if (datetime.now() - joined_at).total_seconds() < 3 * 3600:
                    conn.execute("UPDATE users SET coins = coins - 10 WHERE user_id=?", (user_id,))
                    if referred_by:
                        conn.execute("UPDATE users SET coins = coins - 10 WHERE user_id=?", (referred_by,))
                        warn_msg = (
                            "🚨 <b>ANTI-FRAUD PENALTY ALERT!</b> 🚨\n\n"
                            f"Aapke referral <b>{fname}</b> ne 3 ghante se pehle bot leave kar diya ya block kar diya.\n"
                            "As a penalty, aapke account se <b>10 Coins</b> deduct kar liye gaye hain!"
                        )
                        safe_send_message(referred_by, warn_msg, parse_mode="HTML")
                        notify_admin(f"🚨 <b>Penalty Applied</b>\nUser: {fname} ({user_id}) left < 3 hrs.\nReferrer: {referred_by}\nPenalty: -10 coins to both.")
    except Exception as e:
        logger.error(f"Penalty Error: {e}")

# ═══════════════════════════════════════════════════════════════
# UJALA AUTOMATION ENGINE & ANTI-BAN
# ═══════════════════════════════════════════════════════════════
DUMMY_JPEG = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xd2\xcf\x20\xff\xd9'

def get_pack_image_path() -> str:
    tmp_path = os.path.join(tempfile.gettempdir(), "ujala_pack_pro.jpg")
    if not os.path.exists(tmp_path):
        with open(tmp_path, "wb") as f:
            f.write(DUMMY_JPEG)
    return tmp_path

def get_http_session() -> requests.Session:
    sess = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=15, pool_maxsize=25)
    sess.mount('http://', adapter)
    sess.mount('https://', adapter)
    
    ip_blocks = ["49.36", "106.200", "122.161", "157.32", "223.224"]
    fake_ip = f"{random.choice(ip_blocks)}.{random.randint(1, 254)}.{random.randint(1, 254)}"
    
    devices = [
        "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
    ]
    
    sess.headers.update({
        "User-Agent": random.choice(devices),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.ujalahappiestonam.com",
        "Referer": "https://www.ujalahappiestonam.com/",
        "X-Forwarded-For": fake_ip,
        "X-Real-IP": fake_ip,
        "Client-IP": fake_ip
    })
    return sess

def generate_signature_data(payload: dict, user_key: str, data_key: str) -> str:
    payload_str = json.dumps(payload, separators=(',', ':'))
    a = base64.b64encode(payload_str.encode()).decode()
    u = base64.b64encode(str(payload['t']).encode()).decode()
    h = hmac.new(data_key[4:18].encode(), f"{u}.{a}".encode(), hashlib.sha256).hexdigest()
    f = base64.b64encode(h.encode()).decode()
    m, k = random.randint(1, 6), random.randint(2, 8)
    h_rand = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(k))
    return f"{u}.{a}.{k}{m}{f[0:m]}{h_rand}{f[m:]}"

def decrypt_resp(encrypted: str):
    try:
        pad = len(encrypted) % 4
        if pad: encrypted += "=" * (4 - pad)
        return json.loads(base64.b64decode(encrypted).decode()), True
    except Exception: return {}, False

def get_timestamp() -> int: return int(time.time() * 1000)

def generate_random_name() -> str:
    return f"{random.choice(['Aarav', 'Vivaan', 'Diya', 'Myra', 'Kiara', 'Rohan'])} {random.choice(['Nair', 'Menon', 'Pillai', 'Kurup', 'Varma'])}"

def create_user(sess: requests.Session):
    try:
        r = sess.post(BASE_URL, json={"masterKey": MASTER_KEY}, timeout=10)
        dec, ok = decrypt_resp(r.json().get("resp", ""))
        return (str(dec["userKey"]), dec["dataKey"]) if ok and dec.get("statusCode") == 200 else (None, None)
    except Exception: return None, None

def send_otp(sess: requests.Session, user_key: str, data_key: str, name: str, mobile: str) -> bool:
    img_path = get_pack_image_path()
    try:
        t = get_timestamp()
        data_val = generate_signature_data({"name": name, "mobile": mobile, "email": "", "city": "Kerala", "code": PRODUCT_CODE, "agreed1": "Yes", "agreed2": "Yes", "userKey": int(user_key), "t": t}, user_key, data_key)
        with open(img_path, "rb") as f:
            r = sess.post(f"{BASE_URL}/getOTP/{user_key}?t={t}", data={"t": str(t), "userKey": user_key, "data": data_val}, files={"pack": ("pack.jpg", f, "image/jpeg")}, timeout=15)
        dec, ok = decrypt_resp(r.json().get("resp", ""))
        return ok and dec.get("statusCode") == 200
    except Exception: return False

def verify_otp(sess: requests.Session, user_key: str, data_key: str, otp: str) -> Optional[str]:
    try:
        t = get_timestamp()
        u, a, g = generate_signature_data({"otp": otp, "userKey": int(user_key), "t": t}, user_key, data_key).split(".", 2)
        r = sess.post(f"{BASE_URL}/verifyOTP/{user_key}?t={t}", data=f"userKey={user_key}&data={urllib.parse.quote_plus(u)}.{urllib.parse.quote_plus(a)}.{urllib.parse.quote_plus(g)}", headers={"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}, timeout=10)
        dec, ok = decrypt_resp(r.json().get("resp", ""))
        return dec.get("token") if ok and dec.get("statusCode") == 200 else None
    except Exception: return None

def spin_wheel(sess: requests.Session, user_key: str, data_key: str, token: str) -> Optional[str]:
    try:
        t = get_timestamp()
        u, a, g = generate_signature_data({"userKey": int(user_key), "t": t}, user_key, data_key).split(".", 2)
        r = sess.post(f"{BASE_URL}/speenTheWheel/{user_key}?t={t}", data=f"userKey={user_key}&data={urllib.parse.quote_plus(u)}.{urllib.parse.quote_plus(a)}.{urllib.parse.quote_plus(g)}", headers={"content-type": "application/x-www-form-urlencoded; charset=UTF-8", "authorization": f"Bearer {token}"}, timeout=10)
        dec, ok = decrypt_resp(r.json().get("resp", ""))
        return dec.get('reward', 'Unknown') if ok and dec.get("statusCode") == 200 else None
    except Exception: return None

def claim_reward(sess: requests.Session, user_key: str, data_key: str, token: str) -> bool:
    try:
        t = get_timestamp()
        u, a, g = generate_signature_data({"userKey": int(user_key), "t": t}, user_key, data_key).split(".", 2)
        r = sess.post(f"{BASE_URL}/claimNow/{user_key}?t={t}", data=f"userKey={user_key}&data={urllib.parse.quote_plus(u)}.{urllib.parse.quote_plus(a)}.{urllib.parse.quote_plus(g)}", headers={"content-type": "application/x-www-form-urlencoded; charset=UTF-8", "authorization": f"Bearer {token}"}, timeout=10)
        dec, ok = decrypt_resp(r.json().get("resp", ""))
        return ok and dec.get("statusCode") == 200
    except Exception: return False

# ═══════════════════════════════════════════════════════════════
# BOT HANDLERS & HELPERS
# ═══════════════════════════════════════════════════════════════
class BotStates(StatesGroup):
    manual_mobile = State()
    manual_otp = State()
    broadcast = State()

def safe_send_message(chat_id: int, text: str, **kwargs):
    try: return bot.send_message(chat_id, text, **kwargs)
    except Exception: return None

def safe_copy_message(to_chat_id: int, from_chat_id: int, message_id: int) -> bool:
    for _ in range(3):
        try:
            bot.copy_message(to_chat_id, from_chat_id, message_id)
            return True
        except ApiTelegramException as e:
            if e.error_code == 429:
                retry_after = int(e.result_json.get("parameters", {}).get("retry_after", 2))
                time.sleep(retry_after + 0.5)
            else:
                return False
        except Exception:
            return False
    return False

def notify_admin(msg: str):
    for admin in ADMIN_IDS: safe_send_message(admin, msg, parse_mode="HTML")

@bot.my_chat_member_handler()
def my_chat_m(message: ChatMemberUpdated):
    new = message.new_chat_member
    if new.status in ['kicked', 'left']:
        handle_penalty(message.chat.id)

# ═══════════════════════════════════════════════════════════════
# ADMIN PANEL HANDLERS
# ═══════════════════════════════════════════════════════════════
class AdminFilter(SimpleCustomFilter):
    key = 'is_admin'
    def check(self, obj):
        return obj.from_user.id in ADMIN_IDS

bot.add_custom_filter(AdminFilter())
bot.add_custom_filter(StateFilter(bot))

def get_admin_inline_keyboard():
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"), InlineKeyboardButton("📊 Stats", callback_data="admin_stats"))
    markup.row(InlineKeyboardButton("💾 Backup DB", callback_data="admin_backup"))
    return markup

@bot.message_handler(commands=['admin'], is_admin=True)
def admin_panel(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    safe_send_message(message.chat.id, "⚙️ <b>Admin Control Panel</b>\nSelect an operation:", parse_mode="HTML", reply_markup=get_admin_inline_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"), is_admin=True)
def handle_admin_callbacks(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    action = call.data.replace("admin_", "", 1)

    if action == "stats":
        users = get_all_users()
        text = f"📊 <b>System Statistics</b>\n\n👥 Total Users: {len(users)}"
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode="HTML", reply_markup=get_admin_inline_keyboard())
        except Exception: pass

    elif action == "backup":
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "rb") as f: bot.send_document(chat_id, f)
        else:
            safe_send_message(chat_id, "❌ Database file not found.")

    elif action == "broadcast":
        bot.set_state(call.from_user.id, BotStates.broadcast, chat_id)
        safe_send_message(chat_id, "📢 Send the message to broadcast. Type /cancel to abort.")

@bot.message_handler(state=BotStates.broadcast, is_admin=True, content_types=['text', 'photo', 'video', 'document'])
def process_broadcast(message):
    if message.text == "/cancel":
        bot.delete_state(message.from_user.id, message.chat.id)
        return safe_send_message(message.chat.id, "Broadcast cancelled.")
        
    users = get_all_users()
    safe_send_message(message.chat.id, f"📢 Broadcasting to {len(users)} users...")
    success, failed = 0, 0
    for uid in users:
        if safe_copy_message(uid, message.chat.id, message.message_id): success += 1
        else: failed += 1
        time.sleep(0.04) 
    
    bot.delete_state(message.from_user.id, message.chat.id)
    safe_send_message(message.chat.id, f"✅ Broadcast Complete!\nSent: {success}\nFailed: {failed}")

# ═══════════════════════════════════════════════════════════════
# USER INTERFACE HANDLERS
# ═══════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def handle_check_join(call):
    if check_force_join(call.from_user.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        welcome_msg = (
            "🌟 <b>Welcome to Ujala Happiest Onam Loot Bot!</b> 🌟\n\n"
            "🔥 <b>FREE ₹50 CASHBACK Per Mobile Number</b> 🔥\n\n"
            "Steps to Earn:\n"
            "1️⃣ Click on 🛍 Premium Voucher.\n"
            "2️⃣ Bot details automatic handle karega (City: Kerala, Barcode: 8902102126232).\n"
            "3️⃣ Enter OTP & Spin the wheel!\n"
            "4️⃣ Get link on SMS -> Enter UPI -> Cashback in 24 hrs! 💸"
        )
        safe_send_message(call.message.chat.id, welcome_msg, parse_mode="HTML", reply_markup=get_premium_keyboard())
    else:
        bot.answer_callback_query(call.id, "❌ Aapne abhi tak saare Channels aur Group join nahi kiye hain!", show_alert=True)

@bot.message_handler(commands=['start', 'cancel', 'menu'])
def send_welcome(message):
    bot.delete_state(message.from_user.id, message.chat.id)
    
    args = message.text.split()
    referred_by = None
    if len(args) > 1 and args[1].isdigit():
        referred_by = int(args[1])
        
    track_user(message.from_user.id, message.from_user.first_name, referred_by)
    
    if not check_force_join(message.from_user.id):
        text = "⚠️ <b>Action Required!</b>\n\nBot use karne ke liye, kripya niche diye gaye saare channels aur group join karein:"
        safe_send_message(message.chat.id, text, parse_mode="HTML", reply_markup=force_join_markup())
        return
    
    welcome_msg = (
        "🌟 <b>Welcome to Ujala Happiest Onam Loot Bot!</b> 🌟\n\n"
        "🔥 <b>FREE ₹50 CASHBACK Per Mobile Number</b> 🔥\n\n"
        "Steps to Earn:\n"
        "1️⃣ Click on 🛍 Premium Voucher.\n"
        "2️⃣ Bot details automatic handle karega (City: Kerala, Barcode: 8902102126232).\n"
        "3️⃣ Enter OTP & Spin the wheel!\n"
        "4️⃣ Get link on SMS -> Enter UPI -> Cashback in 24 hrs! 💸"
    )
    safe_send_message(message.chat.id, welcome_msg, parse_mode="HTML", reply_markup=get_premium_keyboard())

@bot.message_handler(func=lambda msg: msg.text == BTN_HOW_TO_USE)
def how_to_use(message):
    if not check_force_join(message.from_user.id): return send_welcome(message)
    info = (
        "💡 <b>IMPORTANT INSTRUCTIONS:</b>\n\n"
        "⏰ <b>Time:</b> 1 PM – 8PM Daily\n\n"
        "👉 <b>Note:</b> ek number se ek baar hi apply kr skte ho.\n"
        "👉 But different number hai toh same bank account pe cashback le skte ho.\n"
        "👉 Different upi IDs dena like - google, paytm, phone pay etc.\n\n"
        "🎁 <b>Isme spin aae ga usme ₹50 cashback aae ga then sms pe ek link and code aae ga. "
        "Wo code dalke details fill krkr upi id dal dena cashback within 24 hrs me mil jae ga.</b> 🔥"
    )
    safe_send_message(message.chat.id, info, parse_mode="HTML")

@bot.message_handler(func=lambda msg: msg.text == BTN_SUPPORT)
def support_handler(message):
    if not check_force_join(message.from_user.id): return send_welcome(message)
    safe_send_message(message.chat.id, f"🆘 <b>Help & Support</b>\n\nAgar aapko koi issue aa raha hai, toh kripya admin se sampark karein:\nContact: <a href='tg://user?id={ADMIN_IDS[0]}'>Admin</a>", parse_mode="HTML")

@bot.message_handler(func=lambda msg: msg.text == BTN_MY_ORDERS)
def my_orders(message):
    if not check_force_join(message.from_user.id): return send_welcome(message)
    safe_send_message(message.chat.id, "🛍 <b>My Orders</b>\n\nAapke saare successfully claimed vouchers aur cashback history SMS link dwara track ki ja rahi hain. Bot se claimed rewards check karne ke liye 'VIP Profile' use karein.", parse_mode="HTML")

@bot.message_handler(func=lambda msg: msg.text == BTN_REFERRED_BONUS)
def refer_earn(message):
    if not check_force_join(message.from_user.id): return send_welcome(message)
    user_id = message.from_user.id
    stats = get_user_stats(user_id)
    ref_link = f"https://t.me/{bot.get_me().username}?start={user_id}"
    
    msg = (
        "🔗 <b>Referred Bonus Program</b> 🔗\n\n"
        "Apne doston ko invite karein aur kamayein Extra Claims!\n\n"
        "💡 <b>Reward System:</b>\n"
        "• 1 Refer = +1 Premium Claim\n"
        "• 5 Refers = +1 BONUS Claim! (Total 7 claims)\n\n"
        f"🎯 <b>Your Referrals:</b> {stats['referrals']}\n"
        f"💰 <b>Current Balance:</b> {stats['coins']} Coins\n\n"
        "<b>Important Rule:</b> 🚫 Jab aap ye link share karein, toh apne doston ko bolna ki seedha claim na karein. Pehle official website par offer terms dekhein, fir bot par claim karein.\n"
        "<i>(Note: Agar koi referral 3 ghante se pehle bot leave karta hai, toh 10 Coins ki penalty lagegi!)</i>\n\n"
        f"👇 <b>Your Referral Link:</b>\n<code>{ref_link}</code>"
    )
    
    markup = InlineKeyboardMarkup()
    share_url = f"https://t.me/share/url?url={ref_link}&text=Bhai%20jaldi%20ye%20bot%20join%20kar%2C%20Free%2050Rs%20cashback%20mil%20raha%20hai%21"
    markup.add(InlineKeyboardButton("📲 Share to WhatsApp/Telegram", url=share_url))
    
    safe_send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text in [BTN_VIP_PROFILE, BTN_ACCOUNT_WALLET])
def my_stats(message):
    if not check_force_join(message.from_user.id): return send_welcome(message)
    stats = get_user_stats(message.from_user.id)
    msg = (
        "👑 <b>VIP Profile & Wallet</b> 👑\n\n"
        f"👤 User: {message.from_user.first_name}\n"
        f"👥 Total Invites: <b>{stats['referrals']}</b>\n"
        f"🪙 Account Wallet (Coins): <b>{stats['coins']}</b>\n\n"
        "<i>(1 Coin = 1 Number Bypass via Premium Voucher)</i>"
    )
    safe_send_message(message.chat.id, msg, parse_mode="HTML")

@bot.message_handler(func=lambda msg: msg.text == BTN_PREMIUM_VOUCHER)
def handle_manual_claim_start(message):
    if not check_force_join(message.from_user.id): return send_welcome(message)
    user_id = message.from_user.id
    
    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    if not (13 <= ist_now.hour < 20):
        safe_send_message(message.chat.id, "⚠️ <b>Time Notice:</b>\nAs per Ujala campaign rules, offers are active between <b>1 PM and 8 PM IST</b>. Aap abhi try kar sakte hain, par agar OTP na aaye toh is time ke beech try karein.", parse_mode="HTML")
    
    stats = get_user_stats(user_id)
    if stats['coins'] <= 0:
        safe_send_message(message.chat.id, f"⚠️ <b>Out of Coins!</b>\n\nAapne apne saare free claims use kar liye hain. Naye numbers bypass karne ke liye doston ko <b>Refer</b> karein!\n(Click on '{BTN_REFERRED_BONUS}')", parse_mode="HTML")
        return

    bot.set_state(user_id, BotStates.manual_mobile, message.chat.id)
    safe_send_message(message.chat.id, "📱 <b>Enter 10-digit Mobile Number:</b>", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

@bot.message_handler(state=BotStates.manual_mobile)
def process_manual_mobile(message):
    if message.text in MENU_BUTTONS:
        bot.delete_state(message.from_user.id, message.chat.id)
        if message.text == "/cancel": return send_welcome(message)
        if message.text == BTN_HOW_TO_USE: return how_to_use(message)
        elif message.text == BTN_SUPPORT: return support_handler(message)
        elif message.text == BTN_MY_ORDERS: return my_orders(message)
        elif message.text == BTN_REFERRED_BONUS: return refer_earn(message)
        elif message.text in [BTN_VIP_PROFILE, BTN_ACCOUNT_WALLET]: return my_stats(message)
        elif message.text == BTN_PREMIUM_VOUCHER: return handle_manual_claim_start(message)
        return send_welcome(message)

    clean_mobile = re.sub(r"\D", "", message.text) if message.text else ""
    if len(clean_mobile) != 10: return safe_send_message(message.chat.id, "❌ Invalid number! Try again:")
    
    name = generate_random_name()
    safe_send_message(message.chat.id, f"⏳ Requesting OTP for <code>{html.escape(clean_mobile)}</code> with Anti-Ban Server...", parse_mode="HTML")
    
    sess = get_http_session()
    user_key, data_key = create_user(sess)
    if not user_key or not send_otp(sess, user_key, data_key, name, clean_mobile):
        bot.delete_state(message.from_user.id, message.chat.id)
        return safe_send_message(message.chat.id, "❌ Connection failed or Number Already Used. Try another number.", reply_markup=get_premium_keyboard())
        
    bot.add_data(message.from_user.id, message.chat.id, u=user_key, d=data_key, m=clean_mobile, n=name, r=0)
    bot.set_state(message.from_user.id, BotStates.manual_otp, message.chat.id)
    safe_send_message(message.chat.id, "✅ <b>OTP sent! Enter 6-digit code:</b>", parse_mode="HTML")

@bot.message_handler(state=BotStates.manual_otp)
def process_manual_otp(message):
    if message.text in MENU_BUTTONS:
        bot.delete_state(message.from_user.id, message.chat.id)
        return send_welcome(message)

    clean_otp = re.sub(r"\D", "", message.text) if message.text else ""
    if len(clean_otp) != 6: return safe_send_message(message.chat.id, "❌ Enter exactly 6 digits:")
        
    with bot.retrieve_data(message.from_user.id, message.chat.id) as d:
        if not d:
            bot.delete_state(message.from_user.id, message.chat.id)
            return safe_send_message(message.chat.id, "❌ Session expired.", reply_markup=get_premium_keyboard())
        user_key, data_key, mobile, name, retries = d.get('u'), d.get('d'), d.get('m'), d.get('n'), d.get('r', 0)
        
    sess = get_http_session()
    token = verify_otp(sess, user_key, data_key, clean_otp)
    if not token:
        if retries < 2:
            bot.add_data(message.from_user.id, message.chat.id, r=retries + 1)
            return safe_send_message(message.chat.id, f"❌ Wrong OTP! {2-retries} attempts left:")
        bot.delete_state(message.from_user.id, message.chat.id)
        return safe_send_message(message.chat.id, "❌ Too many failed attempts.", reply_markup=get_premium_keyboard())
    
    safe_send_message(message.chat.id, "🎡 Spinning Wheel & Bypassing system...")
    reward = spin_wheel(sess, user_key, data_key, token)
    
    if reward and claim_reward(sess, user_key, data_key, token):
        deduct_coin(message.from_user.id)
        
        success_msg = (
            "🎉 <b>BINGO! LOOT CLAIMED SUCCESSFULLY!</b> 🎉\n\n"
            f"👤 Name: <b>{html.escape(name)}</b>\n"
            f"📱 Number: <b>+91-{html.escape(mobile)}</b>\n"
            f"🎁 <b>UJALA REWARD:</b> {html.escape(reward)}\n\n"
            "🔥 <b>NEXT STEPS TO GET ₹50 CASHBACK:</b> 🔥\n"
            "1️⃣ Aapke is number par SMS mein ek link aur code aayega.\n"
            "2️⃣ Link open karein, apna Code aur details fill karein.\n"
            "3️⃣ Apna UPI ID daalein (Google Pay, Paytm, PhonePe, etc.).\n"
            "4️⃣ Cashback 24 hours mein aapke bank account mein aa jayega!\n\n"
            "<i>Note: Same bank account me multi-time lene ke liye different UPI IDs use karein!</i>"
        )
        safe_send_message(message.chat.id, success_msg, parse_mode="HTML", reply_markup=get_premium_keyboard())
        notify_admin(f"🎉 <b>Claim Success!</b>\nUser: {message.from_user.id}\nMobile: {mobile}\nReward: {reward}")
    else:
        safe_send_message(message.chat.id, "❌ Claim failed. The server might be overloaded or number reached limit.", reply_markup=get_premium_keyboard())
    
    bot.delete_state(message.from_user.id, message.chat.id)

def main():
    init_db()
    logger.info("Premium Railway Optimized Bot is starting...")
    bot.infinity_polling(timeout=20, long_polling_timeout=15, allowed_updates=["message", "callback_query", "my_chat_member"])

if __name__ == "__main__":
    main()
