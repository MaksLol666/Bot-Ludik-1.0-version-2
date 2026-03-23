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
        if 'active_glc_status' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN active_glc_status TEXT DEFAULT ''")
            conn.commit()
        if 'active_game_status' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN active_game_status TEXT DEFAULT ''")
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
                sponsor_name TEXT DEFAULT '',
                active_glc_status TEXT DEFAULT '',
                active_game_status TEXT DEFAULT ''
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
    builder.row(InlineKeyboardButton(text="👥 Рефералы", callback_data="referral_menu"), InlineKeyboardButton(text="🏆 Статусы", callback_data="status_menu"))
    builder.row(InlineKeyboardButton(text="💰 GLC", callback_data="glc_info"), InlineKeyboardButton(text="ℹ️ Инфо", callback_data="info"))
    return builder.as_markup()

def get_casino_menu():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🃏 Рулетка", callback_data="game_roulette"),
        InlineKeyboardButton(text="🎰 Слоты", callback_data="game_slots")
    )
    builder.row(
        InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice"),
        InlineKeyboardButton(text="💣 Мины", callback_data="game_mines")
    )
    builder.row(
        InlineKeyboardButton(text="🃏 Блэкджек", callback_data="game_blackjack"),
        InlineKeyboardButton(text="💎 Under 7 Over", callback_data="game_under7over")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
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
    builder.row(InlineKeyboardButton(text="🃏 Блэкджек", callback_data="top_blackjack"), InlineKeyboardButton(text="💎 Under 7 Over", callback_data="top_under7over"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_back_button():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()

def get_glc_menu():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💰 Баланс GLC", callback_data="glc_balance"),
        InlineKeyboardButton(text="🛒 Магазин статусов", callback_data="glc_shop")
    )
    builder.row(
        InlineKeyboardButton(text="🎒 Инвентарь статусов", callback_data="glc_inventory")
    )
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

def get_glc_inventory_page(statuses, active_icon, page, total_pages):
    builder = InlineKeyboardBuilder()
    for i, status in enumerate(statuses):
        is_active = status['status_icon'] == active_icon
        if is_active:
            builder.row(InlineKeyboardButton(text=f"⭐ {status['status_icon']} {status['status_name']} (Активен)", callback_data="noop"))
        else:
            builder.row(InlineKeyboardButton(text=f"⬜ {status['status_icon']} {status['status_name']}", callback_data=f"activate_status_{status['status_key']}"))
    
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"inv_page_{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"inv_page_{page+1}"))
    builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="◀️ Назад в GLC", callback_data="glc_menu"))
    return builder.as_markup()

def get_admin_menu():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"),
        InlineKeyboardButton(text="💰 Выдать LC", callback_data="admin_give_lc")
    )
    builder.row(
        InlineKeyboardButton(text="💎 Выдать GLC", callback_data="admin_give_glc"),
        InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin_create_promo")
    )
    builder.row(
        InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban_menu"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")
    )
    builder.row(
        InlineKeyboardButton(text="📋 Логи игрока", callback_data="admin_logs_menu"),
        InlineKeyboardButton(text="🏦 Бизнес", callback_data="admin_business")
    )
    builder.row(
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_mailing"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")
    )
    return builder.as_markup()

def get_admin_ban_menu():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔨 Забанить", callback_data="admin_ban"),
        InlineKeyboardButton(text="🔓 Разбанить", callback_data="admin_unban")
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

def get_status_menu():
    """Меню управления статусами"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎮 Статусы за топы", callback_data="status_game"),
        InlineKeyboardButton(text="💎 GLC статусы", callback_data="status_glc")
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Активные статусы", callback_data="status_active"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")
    )
    return builder.as_markup()

def get_game_status_menu(game_statuses, active_icons):
    """Клавиатура для выбора статусов за топы"""
    builder = InlineKeyboardBuilder()
    
    for icon, name in game_statuses:
        if icon in active_icons:
            builder.row(InlineKeyboardButton(text=f"✅ {icon} {name}", callback_data=f"toggle_game_{icon}"))
        else:
            builder.row(InlineKeyboardButton(text=f"⬜ {icon} {name}", callback_data=f"toggle_game_{icon}"))
    
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="status_menu"))
    return builder.as_markup()

def get_glc_status_menu(glc_statuses, active_icon):
    """Клавиатура для выбора GLC статуса"""
    builder = InlineKeyboardBuilder()
    
    if active_icon == "":
        builder.row(InlineKeyboardButton(text="✅ Без статуса", callback_data="activate_glc_none"))
    else:
        builder.row(InlineKeyboardButton(text="⬜ Без статуса", callback_data="activate_glc_none"))
    
    for status in glc_statuses:
        if status['status_icon'] == active_icon:
            builder.row(InlineKeyboardButton(text=f"✅ {status['status_icon']} {status['status_name']}", callback_data="noop"))
        else:
            builder.row(InlineKeyboardButton(text=f"⬜ {status['status_icon']} {status['status_name']}", callback_data=f"activate_glc_{status['status_key']}"))
    
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="status_menu"))
    return builder.as_markup()

def get_active_status_menu(game_active, glc_active):
    """Показать текущие активные статусы"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎮 Изменить топ-статусы", callback_data="status_game"))
    builder.row(InlineKeyboardButton(text="💎 Изменить GLC статус", callback_data="status_glc"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
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
    
    rich_top = conn.execute("""
        SELECT user_id FROM users 
        WHERE is_banned = 0 
        ORDER BY balance_lc DESC 
        LIMIT 1
    """).fetchone()
    rich_top = rich_top[0] if rich_top else None
    
    games = ['roulette', 'slots', 'dice', 'mines', 'lottery', 'blackjack', 'under7over']
    tops = {'rich': rich_top}
    
    STATUS_ICONS = {
        "roulette": "🃏",
        "slots": "🎰",
        "dice": "🎲",
        "mines": "💣",
        "lottery": "🎟️",
        "blackjack": "🃏",
        "under7over": "💎",
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

def get_display_name_with_status(user_id: int, username: str) -> str:
    """Получить имя со статусом для отображения в топах"""
    user = db.get_user(user_id)
    active_game = user.get('active_game_status', '') if user else ''
    active_glc = user.get('active_glc_status', '') if user else ''
    
    combined = active_glc + active_game
    if len(combined) > 7:
        combined = combined[:7]
    
    if combined:
        return f"{combined} {username}"
    else:
        return username

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

# Under 7 Over
def play_under7over(bet_type):
    dice1 = random.randint(1, 6)
    dice2 = random.randint(1, 6)
    total = dice1 + dice2
    
    if bet_type == "under":
        win = total < 7
        multiplier = 2
    elif bet_type == "over":
        win = total > 7
        multiplier = 2
    else:
        win = total == 7
        multiplier = 4
    
    return win, multiplier, dice1, dice2, total

# ==================== СОСТОЯНИЯ ДЛЯ ИГР ====================
class MinesState(StatesGroup):
    playing = State()

class BlackjackState(StatesGroup):
    playing = State()

class MailingState(StatesGroup):
    waiting_for_text = State()

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
        
        "💎 <b>Under 7 Over (Premium)</b>\n"
        "Команда: <code>u7o [под/над/ровно] [ставка]</code>\n"
        "Пример: <code>u7o под 1000</code>\n"
        "Правила: угадай сумму двух костей. Под (меньше 7) - x2, Над (больше 7) - x2, Ровно 7 - x4\n"
        "⚠️ Игра только за GLC! Минимальная ставка: 1000 GLC\n\n"
        
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
        "Команды: /tb (богачи), /tr (рулетка), /ts (слоты), /tk (кости), /tm (мины), /tl (лотерея), /tbj (блэкджек), /tu7o (Under 7 Over)\n\n"
        
        "🔍 <b>Просмотр игрока</b>\n"
        "Команда: <code>/глянуть [@username или ID]</code>\n"
        "Пример: <code>/глянуть @username</code>\n\n"
        
        "ℹ️ <b>Другое</b>\n"
        "<code>/my</code> — моя статистика\n"
        "<code>/promo [код]</code> — активировать промокод\n"
        "<code>/donate</code> — информация о донате\n\n"
        
        f"💰 <b>Баланс:</b> /my\n"
        f"👑 <b>Владелец:</b> {ADMIN_USERNAME}\n"
        f"📊 <b>Версия:</b> {BOT_VERSION}"
    )
    await message.answer(text)

# ==================== ПРОСМОТР ИГРОКА ====================
@router.message(Command("глянуть"))
async def cmd_глянуть(message: Message):
    """Просмотр информации о другом игроке"""
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        await message.answer(
            "❌ <b>Использование:</b>\n"
            "<code>/глянуть [@username или ID]</code>\n\n"
            "<b>Примеры:</b>\n"
            "<code>/глянуть @username</code>\n"
            "<code>/глянуть 123456789</code>"
        )
        return
    
    identifier = args[1].strip()
    
    if identifier.startswith('@'):
        identifier = identifier[1:]
        user = db.get_user_by_username(identifier)
    else:
        try:
            user_id = int(identifier)
            user = db.get_user(user_id)
        except:
            await message.answer("❌ Неверный формат ID")
            return
    
    if not user:
        await message.answer(f"❌ Пользователь не найден")
        return
    
    if user['is_banned']:
        await message.answer(f"⚠️ Пользователь забанен")
        return
    
    user_id = user['user_id']
    
    conn = db.get_connection()
    stats = conn.execute("""
        SELECT game_type, COUNT(*) as total, 
               SUM(CASE WHEN win THEN 1 ELSE 0 END) as wins,
               SUM(win_amount) as total_won
        FROM game_stats 
        WHERE user_id = ? 
        GROUP BY game_type
    """, (user_id,)).fetchall()
    
    stats_dict = {}
    for s in stats:
        stats_dict[s[0]] = {
            "total": s[1],
            "wins": s[2],
            "losses": s[1] - s[2],
            "total_won": s[3]
        }
    
    def get_stat(game):
        s = stats_dict.get(game, {"total": 0, "wins": 0, "losses": 0, "total_won": 0})
        return f"{s['wins']}💰 / {s['losses']}💔 / {s['total']} ставок"
    
    game_status = get_user_status(user_id)
    active_game = user.get('active_game_status', '')
    glc_statuses = db.get_user_glc_statuses(user_id)
    active_glc = user.get('active_glc_status', '')
    
    display_name = user.get('custom_name', user['username'])
    if active_glc:
        display_name = f"{active_glc} {display_name}"
    
    active_statuses = []
    if active_game:
        active_statuses.append(f"{active_game}")
    if active_glc:
        active_statuses.append(f"{active_glc}")
    active_text = " ".join(active_statuses) if active_statuses else "Не выбраны"
    
    all_game_statuses = ["🃏", "🎰", "🎲", "💣", "🎟️", "🃏", "💎", "💰"]
    game_statuses_count = len([s for s in all_game_statuses if s in game_status]) if game_status else 0
    glc_statuses_count = len(glc_statuses)
    total_statuses = game_statuses_count + glc_statuses_count
    
    text = (
        f"👤 <b>Пользователь:</b> {display_name} | ID: {user_id}\n\n"
        f"🏆 <b>Активные статусы:</b> {active_text}\n"
        f"📦 <b>Всего статусов:</b> {total_statuses} (топ: {game_statuses_count}, GLC: {glc_statuses_count})\n\n"
        f"📈 <b>Общая статистика:</b>\n\n"
        f"🃏 Рулетка: {get_stat('roulette')}\n"
        f"🎰 Слоты: {get_stat('slots')}\n"
        f"🎲 Кости: {get_stat('dice')}\n"
        f"💣 Мины: {get_stat('mines')}\n"
        f"🎟 Лотерея: {get_stat('lottery')}\n"
        f"🃏 Блэкджек: {get_stat('blackjack')}\n"
        f"💎 Under 7 Over: {get_stat('under7over')}\n\n"
        f"🪙 Баланс LC: {user['balance_lc']}\n"
        f"💰 Баланс GLC: {user['balance_glc']}\n\n"
        f"😭 Всего проиграно: {user['total_lost']} LC\n"
    )
    
    admin_verified = user.get('is_admin_verified', 0)
    is_sponsor = user.get('is_sponsor', 0)
    sponsor_name = user.get('sponsor_name', '')
    
    if admin_verified:
        text += "\n✅ <b>Верифицированный администратор</b>"
    if is_sponsor:
        text += f"\n☑️ <b>Спонсор бота: {sponsor_name}</b>"
    
    await message.answer(text)

# ==================== УПРАВЛЕНИЕ СТАТУСАМИ ====================
@router.callback_query(F.data == "status_menu")
async def status_menu(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    
    active_game = user.get('active_game_status', '')
    active_glc = user.get('active_glc_status', '')
    
    text = (
        f"🏆 <b>Управление статусами</b>\n\n"
        f"🎮 <b>Активные топ-статусы:</b> {active_game if active_game else 'Не выбраны'}\n"
        f"💎 <b>Активный GLC статус:</b> {active_glc if active_glc else 'Не выбран'}\n\n"
        f"Выберите, какие статусы будут отображаться в топах и профиле:"
    )
    
    await callback.message.edit_text(text, reply_markup=get_status_menu())
    await callback.answer()

@router.callback_query(F.data == "status_game")
async def status_game_menu(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    
    game_statuses = [
        ("🃏", "Рулетка"),
        ("🎰", "Слоты"),
        ("🎲", "Кости"),
        ("💣", "Мины"),
        ("🎟️", "Лотерея"),
        ("🃏", "Блэкджек"),
        ("💎", "Under 7 Over"),
        ("💰", "Богач")
    ]
    
    active_game = user.get('active_game_status', '')
    
    text = (
        f"🎮 <b>Статусы за топы</b>\n\n"
        f"Выберите, какие статусы будут отображаться в топах.\n"
        f"Максимум 7 статусов.\n\n"
        f"✅ - активен, ⬜ - не активен"
    )
    
    await callback.message.edit_text(text, reply_markup=get_game_status_menu(game_statuses, active_game))
    await callback.answer()

@router.callback_query(F.data.startswith("toggle_game_"))
async def toggle_game_status(callback: CallbackQuery):
    icon = callback.data.replace("toggle_game_", "")
    user = db.get_user(callback.from_user.id)
    
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    
    active = user.get('active_game_status', '')
    
    if icon in active:
        new_active = active.replace(icon, '')
    else:
        if len(active) >= 7:
            await callback.answer("❌ Нельзя выбрать больше 7 статусов!", show_alert=True)
            return
        new_active = active + icon
    
    conn = db.get_connection()
    conn.execute("UPDATE users SET active_game_status = ? WHERE user_id = ?", (new_active, callback.from_user.id))
    conn.commit()
    
    await callback.answer(f"{'✅ Включен' if icon in new_active else '❌ Выключен'}")
    
    game_statuses = [
        ("🃏", "Рулетка"),
        ("🎰", "Слоты"),
        ("🎲", "Кости"),
        ("💣", "Мины"),
        ("🎟️", "Лотерея"),
        ("🃏", "Блэкджек"),
        ("💎", "Under 7 Over"),
        ("💰", "Богач")
    ]
    
    await callback.message.edit_text(
        "🎮 <b>Статусы за топы</b>\n\nВыберите, какие статусы будут отображаться в топах.\nМаксимум 7 статусов.\n\n✅ - активен, ⬜ - не активен",
        reply_markup=get_game_status_menu(game_statuses, new_active)
    )

@router.callback_query(F.data == "status_glc")
async def status_glc_menu(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    
    glc_statuses = db.get_user_glc_statuses(callback.from_user.id)
    active_glc = user.get('active_glc_status', '')
    
    if not glc_statuses and not active_glc:
        await callback.message.edit_text(
            "💎 <b>GLC статусы</b>\n\nУ тебя нет купленных статусов.\nКупи статус в магазине!",
            reply_markup=get_back_button()
        )
        await callback.answer()
        return
    
    text = (
        f"💎 <b>GLC статусы</b>\n\n"
        f"Выбери статус, который будет отображаться в топах.\n\n"
        f"✅ - активен, ⬜ - не активен"
    )
    
    await callback.message.edit_text(text, reply_markup=get_glc_status_menu(glc_statuses, active_glc))
    await callback.answer()

@router.callback_query(F.data.startswith("activate_glc_"))
async def activate_glc_status(callback: CallbackQuery):
    key = callback.data.replace("activate_glc_", "")
    user_id = callback.from_user.id
    
    conn = db.get_connection()
    
    if key == "none":
        conn.execute("UPDATE users SET active_glc_status = '' WHERE user_id = ?", (user_id,))
        await callback.answer("✅ Статус убран", show_alert=True)
    else:
        if not db.has_glc_status(user_id, key):
            await callback.answer("❌ У тебя нет этого статуса!", show_alert=True)
            return
        status = GLC_STATUSES[key]
        conn.execute("UPDATE users SET active_glc_status = ? WHERE user_id = ?", (status['icon'], user_id))
        await callback.answer(f"✅ Статус {status['icon']} {status['name']} активирован!", show_alert=True)
    
    conn.commit()
    
    user = db.get_user(user_id)
    glc_statuses = db.get_user_glc_statuses(user_id)
    active_glc = user.get('active_glc_status', '')
    
    await callback.message.edit_text(
        "💎 <b>GLC статусы</b>\n\nВыбери статус, который будет отображаться в топах.\n\n✅ - активен, ⬜ - не активен",
        reply_markup=get_glc_status_menu(glc_statuses, active_glc)
    )

@router.callback_query(F.data == "status_active")
async def status_active(callback: CallbackQuery):
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Не зарегистрирован", show_alert=True)
        return
    
    active_game = user.get('active_game_status', 'Не выбраны')
    active_glc = user.get('active_glc_status', 'Не выбран')
    
    text = (
        f"🏆 <b>Твои активные статусы</b>\n\n"
        f"🎮 <b>Статусы за топы:</b>\n"
        f"{' '.join(active_game) if active_game != 'Не выбраны' else 'Не выбраны'}\n\n"
        f"💎 <b>GLC статус:</b>\n"
        f"{active_glc if active_glc != 'Не выбран' else 'Не выбран'}\n\n"
        f"Изменить настройки можно в меню выше."
    )
    
    await callback.message.edit_text(text, reply_markup=get_active_status_menu(active_game, active_glc))
    await callback.answer()

# ==================== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ МЕНЮ ====================
@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("🎮 Главное меню:", reply_markup=get_main_menu())
    await callback.answer()

@router.callback_query(F.data == "casino_menu")
async def casino_menu(callback: CallbackQuery):
    await callback.message.edit_text("🎰 <b>Казино Лудик</b>\n\nВыбери игру:", reply_markup=get_casino_menu())
    await callback.answer()

# ==================== КНОПКИ ИГР ====================
@router.callback_query(F.data == "game_roulette")
async def game_roulette_callback(callback: CallbackQuery):
    await callback.message.answer(
        "🃏 <b>Рулетка</b>\n\n"
        "Команда: <code>рул [цвет/число] [ставка]</code>\n"
        "Пример: <code>рул красное 1000</code>\n\n"
        "Доступные ставки:\n"
        "• красное/черное (x2)\n"
        "• число 0-36 (x36)\n"
        "• ряд1/ряд2/ряд3 (x3)\n"
        "• 1-12/13-24/25-36 (x3)\n"
        "• 1-18/19-36 (x2)\n"
        "• чёт/нечёт (x2)\n"
        "• столбец1-12 (x12)"
    )
    await callback.answer()

@router.callback_query(F.data == "game_slots")
async def game_slots_callback(callback: CallbackQuery):
    await callback.message.answer(
        "🎰 <b>Слоты</b>\n\n"
        "Команда: <code>слоты [ставка]</code>\n"
        "Пример: <code>слоты 1000</code>\n\n"
        "Выигрышные комбинации:\n"
        "• 7️⃣7️⃣7️⃣ — x10 (ДЖЕКПОТ)\n"
        "• 💎💎💎 — x5\n"
        "• 🍋🍋🍋 — x3\n"
        "• 🍒🍒🍒 — x3"
    )
    await callback.answer()

@router.callback_query(F.data == "game_dice")
async def game_dice_callback(callback: CallbackQuery):
    await callback.message.answer(
        "🎲 <b>Кости (дуэль)</b>\n\n"
        "Команда: <code>кости [ставка]</code>\n"
        "Пример: <code>кости 1000</code>\n\n"
        "Правила:\n"
        "1. Создаёшь дуэль\n"
        "2. Другой игрок принимает вызов\n"
        "3. Бот кидает кости\n"
        "4. У кого больше очков - тот забирает банк"
    )
    await callback.answer()

@router.callback_query(F.data == "game_mines")
async def game_mines_callback(callback: CallbackQuery):
    await callback.message.answer(
        "💣 <b>Мины</b>\n\n"
        "Команда: <code>мины [ставка]</code>\n"
        "Пример: <code>мины 1000</code>\n\n"
        "Правила:\n"
        "• Открывай клетки\n"
        "• Чем больше открыл — тем выше множитель\n"
        "• Попал на мину — проигрыш"
    )
    await callback.answer()

@router.callback_query(F.data == "game_blackjack")
async def game_blackjack_callback(callback: CallbackQuery):
    await callback.message.answer(
        "🃏 <b>Блэкджек (21)</b>\n\n"
        "Команда: <code>бджек [ставка]</code>\n"
        "Пример: <code>бджек 1000</code>\n\n"
        "Правила:\n"
        "• Нужно набрать 21 или ближе к дилеру\n"
        "• Туз = 11 или 1\n"
        "• J, Q, K = 10 очков"
    )
    await callback.answer()

@router.callback_query(F.data == "game_under7over")
async def game_under7over_callback(callback: CallbackQuery):
    await callback.message.answer(
        "💎 <b>Under 7 Over (Premium)</b>\n\n"
        "Команда: <code>u7o [под/над/ровно] [ставка]</code>\n"
        "Пример: <code>u7o под 1000</code>\n\n"
        "Правила:\n"
        "• Угадай сумму двух костей\n"
        "• <b>Под</b> (меньше 7) — x2\n"
        "• <b>Над</b> (больше 7) — x2\n"
        "• <b>Ровно 7</b> — x4\n\n"
        "⚠️ <b>ВНИМАНИЕ:</b> Игра только за GLC! Минимальная ставка: 1000 GLC"
    )
    await callback.answer()

# ==================== ЛОТЕРЕЯ ====================
@router.callback_query(F.data == "lottery_menu")
async def lottery_menu(callback: CallbackQuery):
    now = datetime.now()
    week = f"{now.year}-{now.isocalendar()[1]}"
    conn = db.get_connection()
    
    total_result = conn.execute("SELECT COALESCE(SUM(ticket_count),0) FROM lottery_tickets WHERE week_number = ?", (week,)).fetchone()
    total = total_result[0] if total_result else 0
    
    user_result = conn.execute("SELECT COALESCE(ticket_count,0) FROM lottery_tickets WHERE user_id = ? AND week_number = ?", (callback.from_user.id, week)).fetchone()
    user_tickets = user_result[0] if user_result else 0
    
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

# ==================== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (СОКРАЩЕННО) ====================
# ... (здесь идут остальные обработчики, которые не изменились)
# Для экономии места, я не буду дублировать весь код,
# но все остальные функции (donate_menu, get_bonus, business_menu, my_stats, top_menu, top_category, activate_promo, referral_menu, glc_info, glc_balance, glc_shop, shop_page, buy_status, glc_inventory, inventory_page, activate_status_callback, glc_menu, info, check_sub) остаются без изменений

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
    
    game_status = get_user_status(message.from_user.id)
    glc_statuses = db.get_user_glc_statuses(message.from_user.id)
    active_glc = user.get('active_glc_status', '')
    
    glc_icons = []
    for s in glc_statuses:
        if s['status_icon'] == active_glc:
            glc_icons.append(f"⭐ {s['status_icon']}")
        else:
            glc_icons.append(f"⬜ {s['status_icon']}")
    glc_text = " ".join(glc_icons) if glc_icons else "Нет статусов"
    
    active_game = user.get('active_game_status', '')
    game_icons = ' '.join(active_game) if active_game else "Не выбраны"
    
    admin_verified = user.get('is_admin_verified', 0)
    is_sponsor = user.get('is_sponsor', 0)
    sponsor_name = user.get('sponsor_name', '')
    
    text = f"🪙 Баланс LC: {user['balance_lc']}\n💰 Баланс GLC: {user['balance_glc']}\n"
    
    if game_icons != "Не выбраны":
        text += f"\n🏆 <b>Твои статусы за топ:</b> {game_icons}\n"
    
    text += f"💎 <b>Статусы за GLC:</b>\n{glc_text}\n"
    
    if admin_verified:
        text += "\n✅ Вы верифицированный администратор!"
    if is_sponsor:
        text += f"\n☑️ Вы являетесь спонсором бота: {sponsor_name}"
    
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

# ==================== UNDER 7 OVER ====================
@router.message(F.text.lower().startswith(("u7o", "under7over")))
async def play_under7over_game(message: Message):
    parts = message.text.lower().split()
    if len(parts) < 3:
        await message.answer("❌ Формат: u7o [под/над/ровно] [ставка]\nПример: u7o под 1000")
        return
    
    bet_type = parts[1]
    if bet_type not in ["под", "над", "ровно"]:
        await message.answer("❌ Выбери: под, над или ровно")
        return
    
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
    
    MIN_BET_GLC = 1000
    
    if bet < MIN_BET_GLC:
        await message.answer(f"❌ Минимальная ставка: {MIN_BET_GLC} GLC")
        return
    if bet > MAX_BET:
        await message.answer(f"❌ Максимальная ставка: {MAX_BET} GLC")
        return
    if bet > user['balance_glc']:
        await message.answer("❌ Недостаточно GLC!")
        return
    
    db.update_glc(message.from_user.id, -bet)
    
    win, multiplier, dice1, dice2, total = play_under7over(bet_type)
    
    result_text = f"🎲 <b>Under 7 Over</b>\n\n"
    result_text += f"🎲 Кость 1: {dice1}\n"
    result_text += f"🎲 Кость 2: {dice2}\n"
    result_text += f"📊 Сумма: {total}\n\n"
    
    if win:
        win_amount = bet * multiplier
        db.update_glc(message.from_user.id, win_amount)
        db.add_game_stat(message.from_user.id, "under7over", True, bet, win_amount)
        update_user_status(message.from_user.id)
        
        new_user = db.get_user(message.from_user.id)
        new_balance = new_user['balance_glc']
        
        result_text += f"🎉 <b>Ты выиграл!</b>\n"
        result_text += f"📈 Коэффициент: x{multiplier}\n"
        result_text += f"💎 Выигрыш: +{win_amount} GLC\n"
        result_text += f"💰 Баланс GLC: {new_balance}"
    else:
        db.add_game_stat(message.from_user.id, "under7over", False, bet, 0)
        update_user_status(message.from_user.id)
        
        new_user = db.get_user(message.from_user.id)
        new_balance = new_user['balance_glc']
        
        result_text += f"💔 <b>Ты проиграл!</b>\n"
        result_text += f"💰 Потеряно: {bet} GLC\n"
        result_text += f"💰 Баланс GLC: {new_balance}"
    
    await message.answer(result_text)

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

# ==================== АДМИН-КОМАНДЫ (КРАТКО) ====================
# ... (админ-команды остаются без изменений, их слишком много для этого сообщения)
# Но они все присутствуют в полной версии файла

# ==================== ЗАПУСК ====================
async def create_start_promos():
    conn = db.get_connection()
    conn.execute("INSERT OR IGNORE INTO promocodes (code, reward, max_uses) VALUES ('NEW', 2500, 1)")
    conn.execute("INSERT OR IGNORE INTO promocodes (code, reward, max_uses) VALUES ('mëpтв', 25000, 25)")
    conn.commit()

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
