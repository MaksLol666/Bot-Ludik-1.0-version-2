import asyncio
import logging
import sqlite3
import random
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType, ChatMemberStatus
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
CHANNEL_LINK = os.getenv("CHANNEL_LINK")
ADMIN_IDS = [int(os.getenv("ADMIN_IDS"))]
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
BOT_VERSION = os.getenv("BOT_VERSION")
BOT_RELEASE_DATE = os.getenv("BOT_RELEASE_DATE")
MIN_BET = int(os.getenv("MIN_BET"))
MAX_BET = int(os.getenv("MAX_BET"))
BONUS_COOLDOWN = int(os.getenv("BONUS_COOLDOWN"))
BONUS_MIN = int(os.getenv("BONUS_MIN"))
BONUS_MAX = int(os.getenv("BONUS_MAX"))

# ==================== БАЗА ДАННЫХ ====================
class Database:
    _instance = None
    _connection = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.db_path = "ludik_bot.db"
        if not os.path.exists(self.db_path):
            self.create_tables()
        else:
            self.update_tables()

    def get_connection(self):
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def update_tables(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'custom_name' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN custom_name TEXT")
            conn.commit()

    def create_tables(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                custom_name TEXT,
                balance_lc INTEGER DEFAULT 2500,
                balance_glc INTEGER DEFAULT 0,
                referrer_id INTEGER,
                is_banned INTEGER DEFAULT 0,
                ban_reason TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_bonus TIMESTAMP,
                total_lost INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_type TEXT,
                win BOOLEAN,
                bet INTEGER,
                win_amount INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                reward INTEGER,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS used_promocodes (
                user_id INTEGER,
                code TEXT,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, code),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (code) REFERENCES promocodes(code)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS business (
                user_id INTEGER PRIMARY KEY,
                business_type TEXT,
                last_collected TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                week_number TEXT,
                ticket_count INTEGER DEFAULT 0,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, week_number),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lottery_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_number TEXT UNIQUE,
                draw_date TIMESTAMP,
                winners TEXT,
                total_tickets INTEGER,
                total_amount INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referral_id INTEGER UNIQUE,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                donat_amount INTEGER DEFAULT 0,
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referral_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_status (
                user_id INTEGER PRIMARY KEY,
                status TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user INTEGER,
                to_user INTEGER,
                amount INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_user) REFERENCES users(user_id),
                FOREIGN KEY (to_user) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS glc_statuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                status_key TEXT,
                status_name TEXT,
                status_icon TEXT,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.commit()

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username.replace('@', ''),))
        row = cursor.fetchone()
        return dict(row) if row else None

    def create_user_with_name(self, user_id: int, username: str, first_name: str, custom_name: str, referrer_id: int = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name, custom_name, referrer_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, first_name, custom_name, referrer_id))
        if referrer_id:
            cursor.execute("INSERT OR IGNORE INTO referrals (referrer_id, referral_id) VALUES (?, ?)", (referrer_id, user_id))
            self.update_balance(referrer_id, 1000)
            self.update_glc(referrer_id, 100)
        conn.commit()

    def update_balance(self, user_id: int, amount: int) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance_lc = balance_lc + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        cursor.execute("SELECT balance_lc FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def update_glc(self, user_id: int, amount: int) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance_glc = balance_glc + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        cursor.execute("SELECT balance_glc FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

    def add_game_stat(self, user_id: int, game: str, win: bool, bet: int, win_amount: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO game_stats (user_id, game_type, win, bet, win_amount) VALUES (?, ?, ?, ?, ?)",
                      (user_id, game, win, bet, win_amount))
        if not win:
            cursor.execute("UPDATE users SET total_lost = total_lost + ? WHERE user_id = ?", (bet, user_id))
        conn.commit()
        self.log_action(user_id, f"игра_{game}", f"{'win' if win else 'lose'}: {bet}")

    def transfer_lc(self, from_user: int, to_user: int, amount: int) -> tuple[bool, str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        sender = self.get_user(from_user)
        if not sender or sender['balance_lc'] < amount:
            return False, "Недостаточно средств"
        receiver = self.get_user(to_user)
        if not receiver:
            return False, "Получатель не найден"
        cursor.execute("UPDATE users SET balance_lc = balance_lc - ? WHERE user_id = ?", (amount, from_user))
        cursor.execute("UPDATE users SET balance_lc = balance_lc + ? WHERE user_id = ?", (amount, to_user))
        cursor.execute("INSERT INTO transfers (from_user, to_user, amount) VALUES (?, ?, ?)", (from_user, to_user, amount))
        conn.commit()
        self.log_action(from_user, "перевод", f"отправил {amount} LC пользователю {to_user}")
        self.log_action(to_user, "перевод", f"получил {amount} LC от {from_user}")
        return True, "Перевод выполнен успешно"

    def log_action(self, user_id: int, action: str, details: str = ""):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO user_logs (user_id, action, details) VALUES (?, ?, ?)", (user_id, action, details))
        conn.commit()

    def get_user_glc_statuses(self, user_id: int):
        conn = self.get_connection()
        cursor = conn.execute("SELECT * FROM glc_statuses WHERE user_id = ? ORDER BY purchased_at DESC", (user_id,))
        return [dict(row) for row in cursor.fetchall()]

    def has_glc_status(self, user_id: int, status_key: str) -> bool:
        conn = self.get_connection()
        cursor = conn.execute("SELECT * FROM glc_statuses WHERE user_id = ? AND status_key = ?", (user_id, status_key))
        return cursor.fetchone() is not None

db = Database()

# ==================== КЛАВИАТУРЫ ====================
def get_start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="📰 Подписаться", url=CHANNEL_LINK), InlineKeyboardButton(text="🔄 Проверить", callback_data="check_sub"))
    builder.row(InlineKeyboardButton(text="ℹ️ Информация", callback_data="info"))
    return builder.as_markup()

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎰 Казино", callback_data="casino_menu"), InlineKeyboardButton(text="🎟 Лотерея", callback_data="lottery_menu"))
    builder.row(InlineKeyboardButton(text="💰 Донат", callback_data="donate_menu"), InlineKeyboardButton(text="🎁 Бонус", callback_data="get_bonus"))
    builder.row(InlineKeyboardButton(text="💼 Бизнес", callback_data="business_menu"), InlineKeyboardButton(text="👤 Моя стата", callback_data="my_stats"))
    builder.row(InlineKeyboardButton(text="🏆 Топы", callback_data="top_menu"), InlineKeyboardButton(text="🎫 Промокод", callback_data="activate_promo"))
    builder.row(InlineKeyboardButton(text="👥 Рефералы", callback_data="referral_menu"), InlineKeyboardButton(text="💰 GLC", callback_data="glc_info"))
    builder.row(InlineKeyboardButton(text="ℹ️ Инфо", callback_data="info"))
    return builder.as_markup()

def get_casino_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🃏 Рулетка", callback_data="game_roulette"), InlineKeyboardButton(text="🎰 Слоты", callback_data="game_slots"))
    builder.row(InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice"), InlineKeyboardButton(text="💣 Мины", callback_data="game_mines"))
    builder.row(InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_blackjack"), InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_business_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="20к (2.5к/день)", callback_data="buy_small"), InlineKeyboardButton(text="50к (5.5к/день)", callback_data="buy_medium"))
    builder.row(InlineKeyboardButton(text="100к (10.5к/день)", callback_data="buy_large"), InlineKeyboardButton(text="💎 500₽ (50к/день)", callback_data="buy_paid"))
    builder.row(InlineKeyboardButton(text="💰 Собрать", callback_data="collect_business"), InlineKeyboardButton(text="📊 Мой бизнес", callback_data="my_business"))
    builder.row(InlineKeyboardButton(text="💵 Продать бизнес", callback_data="sell_business"), InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_top_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💰 Богачи", callback_data="top_balance"), InlineKeyboardButton(text="🃏 Рулетка", callback_data="top_roulette"))
    builder.row(InlineKeyboardButton(text="🎰 Слоты", callback_data="top_slots"), InlineKeyboardButton(text="🎲 Кости", callback_data="top_dice"))
    builder.row(InlineKeyboardButton(text="💣 Мины", callback_data="top_mines"), InlineKeyboardButton(text="🎟 Лотерея", callback_data="top_lottery"))
    builder.row(InlineKeyboardButton(text="🃏 Блэкджек", callback_data="top_blackjack"), InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_back_button():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_glc_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💰 Баланс GLC", callback_data="glc_balance"), InlineKeyboardButton(text="🛒 Магазин статусов", callback_data="glc_shop"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_glc_shop_page(page, total_pages, statuses, owned_keys):
    builder = InlineKeyboardBuilder()
    for key, status in statuses:
        if key in owned_keys:
            builder.row(InlineKeyboardButton(text=f"✅ {status['icon']} {status['name']} - {status['price']} GLC", callback_data="noop"))
        else:
            builder.row(InlineKeyboardButton(text=f"{status['icon']} {status['name']} - {status['price']} GLC", callback_data=f"buy_status_{key}"))
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_page_{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_page_{page+1}"))
    builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="◀️ Назад в GLC", callback_data="glc_menu"))
    return builder.as_markup()

# ==================== GLC СТАТУСЫ ====================
GLC_STATUSES = {
    "dev": {"name": "Разраб пх", "icon": "👨‍💻", "price": 2500},
    "smoke": {"name": "Nicotine", "icon": "🚬", "price": 2500},
    "star": {"name": "Яркий", "icon": "⭐", "price": 3000},
    "lightning": {"name": "Кчау", "icon": "⚡", "price": 3000},
    "devil": {"name": "Шалун", "icon": "😈", "price": 3000},
    "clown": {"name": "Клоун", "icon": "🤡", "price": 3000},
    "ogre": {"name": "Демон", "icon": "👹", "price": 3000},
    "alien": {"name": "Пиксель", "icon": "👾", "price": 5000},
    "eye": {"name": "Всевидящий", "icon": "👁️‍🗨️", "price": 5000},
    "speech": {"name": "Болтун", "icon": "🗨️", "price": 5000},
    "eyeball": {"name": "Всемогущее Око", "icon": "👁️", "price": 5000},
    "globe": {"name": "Мир дружба горловой", "icon": "🌐", "price": 6500},
    "exchange": {"name": "p2p", "icon": "💱", "price": 6500},
    "money": {"name": "Money", "icon": "💸", "price": 6500},
    "card": {"name": "Master card", "icon": "💳", "price": 6500},
    "medal": {"name": "СВО", "icon": "🎖️", "price": 7777},
    "moai": {"name": "Тупой", "icon": "🗿", "price": 7777},
    "coffin": {"name": "Гроб", "icon": "⚰️", "price": 7777},
    "18plus": {"name": "Ода детка ты такая сладкая конфетка", "icon": "🔞", "price": 7777},
    "belarus": {"name": "Беларусь", "icon": "🇧🇾", "price": 10000},
    "germany": {"name": "Германия", "icon": "🇩🇪", "price": 10000},
    "guatemala": {"name": "Гватемала", "icon": "🇬🇹", "price": 10000},
    "israel": {"name": "Израиль", "icon": "🇮🇱", "price": 10000},
    "kazakhstan": {"name": "Казахстан", "icon": "🇰🇿", "price": 10000},
    "russia": {"name": "Россия", "icon": "🇷🇺", "price": 10000},
    "usa": {"name": "США", "icon": "🇺🇸", "price": 10000},
    "ukraine": {"name": "Украина", "icon": "🇺🇦", "price": 10000},
    "theater": {"name": "Лицемер", "icon": "🎭", "price": 11111},
    "dollar": {"name": "Баксы", "icon": "💵", "price": 15000},
    "euro": {"name": "Евро", "icon": "💶", "price": 15000},
    "chart": {"name": "Арбитраж", "icon": "📈", "price": 15000},
    "pills": {"name": "Xanax", "icon": "💊", "price": 25000},
    "syringe": {"name": "Героин", "icon": "💉", "price": 25000},
    "rose": {"name": "Роза", "icon": "🌹", "price": 30000},
    "cherry": {"name": "Сакура", "icon": "🌸", "price": 30000},
    "tulip": {"name": "Тюльпан", "icon": "🌷", "price": 30000},
    "banana": {"name": "Бананчик", "icon": "🍌", "price": 35000},
    "eggplant": {"name": "Баклажанчик", "icon": "🍆", "price": 35000},
    "peach": {"name": "Попка", "icon": "🍑", "price": 35000},
    "cucumber": {"name": "Огуречик", "icon": "🥒", "price": 35000},
    "lobster": {"name": "Рак ебаный", "icon": "🦞", "price": 40000},
    "watch_premium": {"name": "Премиум Rolex", "icon": "⌚", "price": 50000},
    "fire": {"name": "Fair", "icon": "🔥", "price": 66666},
    "snow": {"name": "Эльза", "icon": "❄️", "price": 66666},
    "crown": {"name": "Король", "icon": "👑", "price": 77777},
    "diamond": {"name": "Бриллиант", "icon": "💎", "price": 77777},
    "wilted": {"name": "MEPTB", "icon": "🥀", "price": 99999},
}
STATUS_PAGES = [list(GLC_STATUSES.items())[i:i+10] for i in range(0, len(GLC_STATUSES), 10)]
TOTAL_PAGES = len(STATUS_PAGES)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def is_private(message): return message.chat.type == ChatType.PRIVATE
def is_admin(user_id): return user_id in ADMIN_IDS

async def require_subscription(func):
    async def wrapper(message: Message, *args, **kwargs):
        user_id = message.from_user.id
        user = db.get_user(user_id)
        if not user: await message.answer("❌ Ты не зарегистрирован! Напиши /start"); return
        if user['is_banned']: await message.answer("⛔ Ты забанен!"); return
        try:
            chat_member = await message.bot.get_chat_member(CHANNEL_ID, user_id)
            if chat_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                await message.answer(f"🔒 <b>Для доступа к играм нужно подписаться на канал!</b>\n\n👉 {CHANNEL_LINK}\n\nПосле подписки нажми /play"); return
        except: pass
        return await func(message, *args, **kwargs)
    return wrapper

# ==================== РЕГИСТРАЦИЯ ====================
class Registration(StatesGroup):
    waiting_for_name = State()

# ==================== ИГРЫ ====================
BLACK_NUMBERS = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]
RED_NUMBERS = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
ROW1 = [1,4,7,10,13,16,19,22,25,28,31,34]; ROW2 = [2,5,8,11,14,17,20,23,26,29,32,35]; ROW3 = [3,6,9,12,15,18,21,24,27,30,33,36]
COLUMNS = {i: [i*3-2, i*3-1, i*3] for i in range(1,13)}
RANGE1_12 = list(range(1,13)); RANGE13_24 = list(range(13,25)); RANGE25_36 = list(range(25,37)); RANGE1_18 = list(range(1,19)); RANGE19_36 = list(range(19,37))
EVEN = [x for x in range(1,37) if x%2==0]; ODD = [x for x in range(1,37) if x%2!=0]

def check_roulette_win(bet_type, result):
    if bet_type in ["зеленое","0"]: return result==0, 36
    if bet_type.isdigit(): return int(bet_type)==result, 36
    if bet_type in ["красное","черное"]: return (result in RED_NUMBERS if bet_type=="красное" else result in BLACK_NUMBERS), 2
    if bet_type in ["ряд1","ряд2","ряд3"]: r=ROW1 if bet_type=="ряд1" else ROW2 if bet_type=="ряд2" else ROW3; return result in r, 3
    if bet_type in ["1-12","13-24","25-36"]: r=RANGE1_12 if bet_type=="1-12" else RANGE13_24 if bet_type=="13-24" else RANGE25_36; return result in r, 3
    if bet_type in ["1-18","19-36","мал","малые","бол","большие"]: r=RANGE1_18 if bet_type in ["1-18","мал","малые"] else RANGE19_36; return result in r, 2
    if bet_type in ["чёт","чет","чётное","четное","нечёт","нечет","нечётное","нечетное"]: return (result in EVEN if bet_type in ["чёт","чет","чётное","четное"] else result in ODD), 2
    if bet_type.startswith("столбец"):
        try:
            col = int(bet_type.replace("столбец",""))
            if 1<=col<=12: return result in COLUMNS[col], 12
        except: pass
    return False, 0

SLOT_VALUES = {64:10, 1:5, 43:3, 22:3}

CARD_VALUES = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':10,'Q':10,'K':10,'A':11}
CARDS = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']; SUITS = ['♥️','♦️','♣️','♠️']
def create_deck(): deck=[f"{c}{s}" for s in SUITS for c in CARDS]; random.shuffle(deck); return deck
def card_value(card): val=card[:-1] if len(card)>2 else card[0]; return CARD_VALUES[val] if val in CARD_VALUES else CARD_VALUES[val[0]]

def hand_score(hand):
    total=aces=0
    for c in hand:
        v=card_value(c)
        if v==11: aces+=1; total+=11
        else: total+=v
    while total>21 and aces>0: total-=10; aces-=1
    return total

# ==================== РОУТЕР И ОБРАБОТЧИКИ ====================
router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if not is_private(message): await message.answer("❌ Команда /start доступна только в личных сообщениях!"); return
    user_id = message.from_user.id
    user = db.get_user(user_id)
    if not user:
        await state.set_state(Registration.waiting_for_name)
        await message.answer("👋 <b>Добро пожаловать в Лудик!</b>\n\nДля начала игры придумай себе имя (до 10 символов):")
        return
    if user['is_banned']: await message.answer(f"⛔ Вы заблокированы! Причина: {user['ban_reason']}"); return
    try:
        cm = await message.bot.get_chat_member(CHANNEL_ID, user_id)
        if cm.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await message.answer(f"🔒 Подпишись на канал: {CHANNEL_LINK}", reply_markup=get_start_keyboard())
        else:
            await message.answer(f"🎲 С возвращением, {user.get('custom_name', user['username'])}!\n💰 Баланс: {user['balance_lc']} LC", reply_markup=get_main_menu())
    except:
        await message.answer(f"🎲 С возвращением, {user.get('custom_name', user['username'])}!\n💰 Баланс: {user['balance_lc']} LC", reply_markup=get_main_menu())

@router.message(Registration.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name)>10: await message.answer("❌ Имя слишком длинное! Максимум 10 символов."); return
    if len(name)<2: await message.answer("❌ Имя слишком короткое! Минимум 2 символа."); return
    if not all(c.isalnum() or c=='_' for c in name): await message.answer("❌ Только буквы, цифры и _"); return
    db.create_user_with_name(message.from_user.id, message.from_user.username or "NoUsername", message.from_user.first_name, name, None)
    await message.answer(f"🎰 <b>Добро пожаловать в Лудик!</b>\n\nПривет, {name}!", reply_markup=get_main_menu())
    await state.clear()

@router.message(Command("play"))
async def cmd_play(message: Message):
    if not is_private(message): await message.answer("❌ Только в личных сообщениях"); return
    user = db.get_user(message.from_user.id)
    if not user: await message.answer("❌ Напиши /start"); return
    if user['is_banned']: await message.answer("⛔ Ты забанен!"); return
    try:
        cm = await message.bot.get_chat_member(CHANNEL_ID, message.from_user.id)
        if cm.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await message.answer(f"🔒 Подпишись: {CHANNEL_LINK}", reply_markup=get_start_keyboard())
        else:
            await message.answer("🎮 Игровой зал:", reply_markup=get_main_menu())
    except:
        await message.answer("🎮 Игровой зал:", reply_markup=get_main_menu())

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("🎮 Главное меню:", reply_markup=get_main_menu())
    await callback.answer()

@router.callback_query(F.data == "casino_menu")
async def casino_menu(callback: CallbackQuery):
    await callback.message.edit_text("🎰 Казино", reply_markup=get_casino_menu())
    await callback.answer()

@router.callback_query(F.data == "lottery_menu")
async def lottery_menu(callback: CallbackQuery):
    await callback.message.answer("🎟 Лотерея - команды: /купить [кол-во], /моибилеты")
    await callback.answer()

@router.callback_query(F.data == "donate_menu")
async def donate_menu(callback: CallbackQuery):
    await callback.message.answer("💰 Донат - напиши /donate")
    await callback.answer()

@router.callback_query(F.data == "get_bonus")
async def get_bonus_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user: await callback.answer("❌ Не зарегистрирован"); return
    last = user.get('last_bonus')
    if last:
        diff = datetime.now() - datetime.strptime(last, '%Y-%m-%d %H:%M:%S')
        if diff.total_seconds() < BONUS_COOLDOWN:
            hours = (BONUS_COOLDOWN - diff.total_seconds())/3600
            await callback.answer(f"⏳ Через {hours:.1f} ч", show_alert=True); return
    bonus = random.randint(BONUS_MIN, BONUS_MAX)
    db.update_balance(callback.from_user.id, bonus)
    conn = db.get_connection()
    conn.execute("UPDATE users SET last_bonus = datetime('now') WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    await callback.answer(f"🎁 +{bonus} LC", show_alert=True)
    await callback.message.edit_text(f"🎁 +{bonus} LC\n💰 Баланс: {db.get_user(callback.from_user.id)['balance_lc']}", reply_markup=get_back_button())

@router.callback_query(F.data == "business_menu")
async def business_menu_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user: await callback.answer("❌ Не зарегистрирован"); return
    conn = db.get_connection()
    biz = conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    text = "💼 Бизнес\n\n"
    if biz:
        bt = {"small":"Малый","medium":"Средний","large":"Крупный","paid":"💎 Богатый"}.get(biz[1],"")
        text += f"✅ {bt}\n"
        last = datetime.strptime(biz[2], '%Y-%m-%d %H:%M:%S')
        hours = (datetime.now()-last).total_seconds()/3600
        if hours>=24: text += "💰 Доступен сбор!"
        else: text += f"⏳ Через {24-hours:.1f} ч"
    else: text += "У тебя нет бизнеса"
    await callback.message.edit_text(text, reply_markup=get_business_menu())
    await callback.answer()

@router.callback_query(F.data == "my_stats")
async def my_stats_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user: await callback.answer("❌ Не зарегистрирован"); return
    conn = db.get_connection()
    stats = conn.execute("SELECT game_type, COUNT(*) as total, SUM(CASE WHEN win THEN 1 ELSE 0 END) as wins FROM game_stats WHERE user_id = ? GROUP BY game_type", (callback.from_user.id,)).fetchall()
    text = f"👤 {user.get('custom_name', user['username'])}\n💰 LC: {user['balance_lc']} | GLC: {user['balance_glc']}\n📊 Статистика:\n"
    for s in stats: text += f"• {s[0]}: {s[2]}/{s[1]-s[2]}\n"
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "top_menu")
async def top_menu_callback(callback: CallbackQuery):
    await callback.message.edit_text("🏆 Выбери категорию:", reply_markup=get_top_menu())
    await callback.answer()

@router.callback_query(F.data == "top_balance")
async def top_balance(callback: CallbackQuery):
    conn = db.get_connection()
    rows = conn.execute("SELECT user_id, username, custom_name, balance_lc FROM users WHERE is_banned=0 ORDER BY balance_lc DESC LIMIT 10").fetchall()
    text = "💰 Топ богачей\n\n"
    for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "top_roulette")
async def top_roulette(callback: CallbackQuery):
    conn = db.get_connection()
    rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='roulette' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
    text = "🃏 Топ рулетки\n\n"
    for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "activate_promo")
async def activate_promo_callback(callback: CallbackQuery):
    await callback.message.answer("🎫 Введи промокод: /promo КОД")
    await callback.answer()

@router.callback_query(F.data == "referral_menu")
async def referral_menu_callback(callback: CallbackQuery):
    bot = callback.bot
    bot_name = (await bot.me()).username
    link = f"https://t.me/{bot_name}?start=ref_{callback.from_user.id}"
    conn = db.get_connection()
    refs = conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (callback.from_user.id,)).fetchone()[0]
    text = f"👥 Рефералы\n\n🔗 {link}\n👤 Приглашено: {refs}\n💰 За каждого +1000 LC"
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "glc_info")
async def glc_info_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user: await callback.answer("❌ Не зарегистрирован"); return
    statuses = db.get_user_glc_statuses(callback.from_user.id)
    stext = "\n".join([f"• {s['status_icon']} {s['status_name']}" for s in statuses]) or "Нет статусов"
    text = f"💰 GLC: {user['balance_glc']}\n\nТвои статусы:\n{stext}"
    await callback.message.edit_text(text, reply_markup=get_glc_menu())
    await callback.answer()

@router.callback_query(F.data == "glc_balance")
async def glc_balance(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    await callback.message.edit_text(f"💰 Твой GLC: {user['balance_glc']}", reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "glc_shop")
async def glc_shop_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user: await callback.answer("❌ Не зарегистрирован"); return
    owned = db.get_user_glc_statuses(callback.from_user.id)
    owned_keys = [s['status_key'] for s in owned]
    await callback.message.edit_text("🛒 Магазин статусов\nВыбери:", reply_markup=get_glc_shop_page(1, TOTAL_PAGES, STATUS_PAGES[0], owned_keys))
    await callback.answer()

@router.callback_query(F.data.startswith("shop_page_"))
async def shop_page_callback(callback: CallbackQuery):
    page = int(callback.data.replace("shop_page_", ""))
    user = db.get_user(callback.from_user.id)
    owned = db.get_user_glc_statuses(callback.from_user.id)
    owned_keys = [s['status_key'] for s in owned]
    await callback.message.edit_text("🛒 Магазин статусов", reply_markup=get_glc_shop_page(page, TOTAL_PAGES, STATUS_PAGES[page-1], owned_keys))
    await callback.answer()

@router.callback_query(F.data.startswith("buy_status_"))
async def buy_status_callback(callback: CallbackQuery):
    key = callback.data.replace("buy_status_", "")
    if key not in GLC_STATUSES: await callback.answer("❌ Статус не найден"); return
    status = GLC_STATUSES[key]
    user = db.get_user(callback.from_user.id)
    if not user: await callback.answer("❌ Не зарегистрирован"); return
    if user['balance_glc'] < status['price']: await callback.answer(f"❌ Нужно {status['price']} GLC", show_alert=True); return
    if db.has_glc_status(callback.from_user.id, key): await callback.answer("❌ Уже есть", show_alert=True); return
    conn = db.get_connection()
    conn.execute("UPDATE users SET balance_glc = balance_glc - ? WHERE user_id = ?", (status['price'], callback.from_user.id))
    conn.execute("INSERT INTO glc_statuses (user_id, status_key, status_name, status_icon) VALUES (?, ?, ?, ?)",
                (callback.from_user.id, key, status['name'], status['icon']))
    conn.commit()
    await callback.answer(f"✅ Куплен статус {status['icon']} {status['name']}!", show_alert=True)
    owned = db.get_user_glc_statuses(callback.from_user.id)
    owned_keys = [s['status_key'] for s in owned]
    await callback.message.edit_text("🛒 Магазин статусов", reply_markup=get_glc_shop_page(1, TOTAL_PAGES, STATUS_PAGES[0], owned_keys))

@router.callback_query(F.data == "info")
async def info_callback(callback: CallbackQuery):
    await callback.message.edit_text(f"🤖 Лудик {BOT_VERSION}\n👑 {ADMIN_USERNAME}\n⚠️ Деньги не возвращаются", reply_markup=get_start_keyboard())
    await callback.answer()

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    try:
        cm = await callback.bot.get_chat_member(CHANNEL_ID, callback.from_user.id)
        if cm.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await callback.answer("❌ Не подписан", show_alert=True)
        else:
            await callback.answer("✅ Подписан!", show_alert=True)
            await callback.message.edit_text("🎮 Игровой зал:", reply_markup=get_main_menu())
    except:
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data == "game_roulette")
async def game_roulette(callback: CallbackQuery):
    await callback.message.answer("🃏 Рулетка\nКоманда: рул [ставка] [цвет/число]\nПример: рул красное 1000")
    await callback.answer()

@router.callback_query(F.data == "game_slots")
async def game_slots(callback: CallbackQuery):
    await callback.message.answer("🎰 Слоты\nКоманда: слоты [ставка]\nВыигрыши: 777 x10, 💎 x5, 🍋/🍒 x3")
    await callback.answer()

@router.callback_query(F.data == "game_dice")
async def game_dice(callback: CallbackQuery):
    await callback.message.answer("🎲 Кости\nКоманда: кости [ставка]\nПротивник принимает вызов")
    await callback.answer()

@router.callback_query(F.data == "game_mines")
async def game_mines(callback: CallbackQuery):
    await callback.message.answer("💣 Мины\nКоманда: мины [ставка]")
    await callback.answer()

@router.callback_query(F.data == "game_blackjack")
async def game_blackjack(callback: CallbackQuery):
    await callback.message.answer("🃏 Блэкджек\nКоманда: бджек [ставка]")
    await callback.answer()

@router.callback_query(F.data == "buy_small")
async def buy_small(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if user['balance_lc'] < 20000: await callback.answer("❌ Нужно 20000 LC", show_alert=True); return
    conn = db.get_connection()
    if conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone():
        await callback.answer("❌ Уже есть бизнес", show_alert=True); return
    db.update_balance(callback.from_user.id, -20000)
    conn.execute("INSERT INTO business (user_id, business_type, last_collected) VALUES (?, 'small', datetime('now'))", (callback.from_user.id,))
    conn.commit()
    await callback.answer("✅ Куплен Малый бизнес!", show_alert=True)
    await business_menu_callback(callback)

@router.callback_query(F.data == "buy_medium")
async def buy_medium(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if user['balance_lc'] < 50000: await callback.answer("❌ Нужно 50000 LC", show_alert=True); return
    conn = db.get_connection()
    if conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone():
        await callback.answer("❌ Уже есть бизнес", show_alert=True); return
    db.update_balance(callback.from_user.id, -50000)
    conn.execute("INSERT INTO business (user_id, business_type, last_collected) VALUES (?, 'medium', datetime('now'))", (callback.from_user.id,))
    conn.commit()
    await callback.answer("✅ Куплен Средний бизнес!", show_alert=True)
    await business_menu_callback(callback)

@router.callback_query(F.data == "buy_large")
async def buy_large(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if user['balance_lc'] < 100000: await callback.answer("❌ Нужно 100000 LC", show_alert=True); return
    conn = db.get_connection()
    if conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone():
        await callback.answer("❌ Уже есть бизнес", show_alert=True); return
    db.update_balance(callback.from_user.id, -100000)
    conn.execute("INSERT INTO business (user_id, business_type, last_collected) VALUES (?, 'large', datetime('now'))", (callback.from_user.id,))
    conn.commit()
    await callback.answer("✅ Куплен Крупный бизнес!", show_alert=True)
    await business_menu_callback(callback)

@router.callback_query(F.data == "buy_paid")
async def buy_paid(callback: CallbackQuery):
    await callback.answer("💎 Платный бизнес - через /donate", show_alert=True)

@router.callback_query(F.data == "collect_business")
async def collect_business_callback(callback: CallbackQuery):
    conn = db.get_connection()
    biz = conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    if not biz: await callback.answer("❌ Нет бизнеса", show_alert=True); return
    prices = {"small":2500, "medium":5500, "large":10500, "paid":50000}
    last = datetime.strptime(biz[2], '%Y-%m-%d %H:%M:%S')
    if (datetime.now()-last).total_seconds() < 86400: await callback.answer("⏳ Еще не прошло 24 часа", show_alert=True); return
    conn.execute("UPDATE business SET last_collected = datetime('now') WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    db.update_balance(callback.from_user.id, prices.get(biz[1],0))
    await callback.answer("💰 Доход собран!", show_alert=True)
    await business_menu_callback(callback)

@router.callback_query(F.data == "my_business")
async def my_business_callback(callback: CallbackQuery):
    conn = db.get_connection()
    biz = conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    if not biz: await callback.answer("❌ Нет бизнеса", show_alert=True); return
    names = {"small":"Малый","medium":"Средний","large":"Крупный","paid":"💎 Богатый"}
    prices = {"small":20000,"medium":50000,"large":100000,"paid":500}
    last = datetime.strptime(biz[2], '%Y-%m-%d %H:%M:%S')
    hours = (datetime.now()-last).total_seconds()/3600
    text = f"🏢 {names.get(biz[1])}\n💰 {prices.get(biz[1])} LC\n📈 Доход: +{prices.get(biz[1])//20} LC/день\n⏱ Сбор через {24-hours:.1f} ч"
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "sell_business")
async def sell_business_callback(callback: CallbackQuery):
    conn = db.get_connection()
    biz = conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    if not biz: await callback.answer("❌ Нет бизнеса", show_alert=True); return
    prices = {"small":20000,"medium":50000,"large":100000,"paid":500}
    sell_price = prices.get(biz[1],0)//2
    conn.execute("DELETE FROM business WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    db.update_balance(callback.from_user.id, sell_price)
    await callback.answer(f"✅ Продано за {sell_price} LC", show_alert=True)
    await business_menu_callback(callback)

@router.message(Command("promo"))
async def cmd_promo(message: Message):
    args = message.text.split()
    if len(args)<2: await message.answer("❌ /promo КОД"); return
    code = args[1]
    conn = db.get_connection()
    promo = conn.execute("SELECT * FROM promocodes WHERE code = ?", (code,)).fetchone()
    if not promo: await message.answer("❌ Промокод не найден"); return
    if promo[3] >= promo[2]: await message.answer("❌ Лимит исчерпан"); return
    used = conn.execute("SELECT * FROM used_promocodes WHERE user_id = ? AND code = ?", (message.from_user.id, code)).fetchone()
    if used: await message.answer("❌ Уже активирован"); return
    conn.execute("UPDATE promocodes SET used_count = used_count+1 WHERE code = ?", (code,))
    conn.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?, ?)", (message.from_user.id, code))
    conn.commit()
    db.update_balance(message.from_user.id, promo[1])
    await message.answer(f"✅ +{promo[1]} LC")

@router.message(Command("купить"))
async def buy_tickets(message: Message):
    args = message.text.split()
    if len(args)<2: await message.answer("❌ /купить [кол-во]"); return
    try: count = int(args[1])
    except: await message.answer("❌ Число"); return
    if count<=0: await message.answer("❌ >0"); return
    user = db.get_user(message.from_user.id)
    if not user: await message.answer("❌ /start"); return
    total = count*10000
    if user['balance_lc'] < total: await message.answer("❌ Недостаточно"); return
    week = f"{datetime.now().year}-{datetime.now().isocalendar()[1]}"
    conn = db.get_connection()
    db.update_balance(message.from_user.id, -total)
    conn.execute("INSERT INTO lottery_tickets (user_id, week_number, ticket_count) VALUES (?, ?, ?) ON CONFLICT(user_id, week_number) DO UPDATE SET ticket_count = ticket_count + ?",
                (message.from_user.id, week, count, count))
    conn.commit()
    await message.answer(f"✅ Куплено {count} билетов")

@router.message(Command("моибилеты"))
async def my_tickets(message: Message):
    week = f"{datetime.now().year}-{datetime.now().isocalendar()[1]}"
    conn = db.get_connection()
    tickets = conn.execute("SELECT ticket_count FROM lottery_tickets WHERE user_id = ? AND week_number = ?", (message.from_user.id, week)).fetchone()
    total = conn.execute("SELECT SUM(ticket_count) FROM lottery_tickets WHERE week_number = ?", (week,)).fetchone()[0] or 0
    await message.answer(f"🎫 Твои билеты: {tickets[0] if tickets else 0}\n📊 Всего: {total}")

@router.message(Command("перевод"))
async def transfer_cmd(message: Message):
    args = message.text.split()
    if len(args)<3: await message.answer("❌ /перевод @username сумма"); return
    username = args[1].replace('@','')
    try: amount = int(args[2])
    except: await message.answer("❌ Число"); return
    if amount<MIN_BET: await message.answer(f"❌ Мин {MIN_BET}"); return
    receiver = db.get_user_by_username(username)
    if not receiver: await message.answer("❌ Пользователь не найден"); return
    success, msg = db.transfer_lc(message.from_user.id, receiver['user_id'], amount)
    await message.answer(msg)

@router.message(Command("donate"))
async def donate_cmd(message: Message):
    await message.answer("💰 Донат:\n100₽ - 20000 LC\n500₽ - Бизнес\nДля оплаты пиши админу")

@router.message(Command("my"))
async def my_cmd(message: Message):
    user = db.get_user(message.from_user.id)
    if not user: await message.answer("❌ /start"); return
    await message.answer(f"💰 LC: {user['balance_lc']}\n💰 GLC: {user['balance_glc']}")

@router.message(Command("tb"))
async def tb_cmd(message: Message):
    conn = db.get_connection()
    rows = conn.execute("SELECT user_id, username, custom_name, balance_lc FROM users WHERE is_banned=0 ORDER BY balance_lc DESC LIMIT 10").fetchall()
    text = "💰 Топ богачей\n\n"
    for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    await message.answer(text)

@router.message(F.text.lower().startswith("рул"))
async def roulette_game(message: Message):
    parts = message.text.split()
    if len(parts)<3: await message.answer("❌ рул [ставка] [цвет/число]"); return
    try: bet = int(parts[2])
    except: await message.answer("❌ Число"); return
    user = db.get_user(message.from_user.id)
    if not user: await message.answer("❌ /start"); return
    if bet<MIN_BET or bet>user['balance_lc']: await message.answer("❌ Недостаточно"); return
    db.update_balance(message.from_user.id, -bet)
    result = random.randint(0,36)
    win, mult = check_roulette_win(parts[1], result)
    if win:
        win_amt = bet * mult
        db.update_balance(message.from_user.id, win_amt)
        db.add_game_stat(message.from_user.id, "roulette", True, bet, win_amt)
        await message.answer(f"🎉 Выиграл! {result} x{mult} +{win_amt} LC")
    else:
        db.add_game_stat(message.from_user.id, "roulette", False, bet, 0)
        await message.answer(f"💔 Проиграл! {result} -{bet} LC")

@router.message(F.text.lower().startswith("слоты"))
async def slots_game(message: Message):
    parts = message.text.split()
    if len(parts)<2: await message.answer("❌ слоты [ставка]"); return
    try: bet = int(parts[1])
    except: await message.answer("❌ Число"); return
    user = db.get_user(message.from_user.id)
    if not user or bet>user['balance_lc']: await message.answer("❌ Недостаточно"); return
    db.update_balance(message.from_user.id, -bet)
    val = random.randint(1,64)
    if val in SLOT_VALUES:
        win = bet * SLOT_VALUES[val]
        db.update_balance(message.from_user.id, win)
        db.add_game_stat(message.from_user.id, "slots", True, bet, win)
        await message.answer(f"🎉 Джекпот! +{win} LC")
    else:
        db.add_game_stat(message.from_user.id, "slots", False, bet, 0)
        await message.answer(f"💔 Проиграл! -{bet} LC")

@router.message(F.text.lower().startswith("мины"))
async def mines_game(message: Message):
    await message.answer("💣 Мины в разработке")

@router.message(F.text.lower().startswith("кости"))
async def dice_game(message: Message):
    await message.answer("🎲 Кости в разработке")

@router.message(F.text.lower().startswith("бджек"))
async def blackjack_game(message: Message):
    await message.answer("🃏 Блэкджек в разработке")

# ==================== ЗАПУСК ====================
async def draw_lottery(bot):
    week = f"{datetime.now().year}-{datetime.now().isocalendar()[1]}"
    conn = db.get_connection()
    tickets = conn.execute("SELECT user_id, ticket_count FROM lottery_tickets WHERE week_number = ?", (week,)).fetchall()
    if not tickets: return
    pool = [t[0] for t in tickets for _ in range(t[1])]
    random.shuffle(pool)
    winners = []
    for _ in range(3):
        if pool: w = random.choice(pool)
        else: break
        while w in [x['user_id'] for x in winners] and pool: w = random.choice(pool)
        winners.append({'user_id': w, 'prize': [100000,30000,15000][_] if _<3 else 0})
    for w in winners:
        db.update_balance(w['user_id'], w['prize'])
    await bot.send_message(CHANNEL_ID, f"🎟 Лотерея\n🥇 {winners[0]['user_id']} - {winners[0]['prize']} LC\n🥈 {winners[1]['user_id']} - {winners[1]['prize']} LC\n🥉 {winners[2]['user_id']} - {winners[2]['prize']} LC")
    conn.execute("DELETE FROM lottery_tickets WHERE week_number = ?", (week,))
    conn.commit()

async def create_start_promos():
    conn = db.get_connection()
    conn.execute("INSERT OR IGNORE INTO promocodes (code, reward, max_uses) VALUES ('NEW', 2500, 1)")
    conn.execute("INSERT OR IGNORE INTO promocodes (code, reward, max_uses) VALUES ('mëpтв', 25000, 25)")
    conn.commit()

async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    
    await create_start_promos()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(draw_lottery, 'cron', day_of_week='sun', hour=20, minute=0, args=[bot])
    scheduler.start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
