import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_PATH = os.getenv("DATABASE_PATH", "finance_tracker.db")

class FinanceTracker:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_PATH
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                date TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_transaction(self, user_id: int, transaction_type: str, amount: float, 
                       category: str, description: str = ""):
        """Добавление транзакции"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, category, description, date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, transaction_type, amount, category, description, date_str))
        
        conn.commit()
        conn.close()
    
    def get_user_balance(self, user_id: int) -> float:
        """Получение баланса пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT type, SUM(amount) FROM transactions 
            WHERE user_id = ? GROUP BY type
        ''', (user_id,))
        
        results = cursor.fetchall()
        conn.close()
        
        balance = 0
        for transaction_type, amount in results:
            if transaction_type == "income":
                balance += amount
            else:
                balance -= amount
        
        return balance
    
    def get_monthly_stats(self, user_id: int) -> Dict[str, Any]:
        """Получение статистики за месяц"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        
        cursor.execute('''
            SELECT type, category, SUM(amount) FROM transactions 
            WHERE user_id = ? AND date >= ? 
            GROUP BY type, category
        ''', (user_id, month_start))
        
        results = cursor.fetchall()
        conn.close()
        
        stats = {"income": {}, "expense": {}, "total_income": 0, "total_expense": 0}
        
        for transaction_type, category, amount in results:
            if transaction_type == "income":
                stats["income"][category] = amount
                stats["total_income"] += amount
            else:
                stats["expense"][category] = amount
                stats["total_expense"] += amount
        
        return stats

# Инициализация трекера
tracker = FinanceTracker()

# Категории для быстрого выбора
EXPENSE_CATEGORIES = ["Кофе", "Заведение", "Одежда", "Косметика", "Транспорт", "Здоровье"]

# Состояния пользователей
user_states = {}

def get_main_keyboard():
    """Главная клавиатура с Web App"""
    # URL твоего размещенного HTML файла
    webapp_url = "https://yourdomain.com/webapp.html"  # Замени на свой URL
    
    keyboard = [
        [KeyboardButton("🚀 Открыть приложение", web_app=WebAppInfo(url=webapp_url))],
        [KeyboardButton("📊 Баланс"), KeyboardButton("📈 Статистика")],
        [KeyboardButton("💰 Добавить доход"), KeyboardButton("💸 Добавить расход")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_category_keyboard(transaction_type: str):
    """Клавиатура с категориями расходов"""
    categories = EXPENSE_CATEGORIES
    keyboard = [[KeyboardButton(cat)] for cat in categories]
    keyboard.append([KeyboardButton("🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    user_states[user_id] = {"state": "main"}
    
    welcome_text = """
🏦 *Финансовый трекер*

Привет! Я помогу тебе отслеживать доходы и расходы.

*Доступные функции:*
• Добавление доходов и расходов
• Просмотр текущего баланса
• Статистика за месяц
• Категоризация транзакций

Используй кнопки меню для навигации!
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи"""
    help_text = """
📖 *Как пользоваться ботом:*

*Добавление транзакций:*
1. Нажми "💰 Добавить доход" или "💸 Добавить расход"
2. Выбери категорию
3. Введи сумму (например: 1500 или 1500 за обед)

*Просмотр данных:*
• "📊 Баланс" - текущий баланс
• "📈 Статистика" - данные за текущий месяц

*Примеры ввода суммы:*
• `1500`
• `1500 зарплата`
• `500 обед в кафе`
"""
    
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Инициализация состояния если нет
    if user_id not in user_states:
        user_states[user_id] = {"state": "main"}
    
    state = user_states[user_id]["state"]
    
    # Обработка кнопки "Назад"
    if text == "🔙 Назад":
        user_states[user_id] = {"state": "main"}
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Главное меню
    if state == "main":
        if text == "💰 Добавить доход":
        if text == "💰 Добавить доход":
            user_states[user_id] = {"state": "enter_income_amount"}
            await update.message.reply_text(
                "💰 Введи сумму дохода:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
            )
            
        elif text == "💸 Добавить расход":
            user_states[user_id] = {"state": "select_expense_category"}
            await update.message.reply_text(
                "Выбери категорию расхода:",
                reply_markup=get_category_keyboard("expense")
            )
            
        elif text == "📊 Баланс":
            balance = tracker.get_user_balance(user_id)
            balance_text = f"💰 *Текущий баланс:* {balance:.2f} ₽"
            
            if balance > 0:
                balance_text += " ✅"
            elif balance < 0:
                balance_text += " ❌"
            else:
                balance_text += " ⚖️"
                
            await update.message.reply_text(balance_text, parse_mode="Markdown")
            
        elif text == "📈 Статистика":
            stats = tracker.get_monthly_stats(user_id)
            
            stats_text = "📈 *Статистика за месяц:*\n\n"
            
            if stats["total_income"] > 0:
                stats_text += f"💰 *Доходы:* {stats['total_income']:.2f} ₽\n"
                for category, amount in stats["income"].items():
                    stats_text += f"  • {category}: {amount:.2f} ₽\n"
                stats_text += "\n"
            
            if stats["total_expense"] > 0:
                stats_text += f"💸 *Расходы:* {stats['total_expense']:.2f} ₽\n"
                for category, amount in stats["expense"].items():
                    stats_text += f"  • {category}: {amount:.2f} ₽\n"
                stats_text += "\n"
            
            difference = stats["total_income"] - stats["total_expense"]
            stats_text += f"📊 *Разница:* {difference:.2f} ₽"
            
            if difference > 0:
                stats_text += " ✅"
            elif difference < 0:
                stats_text += " ❌"
            
            await update.message.reply_text(stats_text, parse_mode="Markdown")
            
        elif text == "❓ Помощь":
            await help_command(update, context)
    
    # Выбор категории расхода
    elif state == "select_expense_category":
        if text in EXPENSE_CATEGORIES:
            user_states[user_id] = {"state": "enter_expense_amount", "category": text}
            await update.message.reply_text(
                f"💸 Категория: *{text}*\n\nВведи сумму расхода:",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
            )
    
    # Ввод суммы дохода (без категории)
    elif state == "enter_income_amount":
        try:
            # Парсинг суммы и описания
            parts = text.split(maxsplit=1)
            amount = float(parts[0])
            description = parts[1] if len(parts) > 1 else ""
            
            tracker.add_transaction(user_id, "income", amount, "Доход", description)
            
            await update.message.reply_text(
                f"✅ Доход добавлен!\n\n💰 *{amount:.2f} ₽*\n📝 {description}",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            user_states[user_id] = {"state": "main"}
            
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат суммы!\n\nПример: `1500` или `1500 описание`",
                parse_mode="Markdown"
            )
    
    # Ввод суммы расхода
    elif state == "enter_expense_amount":
        try:
            # Парсинг суммы и описания
            parts = text.split(maxsplit=1)
            amount = float(parts[0])
            description = parts[1] if len(parts) > 1 else ""
            
            category = user_states[user_id]["category"]
            tracker.add_transaction(user_id, "expense", amount, category, description)
            
            await update.message.reply_text(
                f"✅ Расход добавлен!\n\n💸 *{amount:.2f} ₽*\n📂 {category}\n📝 {description}",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            user_states[user_id] = {"state": "main"}
            
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат суммы!\n\nПример: `500` или `500 обед`",
                parse_mode="Markdown"
            )

def main():
    """Запуск бота"""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Ошибка: Токен бота не найден!")
        print("📝 Создайте файл .env и добавьте: BOT_TOKEN=ваш_токен_от_BotFather")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Бот запущен!")
    print(f"📁 База данных: {DATABASE_PATH}")
    application.run_polling()

if __name__ == "__main__":
    main()
