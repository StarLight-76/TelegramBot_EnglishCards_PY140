"""
EnglishCard Bot - Telegram бот для изучения английских слов
Версия: PostgreSQL с поддержкой .env (исправленная кодировка)
Студент: Дмитрий Кирильчук
Группа: PY-140
"""

import os
import sys
import logging
import random
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from typing import List, Tuple, Optional
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ЯВНО указываем кодировку .env файла
load_dotenv(encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ ПАРАМЕТРЫ ИЗ .env ===============
BOT_TOKEN = os.getenv('BOT_TOKEN')

# ОЧИЩАЕМ значения от возможных скрытых символов
DB_HOST = os.getenv('DB_HOST', 'localhost').strip()
DB_PORT = os.getenv('DB_PORT', '5432').strip()
DB_NAME = os.getenv('DB_NAME', 'english_card').strip()
DB_USER = os.getenv('DB_USER', 'postgres').strip()
DB_PASSWORD = os.getenv('DB_PASSWORD', '').strip()

# Проверка на наличие токена
if not BOT_TOKEN:
    raise ValueError(
        "❌ Токен не найден!\n"
        "Создайте файл .env с содержимым:\n"
        "BOT_TOKEN=ваш_токен_здесь\n"
        "DB_PASSWORD=postgres2026"
    )

# Выводим параметры для отладки (без пароля)
logger.info(f"📁 Загружены параметры:")
logger.info(f"   DB_HOST={DB_HOST}")
logger.info(f"   DB_PORT={DB_PORT}")
logger.info(f"   DB_NAME={DB_NAME}")
logger.info(f"   DB_USER={DB_USER}")
logger.info(f"   DB_PASSWORD={'*' * len(DB_PASSWORD)}")
# ==================================================

# Состояния для разговора
ADDING_WORD, DELETING_WORD = range(2)


class Database:
    """Класс для работы с PostgreSQL базой данных"""

    @staticmethod
    def ensure_database_exists():
        """Проверяет существование БД и создает её при необходимости"""
        try:
            # Подключаемся к стандартной базе данных 'postgres'
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                database="postgres",
                user=DB_USER,
                password=DB_PASSWORD
            )
            conn.autocommit = True
            c = conn.cursor()

            # Проверяем существование нашей БД
            c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
            exists = c.fetchone()

            if not exists:
                # Создаем базу данных
                c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
                logger.info(f"✅ База данных '{DB_NAME}' успешно создана!")
            else:
                logger.info(f"✅ База данных '{DB_NAME}' уже существует")

            conn.close()

        except Exception as e:
            logger.error(f"❌ Ошибка при создании БД: {e}")
            logger.error("Проверьте:")
            logger.error("1. Запущен ли PostgreSQL (служба postgresql)")
            logger.error("2. Правильность пароля в .env файле")
            logger.error("3. Доступность пользователя postgres")
            raise

    @staticmethod
    def get_connection():
        """Получение соединения с нашей БД"""
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            return conn
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к БД '{DB_NAME}': {e}")
            raise

    def __init__(self):
        """Инициализация: создаем БД если нет, затем создаем таблицы"""
        self.ensure_database_exists()
        self.init_db()

    def init_db(self):
        """Создание таблиц и заполнение общими словами"""
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor()

            # Таблица 1: Общие слова для всех пользователей
            c.execute('''
                CREATE TABLE IF NOT EXISTS common_words (
                    id SERIAL PRIMARY KEY,
                    ru_word TEXT UNIQUE NOT NULL,
                    en_word TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица 2: Персональные слова пользователей
            c.execute('''
                CREATE TABLE IF NOT EXISTS user_words (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    ru_word TEXT NOT NULL,
                    en_word TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, ru_word)
                )
            ''')

            # Таблица 3: Статистика изучения слов
            c.execute('''
                CREATE TABLE IF NOT EXISTS user_statistics (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    word_id INTEGER NOT NULL,
                    word_type TEXT CHECK (word_type IN ('common', 'personal')),
                    correct_answers INTEGER DEFAULT 0,
                    total_attempts INTEGER DEFAULT 0,
                    last_reviewed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, word_id, word_type)
                )
            ''')

            # Создаем индексы
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_words_user_id ON user_words(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_statistics_user_id ON user_statistics(user_id)")

            # Заполняем общими словами
            common_words = [
                ('красный', 'red'), ('синий', 'blue'), ('зеленый', 'green'),
                ('желтый', 'yellow'), ('я', 'I'), ('ты', 'you'),
                ('он', 'he'), ('она', 'she'), ('мы', 'we'), ('они', 'they')
            ]

            for ru, en in common_words:
                c.execute(
                    "INSERT INTO common_words (ru_word, en_word) VALUES (%s, %s) ON CONFLICT (ru_word) DO NOTHING",
                    (ru, en)
                )

            conn.commit()
            logger.info("✅ Таблицы успешно созданы")
            logger.info("✅ 10 общих слов загружено")

        except Exception as e:
            logger.error(f"❌ Ошибка при создании таблиц: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    # ... (остальные методы как в вашем коде) ...
    def get_all_words_for_user(self, user_id: int) -> List[Tuple]:
        """Получает все слова для пользователя"""
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor(cursor_factory=RealDictCursor)

            # Общие слова
            c.execute("SELECT id, ru_word, en_word FROM common_words")
            common_rows = c.fetchall()
            common = [(row['ru_word'], row['en_word'], 'common', row['id']) for row in common_rows]

            # Личные слова пользователя
            c.execute("SELECT id, ru_word, en_word FROM user_words WHERE user_id = %s", (user_id,))
            personal_rows = c.fetchall()
            personal = [(row['ru_word'], row['en_word'], 'personal', row['id']) for row in personal_rows]

            all_words = common + personal
            random.shuffle(all_words)
            return all_words
        finally:
            if conn:
                conn.close()

    def add_user_word(self, user_id: int, ru: str, en: str) -> tuple[bool, str]:
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute(
                "INSERT INTO user_words (user_id, ru_word, en_word) VALUES (%s, %s, %s)",
                (user_id, ru.lower(), en.lower())
            )
            conn.commit()
            return True, "✅ Слово успешно добавлено!"
        except psycopg2.IntegrityError:
            return False, "❌ Это слово уже есть в вашем списке!"
        finally:
            if conn:
                conn.close()

    def delete_user_word(self, user_id: int, ru: str) -> tuple[bool, str]:
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute(
                "DELETE FROM user_words WHERE user_id = %s AND ru_word = %s",
                (user_id, ru.lower())
            )
            deleted = c.rowcount > 0
            conn.commit()
            return (True, f"✅ Слово '{ru}' удалено") if deleted else (False, f"❌ Слово '{ru}' не найдено")
        finally:
            if conn:
                conn.close()

    def get_user_personal_words(self, user_id: int) -> List[Tuple]:
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT ru_word, en_word FROM user_words WHERE user_id = %s", (user_id,))
            rows = c.fetchall()
            return [(row['ru_word'], row['en_word']) for row in rows]
        finally:
            if conn:
                conn.close()

    def update_statistics(self, user_id: int, word_id: int, word_type: str, correct: bool):
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute(
                "INSERT INTO user_statistics (user_id, word_id, word_type, correct_answers, total_attempts) "
                "VALUES (%s, %s, %s, %s, 1) "
                "ON CONFLICT (user_id, word_id, word_type) DO UPDATE "
                "SET correct_answers = user_statistics.correct_answers + EXCLUDED.correct_answers, "
                "    total_attempts = user_statistics.total_attempts + 1",
                (user_id, word_id, word_type, 1 if correct else 0)
            )
            conn.commit()
        finally:
            if conn:
                conn.close()


class EnglishCardBot:
    """Основной класс бота"""

    def __init__(self, token: str):
        self.token = token
        self.db = Database()
        self.backup_words = ['dream', 'love', 'life', 'time', 'day', 'night', 'book', 'house', 'car', 'dog']

    @staticmethod
    def get_main_keyboard() -> ReplyKeyboardMarkup:
        keyboard = [
            [KeyboardButton("Дальше 🚀")],
            [KeyboardButton("Добавить слово ✨"), KeyboardButton("Удалить слово")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    @staticmethod
    def get_answer_keyboard(options: List[str]) -> ReplyKeyboardMarkup:
        keyboard = [
            [KeyboardButton(options[0]), KeyboardButton(options[1])],
            [KeyboardButton(options[2]), KeyboardButton(options[3])],
            [KeyboardButton("Дальше 🚀")],
            [KeyboardButton("Добавить слово ✨"), KeyboardButton("Удалить слово")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    def generate_options(self, correct: str, all_words: List[Tuple]) -> List[str]:
        options = [correct]
        all_en = list(set([w[1] for w in all_words if w[1] != correct]))

        while len(options) < 4 and all_en:
            word = random.choice(all_en)
            if word not in options:
                options.append(word)
                all_en.remove(word)

        while len(options) < 4:
            word = random.choice(self.backup_words)
            if word not in options:
                options.append(word)

        random.shuffle(options)
        return options

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        welcome_text = (
            "Привет 👋 Давай попрактикуемся в английском языке. "
            "Тренировки можешь проходить в удобном для себя темпе.\n\n"
            "У тебя есть возможность использовать тренажёр, как конструктор, "
            "и собирать свою собственную базу для обучения. Для этого "
            "воспользуйся инструментами:\n\n"
            "добавить слово ➕,\n"
            "удалить слово 🔙."
        )
        await update.message.reply_text(welcome_text, reply_markup=self.get_main_keyboard())
        logger.info(f"Пользователь {update.effective_user.id} запустил бота")

    async def next_word(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id

        if 'words' not in context.user_data:
            words = self.db.get_all_words_for_user(user_id)
            if not words:
                await update.message.reply_text(
                    "😕 Слов для изучения пока нет! Добавьте свои слова.",
                    reply_markup=self.get_main_keyboard()
                )
                return
            context.user_data['words'] = words
            context.user_data['index'] = 0
            random.shuffle(context.user_data['words'])

        words = context.user_data['words']
        index = context.user_data.get('index', 0)

        if index >= len(words):
            context.user_data['index'] = 0
            index = 0
            random.shuffle(context.user_data['words'])
            words = context.user_data['words']

        ru, en, wtype, wid = words[index]
        options = self.generate_options(en, words)

        context.user_data['current'] = {'ru': ru, 'en': en, 'id': wid, 'type': wtype}
        context.user_data['options'] = options

        await update.message.reply_text(
            f"*Выбери перевод слова:*\n- {ru}",
            parse_mode='Markdown',
            reply_markup=self.get_answer_keyboard(options)
        )

    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        answer = update.message.text

        if answer in ["Дальше 🚀", "Добавить слово ✨", "Удалить слово", "🔄 Попробовать снова"]:
            await self.handle_menu(update, context)
            return

        current = context.user_data.get('current', {})
        options = context.user_data.get('options', [])

        if answer not in options:
            await update.message.reply_text(
                "❌ Пожалуйста, используйте кнопки снизу",
                reply_markup=self.get_answer_keyboard(options) if options else self.get_main_keyboard()
            )
            return

        if not current:
            await update.message.reply_text(
                "❌ Ошибка. Нажмите Дальше 🚀",
                reply_markup=self.get_main_keyboard()
            )
            return

        correct = (answer == current['en'])
        self.db.update_statistics(user_id, current['id'], current['type'], correct)

        if correct:
            text = f"*Отлично!❤️*\n{current['en']} -> {current['ru']}"
            keyboard = [
                [KeyboardButton("Дальше 🚀")],
                [KeyboardButton("Добавить слово ✨"), KeyboardButton("Удалить слово")]
            ]
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            )
            context.user_data['index'] = context.user_data.get('index', 0) + 1
        else:
            text = f"*Неверно!* 😕\n\nПравильный ответ: *{current['en']}*"
            keyboard = [
                [KeyboardButton("🔄 Попробовать снова")],
                [KeyboardButton("Дальше 🚀")],
                [KeyboardButton("Добавить слово ✨"), KeyboardButton("Удалить слово")]
            ]
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            )

    async def retry(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        current = context.user_data.get('current', {})
        options = context.user_data.get('options', [])

        if not current or not options:
            await self.next_word(update, context)
            return

        await update.message.reply_text(
            f"*Выбери перевод слова:*\n- {current['ru']}",
            parse_mode='Markdown',
            reply_markup=self.get_answer_keyboard(options)
        )

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        text = update.message.text

        if text == "Дальше 🚀":
            await self.next_word(update, context)
        elif text == "Добавить слово ✨":
            await update.message.reply_text(
                "✏️ *Добавление нового слова*\n\n"
                "Отправь слово в формате: *русский - английский*\n"
                "Например: `книга - book`\n\n"
                "Или /cancel для отмены",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/cancel")]], resize_keyboard=True)
            )
            return ADDING_WORD
        elif text == "Удалить слово":
            words = self.db.get_user_personal_words(update.effective_user.id)
            if not words:
                await update.message.reply_text(
                    "📭 У вас пока нет личных слов для удаления.",
                    reply_markup=self.get_main_keyboard()
                )
                return ConversationHandler.END

            words_list = "\n".join([f"• {ru} — {en}" for ru, en in words[:10]])
            if len(words) > 10:
                words_list += f"\n• ... и еще {len(words) - 10} слов"

            await update.message.reply_text(
                f"🗑 *Удаление слова*\n\nВаши слова:\n{words_list}\n\n"
                f"Отправьте слово на русском, которое хотите удалить:",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/cancel")]], resize_keyboard=True)
            )
            return DELETING_WORD
        elif text == "🔄 Попробовать снова":
            await self.retry(update, context)
        return None

    async def add_word(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ Отменено", reply_markup=self.get_main_keyboard())
            return ConversationHandler.END

        if '-' not in text:
            await update.message.reply_text("❌ Неверный формат. Используйте: слово - перевод")
            return ADDING_WORD

        ru, en = text.split('-', 1)
        ru, en = ru.strip(), en.strip()
        success, msg = self.db.add_user_word(update.effective_user.id, ru, en)

        if 'words' in context.user_data:
            del context.user_data['words']

        await update.message.reply_text(msg, reply_markup=self.get_main_keyboard())
        return ConversationHandler.END

    async def delete_word(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text
        if text.lower() == '/cancel':
            await update.message.reply_text("❌ Отменено", reply_markup=self.get_main_keyboard())
            return ConversationHandler.END

        success, msg = self.db.delete_user_word(update.effective_user.id, text)

        if 'words' in context.user_data:
            del context.user_data['words']

        await update.message.reply_text(msg, reply_markup=self.get_main_keyboard())
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await update.message.reply_text("❌ Отменено", reply_markup=self.get_main_keyboard())
        return ConversationHandler.END

    def run(self) -> None:
        app = Application.builder().token(self.token).build()

        add_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex('^Добавить слово ✨$'), self.handle_menu)],
            states={ADDING_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_word)]},
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )

        del_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex('^Удалить слово$'), self.handle_menu)],
            states={DELETING_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.delete_word)]},
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )

        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("cancel", self.cancel))
        app.add_handler(add_handler)
        app.add_handler(del_handler)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_answer))

        logger.info("🤖 Бот запущен с PostgreSQL!")
        app.run_polling()


if __name__ == '__main__':
    bot = EnglishCardBot(BOT_TOKEN)
    bot.run()