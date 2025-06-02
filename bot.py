import os
import sqlite3
import logging
import json
import urllib.parse
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any
from dotenv import load_dotenv
from aiohttp import web
import aiohttp_cors

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
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
        """Добавление транзакции с валидацией"""
        # ✅ Добавлена валидация
        if amount <= 0:
            raise ValueError("Сумма должна быть положительной")
        if amount > 1000000:  # Лимит на сумму
            raise ValueError("Сумма слишком большая")
        if transaction_type not in ['income', 'expense']:
            raise ValueError("Неверный тип транзакции")
        
        logger.info(f"Добавление транзакции: user_id={user_id}, type={transaction_type}, amount={amount}, category={category}")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute('''
            INSERT INTO transactions (user_id, type, amount, category, description, date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, transaction_type, amount, category, description, date_str))
        
        conn.commit()
        conn.close()
        logger.info(f"Транзакция успешно добавлена для пользователя {user_id}")
    
    def get_user_balance(self, user_id: int) -> float:
        """Получение баланса пользователя"""
        logger.debug(f"Получение баланса для пользователя {user_id}")
        
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
        
        logger.debug(f"Баланс пользователя {user_id}: {balance}")
        return balance
    
    def get_daily_stats(self, user_id: int) -> Dict[str, Any]:
        """Получение статистики за день"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Получаем текущую дату
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute('''
            SELECT type, category, SUM(amount) FROM transactions 
            WHERE user_id = ? AND date(date) = ? 
            GROUP BY type, category
        ''', (user_id, today_str))
        
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
    
    def get_weekly_stats(self, user_id: int) -> Dict[str, Any]:
        """Получение статистики за неделю"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Получаем дату начала недели (понедельник)
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())
        week_start_str = week_start.strftime("%Y-%m-%d")
        
        cursor.execute('''
            SELECT type, category, SUM(amount) FROM transactions 
            WHERE user_id = ? AND date >= ? 
            GROUP BY type, category
        ''', (user_id, week_start_str))
        
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
    
    def get_user_transactions(self, user_id: int, limit: int = 50) -> list:
        """Получение последних транзакций пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT type, amount, category, description, date 
            FROM transactions 
            WHERE user_id = ? 
            ORDER BY date DESC 
            LIMIT ?
        ''', (user_id, limit))
        
        results = cursor.fetchall()
        conn.close()
        
        transactions = []
        for row in results:
            transactions.append({
                'type': row[0],
                'amount': row[1],
                'category': row[2],
                'description': row[3],
                'date': row[4]
            })
        
        return transactions

    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Получение полной статистики пользователя"""
        logger.info(f"Получение полной статистики для пользователя {user_id}")
        
        balance = self.get_user_balance(user_id)
        daily_stats = self.get_daily_stats(user_id)
        weekly_stats = self.get_weekly_stats(user_id)
        monthly_stats = self.get_monthly_stats(user_id)
        transactions = self.get_user_transactions(user_id, 10)
        
        result = {
            'balance': balance,
            'dailyStats': daily_stats,
            'weeklyStats': weekly_stats,
            'monthlyStats': monthly_stats,
            'recentTransactions': transactions
        }
        
        logger.info(f"Статистика пользователя {user_id}: balance={balance}, transactions_count={len(transactions)}")
        return result

# Инициализация трекера
tracker = FinanceTracker()

# Категории для быстрого выбора
EXPENSE_CATEGORIES = ["Кофе", "Заведение", "Одежда", "Косметика", "Транспорт", "Здоровье"]

# Состояния пользователей
user_states = {}

def get_main_keyboard(user_id: int):
    """Главная клавиатура с веб-приложением"""
    webapp_url = get_webapp_url_with_data(user_id)
    
    logger.info(f"🔧 Создание клавиатуры для пользователя {user_id}")
    logger.info(f"🌐 Сгенерированный URL: {webapp_url}")
    
    keyboard = [
        [KeyboardButton("🚀 Открыть приложение", web_app=WebAppInfo(url=webapp_url))],
        [KeyboardButton("📊 Баланс"), KeyboardButton("📈 Статистика")],
        [KeyboardButton("💰 Добавить доход"), KeyboardButton("💸 Добавить расход")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_stats_keyboard():
    """Клавиатура для выбора периода статистики"""
    keyboard = [
        [KeyboardButton("📅 За день"), KeyboardButton("📆 За неделю")],
        [KeyboardButton("🗓️ За месяц")],
        [KeyboardButton("🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_webapp_url_with_data(user_id: int) -> str:
    """Создание URL веб-приложения с данными пользователя"""
    try:
        base_url = os.getenv("WEBAPP_URL", "https://your-username.github.io/your-repo-name/webapp.html")
        
        logger.info(f"Создание URL с данными для пользователя {user_id}")
        
        user_stats = tracker.get_user_stats(user_id)
        
        logger.debug(f"Данные пользователя для URL: {user_stats}")
        
        balance = user_stats.get('balance', 0)
        daily_stats = user_stats.get('dailyStats', {})
        weekly_stats = user_stats.get('weeklyStats', {})
        monthly_stats = user_stats.get('monthlyStats', {})
        
        # Обработка дневной статистики
        if daily_stats is None:
            daily_stats = {"income": {}, "expense": {}, "total_income": 0, "total_expense": 0}
        
        daily_income = daily_stats.get('total_income', 0)
        daily_expense = daily_stats.get('total_expense', 0)
        daily_expense_categories = daily_stats.get('expense', {})
        
        # Обработка недельной статистики
        if weekly_stats is None:
            weekly_stats = {"income": {}, "expense": {}, "total_income": 0, "total_expense": 0}
        
        weekly_income = weekly_stats.get('total_income', 0)
        weekly_expense = weekly_stats.get('total_expense', 0)
        weekly_expense_categories = weekly_stats.get('expense', {})
        
        # Обработка месячной статистики
        if monthly_stats is None:
            monthly_stats = {"income": {}, "expense": {}, "total_income": 0, "total_expense": 0}
        
        monthly_income = monthly_stats.get('total_income', 0)
        monthly_expense = monthly_stats.get('total_expense', 0)
        monthly_expense_categories = monthly_stats.get('expense', {})
        
        data = {
            'balance': balance,
            'dailyIncome': daily_income,
            'dailyExpense': daily_expense,
            'dailyExpenses': json.dumps(daily_expense_categories),
            'weeklyIncome': weekly_income,
            'weeklyExpense': weekly_expense,
            'weeklyExpenses': json.dumps(weekly_expense_categories),
            'monthlyIncome': monthly_income,
            'monthlyExpense': monthly_expense,
            'monthlyExpenses': json.dumps(monthly_expense_categories),
            'timestamp': int(time.time()),
            'user_id': user_id
        }
        
        query_string = urllib.parse.urlencode(data)
        final_url = f"{base_url}?{query_string}"
        
        logger.info(f"Создан уникальный URL: {final_url}")
        return final_url
        
    except Exception as e:
        logger.error(f"Ошибка создания URL с данными: {e}")
        return os.getenv("WEBAPP_URL", "https://your-username.github.io/your-repo-name/webapp.html")

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
• Статистика за день, неделю и месяц
• Категоризация транзакций

Используй кнопки меню для навигации!
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи"""
    help_text = """
📖 *Как пользоваться ботом:*

🚀 *Веб-приложение:*
Нажми "🚀 Открыть приложение" для современного интерфейса

*Добавление транзакций:*
1. Нажми "💰 Добавить доход" или "💸 Добавить расход"
2. Выбери категорию (для расходов)
3. Введи сумму (например: 1500 или 1500 за обед)

*Просмотр данных:*
• "📊 Баланс" - текущий баланс
• "📈 Статистика" - данные за день, неделю или месяц

*Примеры ввода суммы:*
• `1500`
• `1500 зарплата`
• `500 обед в кафе`
"""
    
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для обновления веб-приложения с актуальными данными"""
    user_id = update.effective_user.id
    
    logger.info(f"Команда /refresh для пользователя {user_id}")
    
    user_stats = tracker.get_user_stats(user_id)
    balance = user_stats.get('balance', 0)
    
    await update.message.reply_text(
        f"🔄 *Данные обновлены через команду!*\n\n💰 Актуальный баланс: *{balance:.2f} ₽*",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из Web App"""
    try:
        user_id = update.effective_user.id
        data = json.loads(update.effective_message.web_app_data.data)
        
        logger.info(f"Получены данные от Web App от пользователя {user_id}: {data}")
        
        # Проверяем, это одна транзакция или пакет
        if 'transactions' in data:
            # Обработка пакета транзакций (при синхронизации)
            transactions = data['transactions']
            total_income = 0
            total_expense = 0
            
            for transaction in transactions:
                tracker.add_transaction(
                    user_id=user_id,
                    transaction_type=transaction['type'],
                    amount=float(transaction['amount']),
                    category=transaction['category'],
                    description=transaction.get('description', '')
                )
                
                if transaction['type'] == 'income':
                    total_income += float(transaction['amount'])
                else:
                    total_expense += float(transaction['amount'])
            
            new_balance = tracker.get_user_balance(user_id)
            
            await update.message.reply_text(
                f"✅ Синхронизация завершена!\n\n"
                f"📊 Добавлено транзакций: {len(transactions)}\n"
                f"💰 Общий доход: {total_income:.2f} ₽\n"
                f"💸 Общий расход: {total_expense:.2f} ₽\n\n"
                f"🔄 *Новый баланс: {new_balance:.2f} ₽*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
            
        else:
            # Обработка одной транзакции (старый формат для совместимости)
            if 'type' not in data or 'amount' not in data or 'category' not in data:
                raise ValueError("Неполные данные транзакции")
            
            tracker.add_transaction(
                user_id=user_id,
                transaction_type=data['type'],
                amount=float(data['amount']),
                category=data['category'],
                description=data.get('description', '')
            )
            
            new_balance = tracker.get_user_balance(user_id)
            
            transaction_type_text = "Доход" if data['type'] == 'income' else "Расход"
            await update.message.reply_text(
                f"✅ {transaction_type_text} добавлен через приложение!\n\n"
                f"💰 {data['amount']:.2f} ₽\n"
                f"📂 {data['category']}\n"
                f"📝 {data.get('description', '')}\n\n"
                f"🔄 *Новый баланс: {new_balance:.2f} ₽*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
        
    except Exception as e:
        logger.error(f"Ошибка обработки Web App данных: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при обработке данных приложения")
        
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in user_states:
        user_states[user_id] = {"state": "main"}
    
    state = user_states[user_id]["state"]
    
    if text == "🔙 Назад":
        user_states[user_id] = {"state": "main"}
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    if state == "main":
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
            user_states[user_id] = {"state": "select_stats_period"}
            await update.message.reply_text(
                "📊 Выбери период для статистики:",
                reply_markup=get_stats_keyboard()
            )
            
        elif text == "❓ Помощь":
            await help_command(update, context)
    
    elif state == "select_stats_period":
        if text == "📅 За день":
            stats = tracker.get_daily_stats(user_id)
            period_text = "день"
            
        elif text == "📆 За неделю":
            stats = tracker.get_weekly_stats(user_id)
            period_text = "неделю"
            
        elif text == "🗓️ За месяц":
            stats = tracker.get_monthly_stats(user_id)
            period_text = "месяц"
            
        else:
            return
        
        # Формируем текст статистики
        stats_text = f"📈 *Статистика за {period_text}:*\n\n"
        
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
        
        if stats["total_income"] == 0 and stats["total_expense"] == 0:
            stats_text = f"📈 *Статистика за {period_text}:*\n\n📭 Нет транзакций за выбранный период"
        
        await update.message.reply_text(
            stats_text, 
            parse_mode="Markdown", 
            reply_markup=get_main_keyboard(user_id)
        )
        user_states[user_id] = {"state": "main"}
    
    elif state == "select_expense_category":
        if text in EXPENSE_CATEGORIES:
            user_states[user_id] = {"state": "enter_expense_amount", "category": text}
            await update.message.reply_text(
                f"💸 Категория: *{text}*\n\nВведи сумму расхода:",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
            )
    
    elif state == "enter_income_amount":
        try:
            parts = text.split(maxsplit=1)
            amount = float(parts[0])
            description = parts[1] if len(parts) > 1 else ""
            
            tracker.add_transaction(user_id, "income", amount, "Доход", description)
            
            new_balance = tracker.get_user_balance(user_id)
            logger.info(f"🔄 После добавления дохода: новый баланс = {new_balance}")
            
            await update.message.reply_text(
                f"✅ Доход добавлен!\n\n💰 *{amount:.2f} ₽*\n📝 {description}",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
            user_states[user_id] = {"state": "main"}
            
        except ValueError as e:
            await update.message.reply_text(
                f"❌ Ошибка: {str(e)}\n\nПример: `1500` или `1500 описание`",
                parse_mode="Markdown"
            )
    
    elif state == "enter_expense_amount":
        try:
            parts = text.split(maxsplit=1)
            amount = float(parts[0])
            description = parts[1] if len(parts) > 1 else ""
            
            category = user_states[user_id]["category"]
            tracker.add_transaction(user_id, "expense", amount, category, description)
            
            await update.message.reply_text(
                f"✅ Расход добавлен!\n\n💸 *{amount:.2f} ₽*\n📂 {category}\n📝 {description}",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
            user_states[user_id] = {"state": "main"}
            
        except ValueError as e:
            await update.message.reply_text(
                f"❌ Ошибка: {str(e)}\n\nПример: `500` или `500 обед`",
                parse_mode="Markdown"
            )

def main():
    """Запуск бота"""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Ошибка: Токен бота не найден!")
        print("📝 Создайте файл .env и добавьте: BOT_TOKEN=ваш_токен_от_BotFather")
        return
    
    print("🤖 Инициализация бота...")
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("refresh", refresh_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    application.add_handler(MessageHandler(filters.TEXT, handle_message))
    
    print("🤖 Бот запущен!")
    print(f"📁 База данных: {DATABASE_PATH}")
    print("📨 Ожидание сообщений...")
    
    # Запускаем бота
    application.run_polling()

if __name__ == "__main__":
    main()