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
        if 'is_admin_verified' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_admin_verified INTEGER DEFAULT 0")
            conn.commit()
        if 'is_sponsor' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_sponsor INTEGER DEFAULT 0")
            conn.commit()
        if 'sponsor_name' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN sponsor_name TEXT DEFAULT ''")
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
                total_lost INTEGER DEFAULT 0,
                is_admin_verified INTEGER DEFAULT 0,
                is_sponsor INTEGER DEFAULT 0,
                sponsor_name TEXT DEFAULT ''
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
    builder.row(
        InlineKeyboardButton(text="🏪 Ларек у дома 24/7 (20к LC)", callback_data="buy_small"),
        InlineKeyboardButton(text="🍺 Пивнуха (50к LC)", callback_data="buy_medium")
    )
    builder.row(
        InlineKeyboardButton(text="🏭 Завод по производству металла (100к LC)", callback_data="buy_large"),
        InlineKeyboardButton(text="🏦 Банк (500₽)", callback_data="buy_paid")
    )
    builder.row(
        InlineKeyboardButton(text="💰 Собрать", callback_data="collect_business"),
        InlineKeyboardButton(text="📊 Мой бизнес", callback_data="my_business")
    )
    builder.row(
        InlineKeyboardButton(text="💵 Продать бизнес", callback_data="sell_business"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")
    )
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

# ==================== СТАТУСЫ ИГРОКОВ (ТОПЫ) ====================
def update_user_status(user_id: int):
    """Обновление статусов пользователя (топы)"""
    conn = db.get_connection()
    
    # Топ богачей
    rich_top = conn.execute("""
        SELECT user_id FROM users 
        WHERE is_banned = 0 
        ORDER BY balance_lc DESC 
        LIMIT 1
    """).fetchone()
    rich_top = rich_top[0] if rich_top else None
    
    # Топы по играм
    games = ['roulette', 'slots', 'dice', 'mines', 'lottery', 'blackjack']
    tops = {'rich': rich_top}
    
    STATUS_ICONS = {
        "roulette": "🃏",
        "slots": "🎰",
        "dice": "🎲",
        "mines": "💣",
        "lottery": "🎟️",
        "blackjack": "🃏",
        "rich": "💰"
    }
    
    for game in games:
        top = conn.execute("""
            SELECT user_id FROM game_stats 
            WHERE game_type = ?
            GROUP BY user_id
            ORDER BY SUM(win_amount) DESC 
            LIMIT 1
        """, (game,)).fetchone()
        tops[game] = top[0] if top else None
    
    user_status = ""
    if tops['rich'] == user_id:
        user_status += STATUS_ICONS['rich']
    
    for game in games:
        if tops.get(game) == user_id:
            user_status += STATUS_ICONS[game]
    
    conn.execute("""
        INSERT INTO user_status (user_id, status)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET status = ?, updated_at = CURRENT_TIMESTAMP
    """, (user_id, user_status, user_status))
    conn.commit()
    
    return user_status

def get_user_status(user_id: int) -> str:
    """Получить статус пользователя (иконки за топы)"""
    conn = db.get_connection()
    cursor = conn.execute(
        "SELECT status FROM user_status WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    return row[0] if row else ""

# ==================== ИГРЫ (ЛОГИКА) ====================
# Рулетка
BLACK_NUMBERS = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]
RED_NUMBERS = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
ROW1 = [1,4,7,10,13,16,19,22,25,28,31,34]
ROW2 = [2,5,8,11,14,17,20,23,26,29,32,35]
ROW3 = [3,6,9,12,15,18,21,24,27,30,33,36]
COLUMNS = {i: [i*3-2, i*3-1, i*3] for i in range(1,13)}
RANGE1_12 = list(range(1,13))
RANGE13_24 = list(range(13,25))
RANGE25_36 = list(range(25,37))
RANGE1_18 = list(range(1,19))
RANGE19_36 = list(range(19,37))
EVEN = [x for x in range(1,37) if x%2==0]
ODD = [x for x in range(1,37) if x%2!=0]

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

# Мины
GRID_SIZE = 5
MULTIPLIERS = {1:1.2,2:1.5,3:2.0,4:2.5,5:3.2,6:4.0,7:5.0,8:6.5,9:8.0,10:10.0,11:12.5,12:15.0,13:18.0,14:22.0,15:27.0,16:33.0,17:40.0,18:50.0,19:65.0,20:85.0,21:110.0,22:150.0,23:200.0,24:300.0}

# Блэкджек
CARD_VALUES = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':10,'Q':10,'K':10,'A':11}
CARDS = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
SUITS = ['♥️', '♦️', '♣️', '♠️']

def create_deck():
    deck = [f"{c}{s}" for s in SUITS for c in CARDS]
    random.shuffle(deck)
    return deck

def card_value(card):
    if card.startswith('10'): return 10
    val = card[0]
    return CARD_VALUES.get(val, 0)

def hand_score(hand):
    total = 0
    aces = 0
    for c in hand:
        v = card_value(c)
        if v == 11:
            aces += 1
            total += 11
        else:
            total += v
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def hand_to_string(hand):
    return ' '.join(hand)

# ==================== СОСТОЯНИЯ ДЛЯ ИГР ====================
class MinesState(StatesGroup):
    playing = State()

class BlackjackState(StatesGroup):
    playing = State()

# Хранилище активных дуэлей
active_duels = {}

# ==================== РОУТЕР ====================
router = Router()

# ==================== РЕГИСТРАЦИЯ ====================
class Registration(StatesGroup):
    waiting_for_name = State()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if not is_private(message):
        await message.answer("❌ Команда /start доступна только в личных сообщениях!")
        return
    user_id = message.from_user.id
    user = db.get_user(user_id)
    if not user:
        await state.set_state(Registration.waiting_for_name)
        await message.answer(
            "👋 <b>Добро пожаловать в Лудик!</b>\n\n"
            "Для начала игры придумай себе имя (никнейм).\n"
            "Оно будет отображаться в топах и статистике.\n\n"
            "✏️ <b>Введи имя (до 10 символов):</b>"
        )
        return
    if user['is_banned']:
        await message.answer(f"⛔ Вы заблокированы! Причина: {user['ban_reason']}\nОбратитесь к {ADMIN_USERNAME}")
        return
    try:
        cm = await message.bot.get_chat_member(CHANNEL_ID, user_id)
        if cm.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await message.answer(f"🔒 <b>Для доступа к играм нужно подписаться на канал!</b>\n\n👉 {CHANNEL_LINK}\n\nПосле подписки нажми /play", reply_markup=get_start_keyboard())
        else:
            await message.answer(f"🎲 <b>С возвращением, {user.get('custom_name', user['username'])}!</b>\n\n💰 Твой баланс: {user['balance_lc']} #LC", reply_markup=get_main_menu())
    except:
        await message.answer(f"🎲 <b>С возвращением, {user.get('custom_name', user['username'])}!</b>\n\n💰 Твой баланс: {user['balance_lc']} #LC", reply_markup=get_main_menu())

@router.message(Registration.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) > 10:
        await message.answer("❌ Имя слишком длинное! Максимум 10 символов.")
        return
    if len(name) < 2:
        await message.answer("❌ Имя слишком короткое! Минимум 2 символа.")
        return
    if not all(c.isalnum() or c == '_' for c in name):
        await message.answer("❌ Имя может содержать только буквы, цифры и символ подчеркивания (_).")
        return
    db.create_user_with_name(message.from_user.id, message.from_user.username or "NoUsername", message.from_user.first_name, name, None)
    await message.answer(
        f"🎰 <b>Добро пожаловать в Лудик {BOT_VERSION}!</b>\n\n"
        f"Привет, {name}!\n"
        f"Мир азарта и больших выигрышей ждет тебя! 🎲\n\n"
        f"👑 Владелец: {ADMIN_USERNAME}\n"
        f"📅 Релиз: {BOT_RELEASE_DATE}\n"
        f"📊 Версия: {BOT_VERSION}\n\n"
        f"👇 Выбери действие в меню ниже:",
        reply_markup=get_main_menu()
    )
    await state.clear()

@router.message(Command("play"))
async def cmd_play(message: Message):
    if not is_private(message):
        await message.answer("❌ Эта команда доступна только в личных сообщениях")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    if user['is_banned']:
        await message.answer("⛔ Вы заблокированы!")
        return
    try:
        cm = await message.bot.get_chat_member(CHANNEL_ID, message.from_user.id)
        if cm.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await message.answer(f"🔒 <b>Ты не подписан на канал!</b>\n\n👉 {CHANNEL_LINK}", reply_markup=get_start_keyboard())
        else:
            await message.answer("🎮 Игровой зал:", reply_markup=get_main_menu())
    except:
        await message.answer("🎮 Игровой зал:", reply_markup=get_main_menu())

# ==================== /help ====================
@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "🎮 <b>Помощь по играм и командам</b>\n\n"
        
        "🃏 <b>Рулетка</b>\n"
        "Команда: <code>рул [цвет/число] [ставка]</code>\n"
        "Пример: <code>рул красное 1000</code>\n"
        "Ставки: красное/черное (x2), число (x36), ряд (x3), диапазон (x3), чёт/нечёт (x2), столбец (x12)\n\n"
        
        "🎰 <b>Слоты</b>\n"
        "Команда: <code>слоты [ставка]</code>\n"
        "Пример: <code>слоты 1000</code>\n"
        "Выигрыши: 7️⃣7️⃣7️⃣ (x10), 💎💎💎 (x5), 🍋🍋🍋 (x3), 🍒🍒🍒 (x3)\n\n"
        
        "🎲 <b>Кости (дуэль)</b>\n"
        "Команда: <code>кости [ставка]</code>\n"
        "Пример: <code>кости 1000</code>\n"
        "Правила: создаёшь дуэль → другой игрок принимает → бот кидает кости → у кого больше очков, тот забирает банк\n\n"
        
        "💣 <b>Мины</b>\n"
        "Команда: <code>мины [ставка]</code>\n"
        "Пример: <code>мины 1000</code>\n"
        "Правила: открывай клетки, чем больше открыл — тем выше множитель. Попал на мину — проигрыш\n\n"
        
        "🃏 <b>Блэкджек (21)</b>\n"
        "Команда: <code>бджек [ставка]</code>\n"
        "Пример: <code>бджек 1000</code>\n"
        "Правила: набери 21 или ближе к дилеру. Туз = 11 или 1, J/Q/K = 10\n\n"
        
        "🎟 <b>Лотерея</b>\n"
        "Команды: <code>/купить [кол-во]</code>, <code>/моибилеты</code>\n"
        "Пример: <code>/купить 5</code>\n"
        "Цена билета: 10000 LC. Призы: 100k, 30k, 15k LC. Розыгрыш каждое воскресенье\n\n"
        
        "💼 <b>Бизнес</b>\n"
        "Меню: 💼 Бизнес\n"
        "Правила: инвестируй LC и получай ежедневный доход. Можно продать за 50% стоимости\n\n"
        
        "💰 <b>GLC (премиум валюта)</b>\n"
        "Команда: <code>/glc</code>\n"
        "Как получить: рефералы (+100), донаты (+10 за 10₽), бонусы, серии побед\n"
        "Тратить: на уникальные статусы в магазине\n\n"
        
        "👥 <b>Реферальная система</b>\n"
        "Команда: <code>/referral</code>\n"
        "Правила: приглашай друзей по ссылке, получай +1000 LC и +100 GLC за каждого\n\n"
        
        "💸 <b>Переводы</b>\n"
        "Команда: <code>/перевод @username сумма</code>\n"
        "Пример: <code>/перевод @friend 1000</code>\n\n"
        
        "🎁 <b>Бонус</b>\n"
        "Кнопка: 🎁 Бонус\n"
        "Правила: раз в 5 часов можно получить от 1000 до 10000 LC\n\n"
        
        "🏆 <b>Топы</b>\n"
        "Команды: /tb (богачи), /tr (рулетка), /ts (слоты), /tk (кости), /tm (мины), /tl (лотерея), /tbj (блэкджек)\n\n"
        
        "ℹ️ <b>Другое</b>\n"
        "<code>/my</code> — моя статистика\n"
        "<code>/promo [код]</code> — активировать промокод\n"
        "<code>/donate</code> — информация о донате\n\n"
        
        f"💰 <b>Баланс:</b> /my\n"
        f"👑 <b>Владелец:</b> {ADMIN_USERNAME}\n"
        f"📊 <b>Версия:</b> {BOT_VERSION}"
    )
    # Добавляем админ-команды, если пользователь админ
    if is_admin(message.from_user.id):
        text += "\n\n👑 <b>Админ-команды:</b>\n"
        text += "<code>/add_glc [id] [сумма]</code> — выдать GLC\n"
        text += "<code>/verify_admin [id]</code> — выдать статус администратора\n"
        text += "<code>/unverify_admin [id]</code> — снять статус администратора\n"
        text += "<code>/verify_player [id] [название]</code> — выдать статус спонсора\n"
        text += "<code>/unverify_player [id]</code> — снять статус спонсора\n"
    
    await message.answer(text)

# ==================== ОБРАБОТЧИКИ МЕНЮ ====================
@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("🎮 Главное меню:", reply_markup=get_main_menu())
    await callback.answer()

@router.callback_query(F.data == "casino_menu")
async def casino_menu(callback: CallbackQuery):
    await callback.message.edit_text("🎰 <b>Казино Лудик</b>\n\nВыбери игру:", reply_markup=get_casino_menu())
    await callback.answer()

@router.callback_query(F.data == "lottery_menu")
async def lottery_menu(callback: CallbackQuery):
    now = datetime.now()
    week = f"{now.year}-{now.isocalendar()[1]}"
    conn = db.get_connection()
    total = conn.execute("SELECT COALESCE(SUM(ticket_count),0) FROM lottery_tickets WHERE week_number = ?", (week,)).fetchone()[0]
    user_tickets = conn.execute("SELECT COALESCE(ticket_count,0) FROM lottery_tickets WHERE user_id = ? AND week_number = ?", (callback.from_user.id, week)).fetchone()[0]
    weekday = now.weekday()
    if weekday >= 6:
        days = (7 - weekday + 0) % 7 or 7
        next_draw = now + timedelta(days=days)
        status = f"📅 Следующий розыгрыш: {next_draw.strftime('%d.%m.%Y')} (воскресенье)"
    else:
        status = "📅 Продажа билетов до воскресенья"
    text = (
        f"🎟 <b>ЛОТЕРЕЯ</b>\n\n{status}\n\n"
        f"💰 <b>Цена билета:</b> 10000 LC\n"
        f"🎫 <b>Продано билетов:</b> {total} шт.\n"
        f"👤 <b>Твои билеты:</b> {user_tickets} шт.\n\n"
        f"🏆 <b>ПРИЗЫ:</b>\n🥇 1 место: 100000 LC\n🥈 2 место: 30000 LC\n🥉 3 место: 15000 LC\n\n"
        f"👇 Купить билеты командой:\n<code>/купить 1</code> — купить 1 билет\n<code>/купить 5</code> — купить 5 билетов"
    )
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "donate_menu")
async def donate_menu(callback: CallbackQuery):
    text = (
        "💰 <b>ДОНАТ</b>\n\nПополни баланс и получи бонус!\n\n<b>Тарифы:</b>\n"
        "• 100₽ — 20000 #LC\n• 200₽ — 30000 #LC\n• 300₽ — 40000 #LC\n"
        "• 400₽ — 50000 #LC\n• 500₽ — 60000 #LC\n• 600₽ — 70000 #LC\n"
        "• 700₽ — 80000 #LC\n• 800₽ — 90000 #LC\n• 900₽ — 100000 #LC\n"
        "• 1000₽ — 110000 #LC\n\n💎 <b>Специальное предложение:</b>\n"
        f"• 500₽ — Банк (50к #LC/день)\n\nДля оплаты напиши админу: {ADMIN_USERNAME}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router.callback_query(F.data == "get_bonus")
async def get_bonus_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    last = user.get('last_bonus')
    if last:
        diff = datetime.now() - datetime.strptime(last, '%Y-%m-%d %H:%M:%S')
        if diff.total_seconds() < BONUS_COOLDOWN:
            hours = (BONUS_COOLDOWN - diff.total_seconds()) / 3600
            await callback.answer(f"⏳ Бонус через {hours:.1f} ч", show_alert=True)
            return
    bonus = random.randint(BONUS_MIN, BONUS_MAX)
    db.update_balance(callback.from_user.id, bonus)
    conn = db.get_connection()
    conn.execute("UPDATE users SET last_bonus = datetime('now') WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    await callback.answer(f"🎁 +{bonus} LC", show_alert=True)
    await callback.message.edit_text(f"🎁 <b>Бонус получен!</b>\n\n+{bonus} LC\n💰 Баланс: {db.get_user(callback.from_user.id)['balance_lc']} LC\n\nСледующий бонус через 5 часов.", reply_markup=get_back_button())

@router.callback_query(F.data == "business_menu")
async def business_menu_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    conn = db.get_connection()
    biz = conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    text = "💼 <b>Бизнес система</b>\n\n"
    if biz:
        names = {"small":"🏪 Ларек у дома 24/7","medium":"🍺 Пивнуха","large":"🏭 Завод по производству металла","paid":"🏦 Банк"}
        prices = {"small":20000,"medium":50000,"large":100000,"paid":500}
        daily = {"small":2500,"medium":5500,"large":10500,"paid":50000}
        currency = {"small":"LC","medium":"LC","large":"LC","paid":"₽"}
        text += f"✅ У тебя есть: {names.get(biz[1])}\n"
        last = datetime.strptime(biz[2], '%Y-%m-%d %H:%M:%S')
        hours = (datetime.now() - last).total_seconds() / 3600
        if hours >= 24:
            text += "💰 Доступен сбор дохода!"
        else:
            text += f"⏳ Следующий сбор через: {24 - hours:.1f} ч."
        text += f"\n\n💵 Можно продать за {prices.get(biz[1],0)//2} {currency.get(biz[1], 'LC')} (50%)"
    else:
        text += "У тебя пока нет бизнеса.\nКупи один из вариантов ниже:"
    await callback.message.edit_text(text, reply_markup=get_business_menu())
    await callback.answer()

@router.callback_query(F.data == "my_stats")
async def my_stats_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    conn = db.get_connection()
    stats = conn.execute("SELECT game_type, COUNT(*) as total, SUM(CASE WHEN win THEN 1 ELSE 0 END) as wins FROM game_stats WHERE user_id = ? GROUP BY game_type", (callback.from_user.id,)).fetchall()
    stats_dict = {s[0]: {"wins": s[2], "losses": s[1]-s[2], "total": s[1]} for s in stats}
    def get_stat(game): s = stats_dict.get(game, {"wins":0,"losses":0,"total":0}); return f"{s['wins']}💰 / {s['losses']}💔 / {s['total']} ставок"
    
    # Получаем GLC статусы
    glc_statuses = db.get_user_glc_statuses(callback.from_user.id)
    glc_icon = glc_statuses[0]['status_icon'] if glc_statuses else ""
    
    # Получаем эксклюзивные статусы за топы
    game_status = get_user_status(callback.from_user.id)
    
    # Получаем статусы верификации
    admin_verified = user.get('is_admin_verified', 0)
    is_sponsor = user.get('is_sponsor', 0)
    sponsor_name = user.get('sponsor_name', '')
    
    # Формируем имя с GLC статусом
    display_name = user.get('custom_name', user['username'])
    if glc_icon:
        display_name = f"{glc_icon} {display_name}"
    
    text = (
        f"👤 <b>Пользователь:</b> {display_name} | ID: {callback.from_user.id}\n"
    )
    
    # Отображаем эксклюзивные статусы за топы
    if game_status:
        text += f"🏆 <b>Статусы:</b> {game_status}\n\n"
    else:
        text += f"\n"
    
    text += (
        f"📈 <b>Общая статистика:</b>\n\n"
        f"🃏 Рулетка: {get_stat('roulette')}\n"
        f"🎰 Слоты: {get_stat('slots')}\n"
        f"🎲 Кости: {get_stat('dice')}\n"
        f"💣 Мины: {get_stat('mines')}\n"
        f"🎟 Лотерея: {get_stat('lottery')}\n"
        f"🃏 Блэкджек: {get_stat('blackjack')}\n\n"
        f"🪙 Баланс LC: {user['balance_lc']}\n"
        f"💰 Баланс GLC: {user['balance_glc']}\n\n"
        f"😭 Всего проиграно: {user['total_lost']} LC\n"
    )
    
    if admin_verified:
        text += "\n✅ <b>Этот аккаунт верифицирован и является администратором бота.</b>\n"
    if is_sponsor:
        text += f"\n☑️ <b>Данный игрок является спонсором бота: {sponsor_name}</b>\n"
    
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "top_menu")
async def top_menu_callback(callback: CallbackQuery):
    await callback.message.edit_text("🏆 <b>Выбери категорию топов:</b>", reply_markup=get_top_menu())
    await callback.answer()

@router.callback_query(F.data.startswith("top_"))
async def top_category_callback(callback: CallbackQuery):
    top_type = callback.data.replace("top_", "")
    conn = db.get_connection()
    if top_type == "balance":
        rows = conn.execute("SELECT user_id, username, custom_name, balance_lc FROM users WHERE is_banned=0 ORDER BY balance_lc DESC LIMIT 10").fetchall()
        text = "💰 <b>Топ богачей</b>\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif top_type == "roulette":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='roulette' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🃏 <b>Топ рулетки</b>\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif top_type == "slots":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='slots' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🎰 <b>Топ слотов</b>\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif top_type == "dice":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='dice' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🎲 <b>Топ костей</b>\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif top_type == "mines":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='mines' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "💣 <b>Топ мин</b>\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif top_type == "lottery":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='lottery' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🎟 <b>Топ лотереи</b>\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif top_type == "blackjack":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='blackjack' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🃏 <b>Топ блэкджека</b>\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    else:
        await callback.answer("❌ Неизвестный топ")
        return
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "activate_promo")
async def activate_promo_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎫 <b>Активация промокода</b>\n\nВведи промокод командой:\n<code>/promo КОД</code>\n\nПример: <code>/promo NEW</code>",
        reply_markup=get_back_button()
    )
    await callback.answer()

@router.callback_query(F.data == "referral_menu")
async def referral_menu_callback(callback: CallbackQuery):
    bot = callback.bot
    bot_name = (await bot.me()).username
    link = f"https://t.me/{bot_name}?start=ref_{callback.from_user.id}"
    conn = db.get_connection()
    refs = conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (callback.from_user.id,)).fetchone()[0]
    donat = conn.execute("SELECT COALESCE(SUM(donat_amount),0) FROM referrals WHERE referrer_id = ?", (callback.from_user.id,)).fetchone()[0]
    text = (
        f"👥 <b>Реферальная система</b>\n\n"
        f"📊 Твоя статистика:\n"
        f"👤 Приглашено: {refs} чел.\n"
        f"💰 Донатов рефералов: {donat} ₽\n"
        f"💎 Твой бонус: {donat * 10} LC (10%)\n\n"
        f"🔗 Твоя ссылка:\n<code>{link}</code>\n\n"
        f"За каждого приглашенного ты получаешь 1000 LC\n"
        f"Если реферал донатит, ты получаешь 10% от его доната в LC"
    )
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "glc_info")
async def glc_info_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    statuses = db.get_user_glc_statuses(callback.from_user.id)
    stext = "\n".join([f"• {s['status_icon']} {s['status_name']}" for s in statuses]) or "У тебя нет купленных статусов"
    text = (
        f"💰 <b>GLC — Премиальная валюта</b>\n\n"
        f"Твой баланс GLC: {user['balance_glc']} #GLC\n\n"
        f"{stext}\n\n"
        f"<b>Как получить GLC:</b>\n"
        f"• 👥 За реферала: +100 GLC\n"
        f"• 💵 За донат: +10 GLC за каждые 10₽\n"
        f"• 📅 В ежедневном бонусе: шанс получить GLC\n"
        f"• 🔥 За серию побед (5+): +50 GLC\n\n"
        f"<b>На что потратить GLC:</b>\n"
        f"• 👑 Уникальные статусы (магазин ниже)"
    )
    await callback.message.edit_text(text, reply_markup=get_glc_menu())
    await callback.answer()

@router.callback_query(F.data == "glc_balance")
async def glc_balance_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    await callback.message.edit_text(f"💰 <b>Твой GLC:</b> {user['balance_glc']} #GLC", reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "glc_shop")
async def glc_shop_callback(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован")
        return
    owned = db.get_user_glc_statuses(callback.from_user.id)
    owned_keys = [s['status_key'] for s in owned]
    await callback.message.edit_text(
        f"🛒 <b>Магазин статусов</b>\n\nТвой баланс GLC: {user['balance_glc']}\nСтраница 1/{TOTAL_PAGES}\n\nВыбери статус для покупки:",
        reply_markup=get_glc_shop_page(1, TOTAL_PAGES, STATUS_PAGES[0], owned_keys)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("shop_page_"))
async def shop_page_callback(callback: CallbackQuery):
    page = int(callback.data.replace("shop_page_", ""))
    user = db.get_user(callback.from_user.id)
    owned = db.get_user_glc_statuses(callback.from_user.id)
    owned_keys = [s['status_key'] for s in owned]
    await callback.message.edit_text(
        f"🛒 <b>Магазин статусов</b>\n\nТвой баланс GLC: {user['balance_glc']}\nСтраница {page}/{TOTAL_PAGES}\n\nВыбери статус для покупки:",
        reply_markup=get_glc_shop_page(page, TOTAL_PAGES, STATUS_PAGES[page-1], owned_keys)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("buy_status_"))
async def buy_status_callback(callback: CallbackQuery):
    key = callback.data.replace("buy_status_", "")
    if key not in GLC_STATUSES:
        await callback.answer("❌ Статус не найден")
        return
    status = GLC_STATUSES[key]
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    if user['balance_glc'] < status['price']:
        await callback.answer(f"❌ Недостаточно GLC! Нужно {status['price']}", show_alert=True)
        return
    if db.has_glc_status(callback.from_user.id, key):
        await callback.answer("❌ У тебя уже есть этот статус!", show_alert=True)
        return
    conn = db.get_connection()
    conn.execute("UPDATE users SET balance_glc = balance_glc - ? WHERE user_id = ?", (status['price'], callback.from_user.id))
    conn.execute("INSERT INTO glc_statuses (user_id, status_key, status_name, status_icon) VALUES (?, ?, ?, ?)", (callback.from_user.id, key, status['name'], status['icon']))
    conn.commit()
    await callback.answer(f"✅ Куплен статус {status['icon']} {status['name']}!", show_alert=True)
    owned = db.get_user_glc_statuses(callback.from_user.id)
    owned_keys = [s['status_key'] for s in owned]
    await callback.message.edit_text(
        f"🛒 <b>Магазин статусов</b>\n\nТвой баланс GLC: {user['balance_glc'] - status['price']}\nСтраница 1/{TOTAL_PAGES}\n\nВыбери статус для покупки:",
        reply_markup=get_glc_shop_page(1, TOTAL_PAGES, STATUS_PAGES[0], owned_keys)
    )

@router.callback_query(F.data == "info")
async def info_callback(callback: CallbackQuery):
    text = (
        f"<b>Информация о боте \"Лудик {BOT_VERSION}\"</b>\n\n"
        f"👑 <b>Владелец:</b> {ADMIN_USERNAME}\n"
        f"📅 <b>Релиз:</b> {BOT_RELEASE_DATE}\n"
        f"📊 <b>Версия:</b> {BOT_VERSION}\n\n"
        f"⚠️ <b>ВНИМАНИЕ:</b>\n"
        f"• Денежные средства не возвращаются.\n"
        f"• Вывод средств не предусмотрен.\n"
        f"• Играйте ответственно!"
    )
    await callback.message.edit_text(text, reply_markup=get_start_keyboard())
    await callback.answer()

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    try:
        cm = await callback.bot.get_chat_member(CHANNEL_ID, callback.from_user.id)
        if cm.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
            await callback.answer("❌ Ты все еще не подписан!", show_alert=True)
        else:
            await callback.answer("✅ Подписка подтверждена! Игры доступны.", show_alert=True)
            await callback.message.edit_text("🎮 Игровой зал:", reply_markup=get_main_menu())
    except:
        await callback.answer("❌ Ошибка проверки", show_alert=True)

# ==================== ИГРЫ (КОМАНДЫ) ====================
@router.message(Command("promo"))
async def cmd_promo(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /promo КОД")
        return
    code = args[1]
    conn = db.get_connection()
    promo = conn.execute("SELECT * FROM promocodes WHERE code = ?", (code,)).fetchone()
    if not promo:
        await message.answer("❌ Промокод не найден")
        return
    if promo[3] >= promo[2]:
        await message.answer("❌ Лимит использований исчерпан")
        return
    used = conn.execute("SELECT * FROM used_promocodes WHERE user_id = ? AND code = ?", (message.from_user.id, code)).fetchone()
    if used:
        await message.answer("❌ Ты уже активировал этот промокод")
        return
    conn.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    conn.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?, ?)", (message.from_user.id, code))
    conn.commit()
    new_balance = db.update_balance(message.from_user.id, promo[1])
    await message.answer(f"✅ Промокод активирован!\nТы получил: +{promo[1]} LC\n💰 Текущий баланс: {new_balance} LC")

@router.message(Command("купить"))
async def buy_tickets(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /купить [количество]")
        return
    try:
        count = int(args[1])
    except:
        await message.answer("❌ Количество должно быть числом")
        return
    if count <= 0:
        await message.answer("❌ Некорректное количество")
        return
    if datetime.now().weekday() >= 6:
        await message.answer("❌ Розыгрыш уже прошел! Жди следующего воскресенья 🎟")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    total_cost = count * 10000
    if user['balance_lc'] < total_cost:
        await message.answer(f"❌ Недостаточно средств! Нужно {total_cost} LC")
        return
    week = f"{datetime.now().year}-{datetime.now().isocalendar()[1]}"
    conn = db.get_connection()
    db.update_balance(message.from_user.id, -total_cost)
    conn.execute("INSERT INTO lottery_tickets (user_id, week_number, ticket_count) VALUES (?, ?, ?) ON CONFLICT(user_id, week_number) DO UPDATE SET ticket_count = ticket_count + ?", (message.from_user.id, week, count, count))
    conn.commit()
    total_tickets = conn.execute("SELECT COALESCE(SUM(ticket_count),0) FROM lottery_tickets WHERE week_number = ?", (week,)).fetchone()[0]
    await message.answer(f"✅ Билеты куплены!\n🎫 Куплено: {count} шт.\n💰 Потрачено: {total_cost} LC\n📊 Всего билетов: {total_tickets} шт.\n\n🍀 Удачи в воскресенье!")

@router.message(Command("моибилеты"))
async def my_tickets(message: Message):
    week = f"{datetime.now().year}-{datetime.now().isocalendar()[1]}"
    conn = db.get_connection()
    tickets = conn.execute("SELECT ticket_count FROM lottery_tickets WHERE user_id = ? AND week_number = ?", (message.from_user.id, week)).fetchone()
    total = conn.execute("SELECT COALESCE(SUM(ticket_count),0) FROM lottery_tickets WHERE week_number = ?", (week,)).fetchone()[0]
    await message.answer(f"🎫 <b>Твои билеты</b>\n\nТекущая лотерея:\n• У тебя: {tickets[0] if tickets else 0} билетов\n• Всего продано: {total} билетов")

@router.message(Command("перевод"))
async def transfer_cmd(message: Message):
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Использование: /перевод @username сумма")
        return
    username = args[1].replace('@', '')
    try:
        amount = int(args[2])
    except:
        await message.answer("❌ Сумма должна быть числом")
        return
    if amount < MIN_BET:
        await message.answer(f"❌ Минимальная сумма перевода: {MIN_BET} LC")
        return
    receiver = db.get_user_by_username(username)
    if not receiver:
        await message.answer("❌ Пользователь не найден")
        return
    if receiver['user_id'] == message.from_user.id:
        await message.answer("❌ Нельзя переводить самому себе")
        return
    success, msg = db.transfer_lc(message.from_user.id, receiver['user_id'], amount)
    if success:
        await message.answer(f"✅ Перевод выполнен!\nКому: @{username}\nСумма: {amount} LC")
        try:
            await message.bot.send_message(receiver['user_id'], f"💰 Тебе перевели LC!\nОт кого: @{message.from_user.username}\nСумма: +{amount} LC")
        except:
            pass
    else:
        await message.answer(f"❌ {msg}")

@router.message(Command("donate"))
async def donate_cmd(message: Message):
    text = (
        "💰 <b>ДОНАТ</b>\n\nПополни баланс и получи бонус!\n\n<b>Тарифы:</b>\n"
        "• 100₽ — 20000 #LC\n• 200₽ — 30000 #LC\n• 300₽ — 40000 #LC\n"
        "• 400₽ — 50000 #LC\n• 500₽ — 60000 #LC\n• 600₽ — 70000 #LC\n"
        "• 700₽ — 80000 #LC\n• 800₽ — 90000 #LC\n• 900₽ — 100000 #LC\n"
        "• 1000₽ — 110000 #LC\n\n💎 <b>Специальное предложение:</b>\n"
        f"• 500₽ — Банк (50к #LC/день)\n\nДля оплаты напиши админу: {ADMIN_USERNAME}"
    )
    await message.answer(text)

@router.message(Command("my"))
async def my_cmd(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    
    # Получаем эксклюзивные статусы за топы
    game_status = get_user_status(message.from_user.id)
    
    # Получаем GLC статусы
    glc_statuses = db.get_user_glc_statuses(message.from_user.id)
    glc_icon = glc_statuses[0]['status_icon'] if glc_statuses else ""
    
    admin_verified = user.get('is_admin_verified', 0)
    is_sponsor = user.get('is_sponsor', 0)
    sponsor_name = user.get('sponsor_name', '')
    
    text = f"🪙 Баланс LC: {user['balance_lc']}\n💰 Баланс GLC: {user['balance_glc']}\n"
    
    if game_status:
        text += f"\n🏆 <b>Твои статусы:</b> {game_status}\n"
    
    if admin_verified:
        text += "\n✅ Вы верифицированный администратор!"
    if is_sponsor:
        text += f"\n☑️ Вы являетесь спонсором бота: {sponsor_name}"
    
    await message.answer(text)

@router.message(Command("tb", "tr", "ts", "tk", "tm", "tl", "tbj"))
async def top_cmd(message: Message):
    cmd = message.text[1:]
    conn = db.get_connection()
    if cmd == "tb":
        rows = conn.execute("SELECT user_id, username, custom_name, balance_lc FROM users WHERE is_banned=0 ORDER BY balance_lc DESC LIMIT 10").fetchall()
        text = "💰 Топ богачей\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif cmd == "tr":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='roulette' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🃏 Топ рулетки\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif cmd == "ts":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='slots' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🎰 Топ слотов\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif cmd == "tk":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='dice' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🎲 Топ костей\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif cmd == "tm":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='mines' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "💣 Топ мин\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif cmd == "tl":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='lottery' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🎟 Топ лотереи\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    elif cmd == "tbj":
        rows = conn.execute("SELECT u.user_id, u.username, u.custom_name, COALESCE(SUM(g.win_amount),0) as won FROM users u LEFT JOIN game_stats g ON u.user_id=g.user_id AND g.game_type='blackjack' AND g.win=1 WHERE u.is_banned=0 GROUP BY u.user_id ORDER BY won DESC LIMIT 10").fetchall()
        text = "🃏 Топ блэкджека\n\n"
        for i,r in enumerate(rows,1): text += f"{i}. {r[2] or r[1] or f'id{r[0]}'} — {r[3]} LC\n"
    else:
        await message.answer("❌ Неизвестный топ")
        return
    await message.answer(text)

# ==================== ИГРЫ (ТЕКСТОВЫЕ КОМАНДЫ) ====================
@router.message(F.text.lower().startswith("рул"))
async def roulette_game(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("❌ Формат: рул [цвет/число] [ставка]\nПримеры:\nрул красное 1000\nрул 7 2000")
        return
    bet_type = parts[1].lower()
    try:
        bet = int(parts[2])
    except:
        await message.answer("❌ Ставка должна быть числом")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    if user['is_banned']:
        await message.answer("⛔ Ты забанен!")
        return
    if bet < MIN_BET:
        await message.answer(f"❌ Минимальная ставка: {MIN_BET} LC")
        return
    if bet > user['balance_lc']:
        await message.answer("❌ Недостаточно средств!")
        return
    db.update_balance(message.from_user.id, -bet)
    result = random.randint(0, 36)
    win, mult = check_roulette_win(bet_type, result)
    color = "зеленое" if result==0 else ("красное" if result in RED_NUMBERS else "черное")
    if win:
        win_amount = bet * mult
        db.update_balance(message.from_user.id, win_amount)
        db.add_game_stat(message.from_user.id, "roulette", True, bet, win_amount)
        update_user_status(message.from_user.id)
        await message.answer(
            f"🎉 <b>Ты выиграл в рулетке!</b>\n\n"
            f"Выпало число: {result} ({color})\n"
            f"Ставка: {bet} LC\n"
            f"Коэффициент: x{mult}\n"
            f"Выигрыш: +{win_amount} LC\n"
            f"💰 Баланс: {user['balance_lc'] - bet + win_amount} LC"
        )
    else:
        db.add_game_stat(message.from_user.id, "roulette", False, bet, 0)
        update_user_status(message.from_user.id)
        await message.answer(
            f"💔 <b>Ты проиграл в рулетке</b>\n\n"
            f"Выпало число: {result} ({color})\n"
            f"💰 Потеряно: {bet} LC\n"
            f"💰 Баланс: {user['balance_lc'] - bet} LC"
        )

@router.message(F.text.lower().startswith(("слоты", "слот")))
async def slots_game(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: слоты [ставка]\nПример: слоты 1000")
        return
    try:
        bet = int(parts[1])
    except:
        await message.answer("❌ Ставка должна быть числом")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    if user['is_banned']:
        await message.answer("⛔ Ты забанен!")
        return
    if bet < MIN_BET:
        await message.answer(f"❌ Минимальная ставка: {MIN_BET} LC")
        return
    if bet > user['balance_lc']:
        await message.answer("❌ Недостаточно средств!")
        return
    db.update_balance(message.from_user.id, -bet)
    slot_msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(3)
    value = slot_msg.dice.value
    if value == 64:
        combo = "7️⃣7️⃣7️⃣"
        win_name = "ДЖЕКПОТ"
        multiplier = 10
    elif value == 22:
        combo = "🍒🍒🍒"
        win_name = "ВИШНИ"
        multiplier = 3
    elif value == 43:
        combo = "🍋🍋🍋"
        win_name = "ЛИМОНЫ"
        multiplier = 3
    elif value == 1:
        combo = "💎💎💎"
        win_name = "БАР"
        multiplier = 5
    else:
        combo = f"{random.choice(['🍒','🍋','💎','7️⃣'])} {random.choice(['🍒','🍋','💎','7️⃣'])} {random.choice(['🍒','🍋','💎','7️⃣'])}"
        win_name = "ПРОИГРЫШ"
        multiplier = 0
    if multiplier > 0:
        win_amount = bet * multiplier
        db.update_balance(message.from_user.id, win_amount)
        db.add_game_stat(message.from_user.id, "slots", True, bet, win_amount)
        update_user_status(message.from_user.id)
        await message.answer(
            f"🎰 <b>СЛОТЫ - {win_name}!</b>\n\n"
            f"{combo}\n\n"
            f"💰 Ставка: {bet} LC\n"
            f"📈 Коэффициент: x{multiplier}\n"
            f"💎 Выигрыш: +{win_amount} LC\n"
            f"🪙 Баланс: {user['balance_lc'] - bet + win_amount} LC"
        )
    else:
        db.add_game_stat(message.from_user.id, "slots", False, bet, 0)
        update_user_status(message.from_user.id)
        await message.answer(
            f"🎰 <b>СЛОТЫ - {win_name}</b>\n\n"
            f"{combo}\n\n"
            f"💰 Ставка: {bet} LC\n"
            f"💔 Потеряно: {bet} LC\n"
            f"🪙 Баланс: {user['balance_lc'] - bet} LC"
        )

# ==================== КОСТИ (ДУЭЛЬ) ====================
@router.message(F.text.lower().startswith("кости"))
async def create_dice_duel(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: кости [ставка]\nПример: кости 1000")
        return
    try:
        bet = int(parts[1])
    except:
        await message.answer("❌ Ставка должна быть числом")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    if user['is_banned']:
        await message.answer("⛔ Ты забанен!")
        return
    if bet < MIN_BET:
        await message.answer(f"❌ Минимальная ставка: {MIN_BET} LC")
        return
    if bet > user['balance_lc']:
        await message.answer("❌ Недостаточно средств!")
        return
    if bet > MAX_BET:
        await message.answer(f"❌ Максимальная ставка: {MAX_BET} LC")
        return
    duel_id = f"{message.from_user.id}_{message.message_id}"
    active_duels[duel_id] = {
        'creator': message.from_user.id,
        'creator_name': message.from_user.full_name,
        'bet': bet,
        'status': 'waiting'
    }
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Принять вызов", callback_data=f"accept_duel_{duel_id}")]
    ])
    await message.answer(
        f"🎲 <b>Дуэль создана!</b>\n\n"
        f"👤 Игрок: {message.from_user.full_name}\n"
        f"💰 Ставка: {bet} LC\n\n"
        f"⚔️ Ждем противника...",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("accept_duel_"))
async def accept_duel(callback: CallbackQuery):
    duel_id = callback.data.replace("accept_duel_", "")
    if duel_id not in active_duels:
        await callback.answer("❌ Дуэль уже неактуальна", show_alert=True)
        return
    duel = active_duels[duel_id]
    if duel['status'] != 'waiting':
        await callback.answer("❌ Дуэль уже началась", show_alert=True)
        return
    opponent_id = callback.from_user.id
    if opponent_id == duel['creator']:
        await callback.answer("❌ Нельзя играть с самим собой!", show_alert=True)
        return
    opponent = db.get_user(opponent_id)
    if not opponent:
        await callback.answer("❌ Ты не зарегистрирован!", show_alert=True)
        return
    if opponent['is_banned']:
        await callback.answer("⛔ Ты забанен!", show_alert=True)
        return
    if duel['bet'] > opponent['balance_lc']:
        await callback.answer(f"❌ Недостаточно средств! Нужно {duel['bet']} LC", show_alert=True)
        return
    db.update_balance(duel['creator'], -duel['bet'])
    db.update_balance(opponent_id, -duel['bet'])
    duel['opponent'] = opponent_id
    duel['opponent_name'] = callback.from_user.full_name
    duel['status'] = 'playing'
    await callback.message.edit_text(
        f"🎲 <b>ДУЭЛЬ НАЧАЛАСЬ!</b>\n\n"
        f"👤 {duel['creator_name']} VS {duel['opponent_name']}\n"
        f"💰 Банк: {duel['bet'] * 2} LC\n\n"
        f"⚡ Кидаем кости..."
    )
    creator_dice = await callback.bot.send_dice(callback.message.chat.id, emoji="🎲")
    opponent_dice = await callback.bot.send_dice(callback.message.chat.id, emoji="🎲")
    await asyncio.sleep(4)
    creator_roll = creator_dice.dice.value
    opponent_roll = opponent_dice.dice.value
    if creator_roll > opponent_roll:
        winner_id = duel['creator']
        winner_name = duel['creator_name']
        win_amount = duel['bet'] * 2
        db.update_balance(winner_id, win_amount)
        db.add_game_stat(winner_id, "dice", True, duel['bet'], win_amount)
        db.add_game_stat(opponent_id, "dice", False, duel['bet'], 0)
        update_user_status(winner_id)
        update_user_status(opponent_id)
        result_text = f"🏆 <b>ПОБЕДИТЕЛЬ: {winner_name}</b>"
    elif opponent_roll > creator_roll:
        winner_id = opponent_id
        winner_name = duel['opponent_name']
        win_amount = duel['bet'] * 2
        db.update_balance(winner_id, win_amount)
        db.add_game_stat(winner_id, "dice", True, duel['bet'], win_amount)
        db.add_game_stat(duel['creator'], "dice", False, duel['bet'], 0)
        update_user_status(winner_id)
        update_user_status(duel['creator'])
        result_text = f"🏆 <b>ПОБЕДИТЕЛЬ: {winner_name}</b>"
    else:
        db.update_balance(duel['creator'], duel['bet'])
        db.update_balance(opponent_id, duel['bet'])
        await callback.message.answer(
            f"🎲 <b>НИЧЬЯ!</b>\n\n"
            f"👤 {duel['creator_name']}: {creator_roll}\n"
            f"👤 {duel['opponent_name']}: {opponent_roll}\n\n"
            f"🤝 Ставки возвращены!"
        )
        del active_duels[duel_id]
        await callback.answer()
        return
    await callback.message.answer(
        f"🎲 <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n\n"
        f"👤 {duel['creator_name']}: {creator_roll}\n"
        f"👤 {duel['opponent_name']}: {opponent_roll}\n\n"
        f"{result_text}\n"
        f"💰 Выигрыш: +{win_amount} LC"
    )
    del active_duels[duel_id]
    await callback.answer()

# ==================== МИНЫ ====================
@router.message(F.text.lower().startswith("мины"))
async def start_mines(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: мины [ставка]\nПример: мины 1000")
        return
    try:
        bet = int(parts[1])
    except:
        await message.answer("❌ Ставка должна быть числом")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    if user['is_banned']:
        await message.answer("⛔ Ты забанен!")
        return
    if bet < MIN_BET:
        await message.answer(f"❌ Минимальная ставка: {MIN_BET} LC")
        return
    if bet > user['balance_lc']:
        await message.answer("❌ Недостаточно средств!")
        return
    if bet > MAX_BET:
        await message.answer(f"❌ Максимальная ставка: {MAX_BET} LC")
        return
    db.update_balance(message.from_user.id, -bet)
    mines = random.sample(range(25), 5)
    await state.set_state(MinesState.playing)
    await state.update_data(bet=bet, mines=mines, opened=[], game_over=False)
    await show_mines_field(message, state, message.from_user.id)

async def show_mines_field(message: Message, state: FSMContext, user_id: int, edit: bool = False):
    data = await state.get_data()
    opened = data.get('opened', [])
    mines = data.get('mines', [])
    bet = data.get('bet', 0)
    builder = InlineKeyboardBuilder()
    for i in range(5):
        row = []
        for j in range(5):
            cell_num = i * 5 + j
            if cell_num in opened:
                if cell_num in mines:
                    text = "💥"
                else:
                    text = "⬜"
            else:
                text = "⬛"
            row.append(InlineKeyboardButton(text=text, callback_data=f"mine_{cell_num}"))
        builder.row(*row)
    if opened:
        current_mult = MULTIPLIERS.get(len(opened), 300)
        win_amount = int(bet * current_mult)
        builder.row(InlineKeyboardButton(text=f"💰 ЗАБРАТЬ {win_amount} LC (x{current_mult})", callback_data="mine_cashout"))
    builder.row(InlineKeyboardButton(text="◀️ Выйти", callback_data="mine_exit"))
    info = f"💣 <b>Мины</b>\n\n💰 Ставка: {bet} LC\n🔓 Открыто: {len(opened)}\n"
    if opened:
        info += f"📈 Множитель: x{current_mult}\n💎 Можно забрать: {win_amount} LC"
    else:
        info += "📈 Множитель за 1 клетку: x1.2"
    info += "\n\n⬛ - закрыто\n⬜ - пусто\n💥 - мина"
    if edit:
        await message.edit_text(info, reply_markup=builder.as_markup())
    else:
        await message.answer(info, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("mine_"), MinesState.playing)
async def mine_action(callback: CallbackQuery, state: FSMContext):
    if callback.data == "mine_cashout":
        data = await state.get_data()
        if data.get('game_over', False):
            await callback.answer("Игра окончена!", show_alert=True)
            return
        opened = data.get('opened', [])
        if not opened:
            await callback.answer("Сначала открой хотя бы одну клетку!", show_alert=True)
            return
        bet = data.get('bet', 0)
        current_mult = MULTIPLIERS.get(len(opened), 300)
        win_amount = int(bet * current_mult)
        db.update_balance(callback.from_user.id, win_amount)
        db.add_game_stat(callback.from_user.id, "mines", True, bet, win_amount)
        update_user_status(callback.from_user.id)
        await callback.message.edit_text(f"💰 <b>Ты забрал выигрыш!</b>\n\nОткрыто: {len(opened)}\nМножитель: x{current_mult}\nВыигрыш: +{win_amount} LC")
        await state.clear()
        await callback.answer()
        return
    if callback.data == "mine_exit":
        data = await state.get_data()
        if not data.get('game_over', False) and data.get('opened'):
            bet = data.get('bet', 0)
            db.add_game_stat(callback.from_user.id, "mines", False, bet, 0)
            update_user_status(callback.from_user.id)
        await callback.message.edit_text("👋 Игра завершена")
        await state.clear()
        await callback.answer()
        return
    try:
        cell = int(callback.data.replace("mine_", ""))
    except:
        await callback.answer()
        return
    data = await state.get_data()
    if data.get('game_over', False):
        await callback.answer("Игра окончена!", show_alert=True)
        return
    opened = data.get('opened', [])
    mines = data.get('mines', [])
    bet = data.get('bet', 0)
    if cell in opened:
        await callback.answer("Эта клетка уже открыта!", show_alert=True)
        return
    if cell in mines:
        opened.append(cell)
        await state.update_data(opened=opened, game_over=True)
        await show_mines_field(callback.message, state, callback.from_user.id, edit=True)
        await callback.message.answer(f"💥 <b>БАХ! Ты подорвался!</b>\n\n💰 Потеряно: {bet} LC")
        db.add_game_stat(callback.from_user.id, "mines", False, bet, 0)
        update_user_status(callback.from_user.id)
        await state.clear()
        await callback.answer()
        return
    opened.append(cell)
    await state.update_data(opened=opened)
    await show_mines_field(callback.message, state, callback.from_user.id, edit=True)
    await callback.answer()

# ==================== БЛЭКДЖЕК ====================
@router.message(F.text.lower().startswith(("бджек", "blackjack")))
async def start_blackjack(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Формат: бджек [ставка]\nПример: бджек 1000")
        return
    try:
        bet = int(parts[1])
    except:
        await message.answer("❌ Ставка должна быть числом")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ты не зарегистрирован! Напиши /start")
        return
    if user['is_banned']:
        await message.answer("⛔ Ты забанен!")
        return
    if bet < MIN_BET:
        await message.answer(f"❌ Минимальная ставка: {MIN_BET} LC")
        return
    if bet > user['balance_lc']:
        await message.answer("❌ Недостаточно средств!")
        return
    if bet > MAX_BET:
        await message.answer(f"❌ Максимальная ставка: {MAX_BET} LC")
        return
    db.update_balance(message.from_user.id, -bet)
    deck = create_deck()
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    player_score = hand_score(player_hand)
    if player_score == 21:
        win_amount = int(bet * 2.5)
        db.update_balance(message.from_user.id, win_amount)
        db.add_game_stat(message.from_user.id, "blackjack", True, bet, win_amount)
        update_user_status(message.from_user.id)
        await message.answer(
            f"🃏 <b>БЛЭКДЖЕК!</b>\n\n"
            f"Твои карты: {hand_to_string(player_hand)} (21)\n"
            f"Карты дилера: {hand_to_string(dealer_hand)} ({hand_score(dealer_hand)})\n\n"
            f"💰 Выигрыш: +{win_amount} LC"
        )
        return
    await state.set_state(BlackjackState.playing)
    await state.update_data(bet=bet, deck=deck, player_hand=player_hand, dealer_hand=dealer_hand)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Еще", callback_data="bj_hit"),
         InlineKeyboardButton(text="⏹ Хватит", callback_data="bj_stand")]
    ])
    await message.answer(
        f"🃏 <b>Блэкджек</b>\n\n"
        f"Твои карты: {hand_to_string(player_hand)} ({player_score})\n"
        f"Карты дилера: {hand_to_string([dealer_hand[0]])} + ?\n\n"
        f"💰 Ставка: {bet} LC",
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith("bj_"), BlackjackState.playing)
async def blackjack_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data.replace("bj_", "")
    data = await state.get_data()
    bet = data['bet']
    deck = data['deck']
    player_hand = data['player_hand']
    dealer_hand = data['dealer_hand']
    user_id = callback.from_user.id
    if action == "hit":
        player_hand.append(deck.pop())
        player_score = hand_score(player_hand)
        if player_score > 21:
            db.add_game_stat(user_id, "blackjack", False, bet, 0)
            update_user_status(user_id)
            await callback.message.edit_text(
                f"💔 <b>ПЕРЕБОР!</b>\n\n"
                f"Твои карты: {hand_to_string(player_hand)} ({player_score})\n"
                f"Карты дилера: {hand_to_string(dealer_hand)} ({hand_score(dealer_hand)})\n\n"
                f"💰 Потеряно: {bet} LC"
            )
            await state.clear()
            await callback.answer()
            return
        await state.update_data(player_hand=player_hand, deck=deck)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Еще", callback_data="bj_hit"),
             InlineKeyboardButton(text="⏹ Хватит", callback_data="bj_stand")]
        ])
        await callback.message.edit_text(
            f"🃏 <b>Блэкджек</b>\n\n"
            f"Твои карты: {hand_to_string(player_hand)} ({player_score})\n"
            f"Карты дилера: {hand_to_string([dealer_hand[0]])} + ?\n\n"
            f"💰 Ставка: {bet} LC",
            reply_markup=keyboard
        )
        await callback.answer()
    elif action == "stand":
        player_score = hand_score(player_hand)
        dealer_score = hand_score(dealer_hand)
        while dealer_score < 17:
            dealer_hand.append(deck.pop())
            dealer_score = hand_score(dealer_hand)
        if dealer_score > 21:
            win_amount = bet * 2
            db.update_balance(user_id, win_amount)
            db.add_game_stat(user_id, "blackjack", True, bet, win_amount)
            update_user_status(user_id)
            result = f"🎉 <b>Ты выиграл! Дилер перебрал</b>\n\n+{win_amount} LC"
        elif dealer_score > player_score:
            db.add_game_stat(user_id, "blackjack", False, bet, 0)
            update_user_status(user_id)
            result = f"💔 <b>Дилер выиграл</b>\n\n💰 Потеряно: {bet} LC"
        elif dealer_score < player_score:
            win_amount = bet * 2
            db.update_balance(user_id, win_amount)
            db.add_game_stat(user_id, "blackjack", True, bet, win_amount)
            update_user_status(user_id)
            result = f"🎉 <b>Ты выиграл!</b>\n\n+{win_amount} LC"
        else:
            db.update_balance(user_id, bet)
            db.add_game_stat(user_id, "blackjack", False, bet, 0)
            update_user_status(user_id)
            result = f"🤝 <b>Ничья</b>\n\n💰 Ставка возвращена: {bet} LC"
        await callback.message.edit_text(
            f"🃏 <b>Блэкджек</b>\n\n"
            f"Твои карты: {hand_to_string(player_hand)} ({player_score})\n"
            f"Карты дилера: {hand_to_string(dealer_hand)} ({dealer_score})\n\n"
            f"{result}"
        )
        await state.clear()
        await callback.answer()

# ==================== БИЗНЕС (КОМАНДЫ) ====================
@router.callback_query(F.data == "buy_small")
async def buy_small(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if user['balance_lc'] < 20000:
        await callback.answer("❌ Нужно 20000 LC", show_alert=True)
        return
    conn = db.get_connection()
    if conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone():
        await callback.answer("❌ У тебя уже есть бизнес! Сначала продай старый.", show_alert=True)
        return
    db.update_balance(callback.from_user.id, -20000)
    conn.execute("INSERT INTO business (user_id, business_type, last_collected) VALUES (?, 'small', datetime('now'))", (callback.from_user.id,))
    conn.commit()
    await callback.answer("✅ Ты купил Ларек у дома 24/7! Торгуй ночами!", show_alert=True)
    await business_menu_callback(callback)

@router.callback_query(F.data == "buy_medium")
async def buy_medium(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if user['balance_lc'] < 50000:
        await callback.answer("❌ Нужно 50000 LC", show_alert=True)
        return
    conn = db.get_connection()
    if conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone():
        await callback.answer("❌ У тебя уже есть бизнес! Сначала продай старый.", show_alert=True)
        return
    db.update_balance(callback.from_user.id, -50000)
    conn.execute("INSERT INTO business (user_id, business_type, last_collected) VALUES (?, 'medium', datetime('now'))", (callback.from_user.id,))
    conn.commit()
    await callback.answer("🍻 Ты купил Пивнуху! Наливай, народ потянулся!", show_alert=True)
    await business_menu_callback(callback)

@router.callback_query(F.data == "buy_large")
async def buy_large(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if user['balance_lc'] < 100000:
        await callback.answer("❌ Нужно 100000 LC", show_alert=True)
        return
    conn = db.get_connection()
    if conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone():
        await callback.answer("❌ У тебя уже есть бизнес! Сначала продай старый.", show_alert=True)
        return
    db.update_balance(callback.from_user.id, -100000)
    conn.execute("INSERT INTO business (user_id, business_type, last_collected) VALUES (?, 'large', datetime('now'))", (callback.from_user.id,))
    conn.commit()
    await callback.answer("🏭 Ты купил Завод по производству металла! Сталь течет рекой!", show_alert=True)
    await business_menu_callback(callback)

@router.callback_query(F.data == "buy_paid")
async def buy_paid(callback: CallbackQuery):
    await callback.answer("🏦 Банк за 500₽ - используй /donate", show_alert=True)

@router.callback_query(F.data == "collect_business")
async def collect_business_callback(callback: CallbackQuery):
    conn = db.get_connection()
    biz = conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    if not biz:
        await callback.answer("❌ Нет бизнеса", show_alert=True)
        return
    daily = {"small":2500, "medium":5500, "large":10500, "paid":50000}
    last = datetime.strptime(biz[2], '%Y-%m-%d %H:%M:%S')
    if (datetime.now() - last).total_seconds() < 86400:
        await callback.answer("⏳ Еще не прошло 24 часа", show_alert=True)
        return
    conn.execute("UPDATE business SET last_collected = datetime('now') WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    db.update_balance(callback.from_user.id, daily.get(biz[1],0))
    await callback.answer(f"💰 Собрано: {daily.get(biz[1])} LC!", show_alert=True)
    await business_menu_callback(callback)

@router.callback_query(F.data == "my_business")
async def my_business_callback(callback: CallbackQuery):
    conn = db.get_connection()
    biz = conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    if not biz:
        await callback.answer("❌ Нет бизнеса", show_alert=True)
        return
    names = {"small":"🏪 Ларек у дома 24/7","medium":"🍺 Пивнуха","large":"🏭 Завод по производству металла","paid":"🏦 Банк"}
    prices = {"small":20000,"medium":50000,"large":100000,"paid":500}
    daily = {"small":2500,"medium":5500,"large":10500,"paid":50000}
    currency = {"small":"LC","medium":"LC","large":"LC","paid":"₽"}
    last = datetime.strptime(biz[2], '%Y-%m-%d %H:%M:%S')
    hours = (datetime.now() - last).total_seconds() / 3600
    sell_price = prices.get(biz[1],0) // 2
    
    text = (
        f"💼 <b>Мой бизнес</b>\n\n"
        f"🏢 Тип: {names.get(biz[1])}\n"
        f"💰 Инвестировано: {prices.get(biz[1])} {currency.get(biz[1])}\n"
        f"📈 Доход в день: +{daily.get(biz[1])} LC\n"
        f"💵 Можно продать за: {sell_price} {currency.get(biz[1])}\n\n"
        f"⏱ Последний сбор: {last.strftime('%Y-%m-%d %H:%M')}\n"
        f"⌛️ Прошло: {hours:.1f} ч.\n"
    )
    if hours >= 24:
        text += "\n✅ Можно собирать доход!"
    
    await callback.message.edit_text(text, reply_markup=get_back_button())
    await callback.answer()

@router.callback_query(F.data == "sell_business")
async def sell_business_callback(callback: CallbackQuery):
    conn = db.get_connection()
    biz = conn.execute("SELECT * FROM business WHERE user_id = ?", (callback.from_user.id,)).fetchone()
    if not biz:
        await callback.answer("❌ Нет бизнеса", show_alert=True)
        return
    prices = {"small":20000,"medium":50000,"large":100000,"paid":500}
    currency = {"small":"LC","medium":"LC","large":"LC","paid":"₽"}
    sell_price = prices.get(biz[1],0) // 2
    currency_type = currency.get(biz[1], "LC")
    
    conn.execute("DELETE FROM business WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    
    if biz[1] == "paid":
        db.update_balance(callback.from_user.id, sell_price * 200)
        await callback.answer(f"✅ Продано за {sell_price * 200} LC", show_alert=True)
    else:
        db.update_balance(callback.from_user.id, sell_price)
        await callback.answer(f"✅ Продано за {sell_price} LC", show_alert=True)
    
    await business_menu_callback(callback)

# ==================== АДМИН-КОМАНДЫ ====================
@router.message(Command("ban"))
async def cmd_ban(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❌ Использование: /ban user_id причина")
        return
    try:
        user_id = int(args[1])
        reason = args[2]
    except:
        await message.answer("❌ Неверный формат")
        return
    conn = db.get_connection()
    conn.execute("UPDATE users SET is_banned = 1, ban_reason = ? WHERE user_id = ?", (reason, user_id))
    conn.commit()
    await message.answer(f"✅ Пользователь {user_id} забанен.\nПричина: {reason}")

@router.message(Command("unban"))
async def cmd_unban(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /unban user_id")
        return
    try:
        user_id = int(args[1])
    except:
        await message.answer("❌ Неверный ID")
        return
    conn = db.get_connection()
    conn.execute("UPDATE users SET is_banned = 0, ban_reason = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    await message.answer(f"✅ Пользователь {user_id} разбанен.")

@router.message(Command("money"))
async def cmd_money(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Использование: /money user_id сумма")
        return
    try:
        user_id = int(args[1])
        amount = int(args[2])
    except:
        await message.answer("❌ Неверные числа")
        return
    new_balance = db.update_balance(user_id, amount)
    await message.answer(f"✅ Баланс пользователя {user_id} изменен на {amount}. Текущий: {new_balance}")

@router.message(Command("add_promo"))
async def cmd_add_promo(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 4:
        await message.answer("❌ Использование: /add_promo КОД СУММА ЛИМИТ")
        return
    code, reward, max_uses = args[1], args[2], args[3]
    try:
        reward = int(reward)
        max_uses = int(max_uses)
    except:
        await message.answer("❌ Сумма и лимит должны быть числами")
        return
    conn = db.get_connection()
    conn.execute("INSERT INTO promocodes (code, reward, max_uses) VALUES (?, ?, ?) ON CONFLICT(code) DO UPDATE SET reward = ?, max_uses = ?, used_count = 0", (code, reward, max_uses, reward, max_uses))
    conn.commit()
    await message.answer(f"✅ Промокод {code} создан! Награда: {reward}, лимит: {max_uses}")

@router.message(Command("promolist"))
async def cmd_promolist(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    conn = db.get_connection()
    promos = conn.execute("SELECT * FROM promocodes ORDER BY used_count DESC").fetchall()
    if not promos:
        await message.answer("📭 Нет промокодов")
        return
    text = "📋 <b>Список промокодов:</b>\n\n"
    for p in promos:
        text += f"• <code>{p[0]}</code>: {p[1]} LC | {p[3]}/{p[2]}\n"
    await message.answer(text)

@router.message(Command("add_glc"))
async def cmd_add_glc(message: Message):
    """Выдать GLC пользователю"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Использование: /add_glc user_id сумма")
        return
    try:
        user_id = int(args[1])
        amount = int(args[2])
    except:
        await message.answer("❌ Неверные числа")
        return
    new_balance = db.update_glc(user_id, amount)
    db.log_action(user_id, "admin_glc", f"админ выдал {amount} GLC")
    await message.answer(f"✅ Пользователю {user_id} выдано {amount} GLC. Текущий баланс: {new_balance}")
    try:
        await message.bot.send_message(user_id, f"💰 <b>Вам начислено {amount} GLC</b> от администратора!")
    except:
        pass

@router.message(Command("verify_admin"))
async def cmd_verify_admin(message: Message):
    """Выдать верификацию администратора"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /verify_admin user_id")
        return
    try:
        user_id = int(args[1])
    except:
        await message.answer("❌ Неверный ID")
        return
    user = db.get_user(user_id)
    if not user:
        await message.answer("❌ Пользователь не найден")
        return
    conn = db.get_connection()
    conn.execute("UPDATE users SET is_admin_verified = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    db.log_action(user_id, "admin_verify", f"админ выдал верификацию")
    await message.answer(f"✅ Пользователь {user_id} теперь верифицирован как администратор!")
    try:
        await message.bot.send_message(user_id, f"👑 <b>Поздравляем! Вы получили статус администратора бота!</b>\n\nТеперь вы отображаетесь как верифицированный администратор.")
    except:
        pass

@router.message(Command("unverify_admin"))
async def cmd_unverify_admin(message: Message):
    """Снять верификацию администратора"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /unverify_admin user_id")
        return
    try:
        user_id = int(args[1])
    except:
        await message.answer("❌ Неверный ID")
        return
    conn = db.get_connection()
    conn.execute("UPDATE users SET is_admin_verified = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    db.log_action(user_id, "admin_unverify", f"админ снял верификацию")
    await message.answer(f"✅ У пользователя {user_id} снята верификация администратора")

@router.message(Command("verify_player"))
async def cmd_verify_player(message: Message):
    """Выдать статус спонсора игроку"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Использование: /verify_player user_id название_спонсора")
        return
    try:
        user_id = int(args[1])
        sponsor_name = ' '.join(args[2:])
    except:
        await message.answer("❌ Неверный формат")
        return
    user = db.get_user(user_id)
    if not user:
        await message.answer("❌ Пользователь не найден")
        return
    conn = db.get_connection()
    conn.execute("UPDATE users SET is_sponsor = 1, sponsor_name = ? WHERE user_id = ?", (sponsor_name, user_id))
    conn.commit()
    db.log_action(user_id, "sponsor_verify", f"админ выдал статус спонсора: {sponsor_name}")
    await message.answer(f"✅ Пользователь {user_id} теперь является спонсором бота: {sponsor_name}")
    try:
        await message.bot.send_message(user_id, f"🎖️ <b>Поздравляем! Вы получили статус спонсора бота: {sponsor_name}</b>\n\nСпасибо за поддержку проекта!")
    except:
        pass

@router.message(Command("unverify_player"))
async def cmd_unverify_player(message: Message):
    """Снять статус спонсора"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /unverify_player user_id")
        return
    try:
        user_id = int(args[1])
    except:
        await message.answer("❌ Неверный ID")
        return
    conn = db.get_connection()
    conn.execute("UPDATE users SET is_sponsor = 0, sponsor_name = '' WHERE user_id = ?", (user_id,))
    conn.commit()
    db.log_action(user_id, "sponsor_unverify", f"админ снял статус спонсора")
    await message.answer(f"✅ У пользователя {user_id} снят статус спонсора")

@router.message(Command("donate_confirm"))
async def cmd_donate_confirm(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ты не админ!")
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Использование: /donate_confirm user_id сумма [business]")
        return
    try:
        user_id = int(args[1])
        amount = int(args[2])
        is_business = len(args) > 3 and args[3] == "business"
    except:
        await message.answer("❌ Неверный формат")
        return
    if is_business:
        conn = db.get_connection()
        existing = conn.execute("SELECT * FROM business WHERE user_id = ?", (user_id,)).fetchone()
        if existing:
            conn.execute("DELETE FROM business WHERE user_id = ?", (user_id,))
        conn.execute("INSERT INTO business (user_id, business_type, last_collected) VALUES (?, 'paid', datetime('now'))", (user_id,))
        conn.commit()
        await message.answer(f"✅ Бизнес выдан пользователю {user_id}")
        try:
            await message.bot.send_message(
                user_id,
                "🏦 <b>Тебе выдан Банк!</b>\n\n"
                "Ты будешь получать по 50к #LC каждый день!\n"
                "Забирай доход в разделе 💼 Бизнес → 💰 Собрать"
            )
        except:
            pass
    else:
        lc_amount = {100:20000,200:30000,300:40000,400:50000,500:60000,600:70000,700:80000,800:90000,900:100000,1000:110000}.get(amount, amount*200)
        db.update_balance(user_id, lc_amount)
        await message.answer(f"✅ Начислено {lc_amount} LC пользователю {user_id}")
        try:
            await message.bot.send_message(user_id, f"💰 <b>Донат зачислен!</b>\n\nТы получил +{lc_amount} LC")
        except:
            pass

# ==================== ЛОТЕРЕЯ (РОЗЫГРЫШ) ====================
async def draw_lottery(bot):
    week = f"{datetime.now().year}-{datetime.now().isocalendar()[1]}"
    conn = db.get_connection()
    tickets = conn.execute("SELECT user_id, ticket_count FROM lottery_tickets WHERE week_number = ?", (week,)).fetchall()
    if not tickets:
        await bot.send_message(CHANNEL_ID, "🎟 РОЗЫГРЫШ ЛОТЕРЕИ\n\nВ этой неделе никто не купил билеты 😢")
        return
    pool = [t[0] for t in tickets for _ in range(t[1])]
    random.shuffle(pool)
    winners = []
    for _ in range(3):
        if pool:
            w = random.choice(pool)
            while w in [x['user_id'] for x in winners] and pool:
                w = random.choice(pool)
            winners.append({'user_id': w, 'prize': [100000,30000,15000][_] if _<3 else 0})
    for w in winners:
        db.update_balance(w['user_id'], w['prize'])
        db.add_game_stat(w['user_id'], "lottery", True, 0, w['prize'])
        update_user_status(w['user_id'])
    results = f"🥇 {winners[0]['user_id']} — {winners[0]['prize']} LC\n🥈 {winners[1]['user_id']} — {winners[1]['prize']} LC\n🥉 {winners[2]['user_id']} — {winners[2]['prize']} LC"
    await bot.send_message(CHANNEL_ID, f"🎟 РЕЗУЛЬТАТЫ ЛОТЕРЕИ\n\n{results}")
    conn.execute("DELETE FROM lottery_tickets WHERE week_number = ?", (week,))
    conn.commit()

# ==================== ЗАПУСК ====================
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
