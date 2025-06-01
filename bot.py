import os
import sqlite3
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any
from dotenv import load_dotenv
from aiohttp import web, web_request
import aiohttp_cors
from aiohttp.web import Application as WebApplication

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,  # Более подробные логи
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
        """Добавление транзакции"""
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
        monthly_stats = self.get_monthly_stats(user_id)
        transactions = self.get_user_transactions(user_id, 10)
        
        result = {
            'balance': balance,
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

def get_main_keyboard():
    """Главная клавиатура с Web App"""
    # Замени на свой реальный GitHub Pages URL
    webapp_url = os.getenv("WEBAPP_URL", "https://your-username.github.io/your-repo-name/webapp.html")
    
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

🚀 *Веб-приложение:*
Нажми "🚀 Открыть приложение" для современного интерфейса

*Добавление транзакций:*
1. Нажми "💰 Добавить доход" или "💸 Добавить расход"
2. Выбери категорию (для расходов)
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

async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда синхронизации данных для веб-приложения"""
    user_id = update.effective_user.id
    
    logger.info(f"Команда синхронизации для пользователя {user_id}")
    
    try:
        user_stats = tracker.get_user_stats(user_id)
        
        stats_text = "🔄 *Синхронизация данных*\n\n"
        stats_text += f"💰 *Текущий баланс:* {user_stats['balance']:.2f} ₽\n\n"
        
        if user_stats['monthlyStats']['total_income'] > 0:
            stats_text += f"📈 *Доходы за месяц:* {user_stats['monthlyStats']['total_income']:.2f} ₽\n"
        
        if user_stats['monthlyStats']['total_expense'] > 0:
            stats_text += f"📉 *Расходы за месяц:* {user_stats['monthlyStats']['total_expense']:.2f} ₽\n"
            for category, amount in user_stats['monthlyStats']['expense'].items():
                stats_text += f"　• {category}: {amount:.2f} ₽\n"
        
        if len(user_stats['recentTransactions']) > 0:
            stats_text += f"\n📝 *Последние транзакции:*\n"
            for transaction in user_stats['recentTransactions'][:5]:
                icon = "💰" if transaction['type'] == 'income' else "💸"
                stats_text += f"{icon} {transaction['amount']:.2f} ₽ - {transaction['category']}\n"
        
        stats_text += f"\n✅ *Данные актуальны на {datetime.now().strftime('%d.%m.%Y %H:%M')}*"
        
        await update.message.reply_text(stats_text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Ошибка синхронизации для пользователя {user_id}: {e}")
        await update.message.reply_text("❌ Ошибка при получении данных")

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из Web App"""
    try:
        user_id = update.effective_user.id
        data = json.loads(update.effective_message.web_app_data.data)
        
        logger.info(f"Получены данные от Web App: {data}")
        
        action = data.get('action')
        
        if action == 'get_data':
            # Запрос данных пользователя
            logger.info(f"Запрос данных для пользователя {user_id}")
            user_stats = tracker.get_user_stats(user_id)
            
            # Отправляем данные обратно (можно через inline кнопку или просто сообщение)
            stats_text = f"📊 *Ваши данные:*\n\n"
            stats_text += f"💰 Баланс: {user_stats['balance']:.2f} ₽\n"
            stats_text += f"📈 Доходы за месяц: {user_stats['monthlyStats']['total_income']:.2f} ₽\n"
            stats_text += f"📉 Расходы за месяц: {user_stats['monthlyStats']['total_expense']:.2f} ₽\n"
            stats_text += f"🔄 Данные синхронизированы!"
            
            await update.message.reply_text(stats_text, parse_mode="Markdown")
            
        elif action == 'add_transaction':
            # Добавление транзакции
            logger.info(f"Добавление транзакции через Web App для пользователя {user_id}")
            
            tracker.add_transaction(
                user_id=user_id,
                transaction_type=data['type'],
                amount=data['amount'],
                category=data['category'],
                description=data.get('description', '')
            )
            
            transaction_type_text = "Доход" if data['type'] == 'income' else "Расход"
            await update.message.reply_text(
                f"✅ {transaction_type_text} добавлен через приложение!\n\n"
                f"💰 {data['amount']:.2f} ₽\n"
                f"📂 {data['category']}\n"
                f"📝 {data.get('description', '')}"
            )
        else:
            logger.warning(f"Неизвестное действие Web App: {action}")
            await update.message.reply_text("❌ Неизвестная команда от приложения")
        
    except Exception as e:
        logger.error(f"Ошибка обработки Web App данных: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при обработке данных приложения")

# API обработчики для веб-приложения
async def api_get_user_data(request):
    """API для получения данных пользователя"""
    try:
        logger.info(f"API запрос get_user_data: {request.query}")
        
        # Получаем user_id из параметров запроса
        user_id = request.query.get('user_id')
        if not user_id:
            logger.warning("API запрос без user_id")
            return web.json_response({'error': 'user_id required'}, status=400)
        
        user_id = int(user_id)
        logger.info(f"Обработка запроса данных для пользователя {user_id}")
        
        user_data = tracker.get_user_stats(user_id)
        
        logger.info(f"Возвращаем данные пользователя {user_id}: {user_data}")
        return web.json_response(user_data)
        
    except Exception as e:
        logger.error(f"Ошибка API get_user_data: {e}", exc_info=True)
        return web.json_response({'error': 'Internal server error'}, status=500)

async def api_add_transaction(request):
    """API для добавления транзакции"""
    try:
        logger.info("API запрос add_transaction")
        data = await request.json()
        logger.info(f"Данные транзакции: {data}")
        
        user_id = data.get('user_id')
        transaction_type = data.get('type')
        amount = float(data.get('amount'))
        category = data.get('category')
        description = data.get('description', '')
        
        if not all([user_id, transaction_type, amount, category]):
            logger.warning(f"Неполные данные транзакции: {data}")
            return web.json_response({'error': 'Missing required fields'}, status=400)
        
        logger.info(f"Добавление транзакции через API для пользователя {user_id}")
        tracker.add_transaction(user_id, transaction_type, amount, category, description)
        
        # Возвращаем обновленные данные
        user_data = tracker.get_user_stats(user_id)
        logger.info(f"Транзакция добавлена, возвращаем обновленные данные")
        return web.json_response({'success': True, 'data': user_data})
        
    except Exception as e:
        logger.error(f"Ошибка API add_transaction: {e}", exc_info=True)
        return web.json_response({'error': 'Internal server error'}, status=500)

async def create_web_app():
    """Создание веб-приложения для API"""
    logger.info("Создание веб-приложения для API")
    
    app = WebApplication()
    
    # Настройка CORS
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        )
    })
    
    # API маршруты
    app.router.add_get('/api/user-data', api_get_user_data)
    app.router.add_post('/api/add-transaction', api_add_transaction)
    
    # Добавляем простой тестовый роут
    async def health_check(request):
        logger.info("Health check запрос")
        return web.json_response({'status': 'ok', 'message': 'API работает'})
    
    app.router.add_get('/health', health_check)
    
    # Добавляем CORS для всех маршрутов
    for route in list(app.router.routes()):
        cors.add(route)
    
    logger.info("Веб-приложение создано")
    return app
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

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка данных из Web App"""
    try:
        user_id = update.effective_user.id
        data = json.loads(update.effective_message.web_app_data.data)
        
        # Добавляем транзакцию из Web App
        tracker.add_transaction(
            user_id=user_id,
            transaction_type=data['type'],
            amount=data['amount'],
            category=data['category'],
            description=data.get('description', '')
        )
        
        transaction_type_text = "Доход" if data['type'] == 'income' else "Расход"
        await update.message.reply_text(
            f"✅ {transaction_type_text} добавлен через приложение!\n\n"
            f"💰 {data['amount']:.2f} ₽\n"
            f"📂 {data['category']}\n"
            f"📝 {data.get('description', '')}"
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки Web App данных: {e}")
        await update.message.reply_text("❌ Ошибка при сохранении данных")

import asyncio

def main():
    """Запуск бота"""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Ошибка: Токен бота не найден!")
        print("📝 Создайте файл .env и добавьте: BOT_TOKEN=ваш_токен_от_BotFather")
        return
    
    async def start_bot_and_server():
        # Создаем и запускаем API сервер
        web_app = await create_web_app()
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8080)
        await site.start()
        print("🌐 API сервер запущен на http://localhost:8080")
        
        # Создаем и запускаем бота
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Добавление обработчиков
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("sync", sync_command))
        application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        print("🤖 Бот запущен!")
        print(f"📁 База данных: {DATABASE_PATH}")
        
        # Запускаем бота
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Ждем бесконечно
        try:
            await asyncio.Future()  # Ждем вечно
        except KeyboardInterrupt:
            print("Остановка...")
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
            await runner.cleanup()
    
    # Запускаем все
    asyncio.run(start_bot_and_server())

if __name__ == "__main__":
    main()