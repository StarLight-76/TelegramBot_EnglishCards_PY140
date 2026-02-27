"""
EnglishCard Bot - Telegram бот для изучения английских слов
Версия: PostgreSQL (с автоматическим созданием БД)
Студент: Дмитрий Кирильчук
Группа: PY-140
Курсовая работа «ТГ-чат-бот «Обучалка английскому языку»»
"""

import logging
import random
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from typing import List, Tuple, Optional

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ ПАРАМЕТРЫ ПОДКЛЮЧЕНИЯ ===============
BOT_TOKEN = "8443609494:AAEvhmmm3gRnRStZ_UM-K4vu6RoaRujxbZc"

DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "english_card"
DB_USER = "postgres"
DB_PASSWORD = "postgres2026"
# ==================================================

# Состояния для разговора
ADDING_WORD, DELETING_WORD = range(2)


class Database:
    """Класс для работы с PostgreSQL базой данных (с автоматическим созданием БД)"""

    def __init__(self):
        """Инициализация: создаем БД если нет, затем создаем таблицы"""
        self.ensure_database_exists()
        self.init_db()

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
            logger.error("2. Правильность пароля в DB_PASSWORD")
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

            # Создаем индексы для ускорения запросов
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_words_user_id ON user_words(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_statistics_user_id ON user_statistics(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_statistics_word ON user_statistics(word_id, word_type)")

            # Заполняем общими словами (10 слов как требуется в задании)
            common_words = [
                ('красный', 'red'),
                ('синий', 'blue'),
                ('зеленый', 'green'),
                ('желтый', 'yellow'),
                ('я', 'I'),
                ('ты', 'you'),
                ('он', 'he'),
                ('она', 'she'),
                ('мы', 'we'),
                ('они', 'they')
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

    def get_all_words_for_user(self, user_id: int) -> List[Tuple]:
        """Получает все слова для пользователя (общие + персональные)"""
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor(cursor_factory=RealDictCursor)

            # Получаем общие слова
            c.execute("SELECT id, ru_word, en_word FROM common_words")
            common_rows = c.fetchall()
            common = [(row['ru_word'], row['en_word'], 'common', row['id']) for row in common_rows]

            # Получаем персональные слова пользователя
            c.execute("SELECT id, ru_word, en_word FROM user_words WHERE user_id = %s", (user_id,))
            personal_rows = c.fetchall()
            personal = [(row['ru_word'], row['en_word'], 'personal', row['id']) for row in personal_rows]

            # Объединяем и перемешиваем для разнообразия
            all_words = common + personal
            random.shuffle(all_words)
            return all_words

        except Exception as e:
            logger.error(f"Ошибка при получении слов: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def add_user_word(self, user_id: int, ru: str, en: str) -> tuple[bool, str]:
        """Добавляет персональное слово пользователя"""
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor()
            c.execute(
                "INSERT INTO user_words (user_id, ru_word, en_word) VALUES (%s, %s, %s)",
                (user_id, ru.lower(), en.lower())
            )
            conn.commit()
            logger.info(f"Пользователь {user_id} добавил слово: {ru} - {en}")
            return True, "✅ Слово успешно добавлено!"
        except psycopg2.IntegrityError:
            if conn:
                conn.rollback()
            return False, "❌ Это слово уже есть в вашем списке!"
        except Exception as e:
            logger.error(f"Ошибка при добавлении слова: {e}")
            return False, "❌ Произошла ошибка при добавлении слова"
        finally:
            if conn:
                conn.close()

    def delete_user_word(self, user_id: int, ru: str) -> tuple[bool, str]:
        """Удаляет персональное слово пользователя (только своё)"""
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

            if deleted:
                logger.info(f"Пользователь {user_id} удалил слово: {ru}")
                return True, f"✅ Слово '{ru}' удалено"
            else:
                return False, f"❌ Слово '{ru}' не найдено в вашем списке"
        except Exception as e:
            logger.error(f"Ошибка при удалении слова: {e}")
            return False, "❌ Произошла ошибка при удалении слова"
        finally:
            if conn:
                conn.close()

    def get_user_personal_words(self, user_id: int) -> List[Tuple]:
        """Получает только персональные слова пользователя для отображения при удалении"""
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT ru_word, en_word FROM user_words WHERE user_id = %s", (user_id,))
            rows = c.fetchall()
            return [(row['ru_word'], row['en_word']) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка при получении личных слов: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def update_statistics(self, user_id: int, word_id: int, word_type: str, correct: bool):
        """Обновляет статистику изучения слов"""
        conn = None
        try:
            conn = self.get_connection()
            c = conn.cursor()

            # Проверяем, есть ли уже запись статистики
            c.execute(
                "SELECT id, correct_answers, total_attempts FROM user_statistics "
                "WHERE user_id = %s AND word_id = %s AND word_type = %s",
                (user_id, word_id, word_type)
            )
            result = c.fetchone()

            if result:
                # Обновляем существующую запись
                new_correct = result[1] + (1 if correct else 0)
                new_total = result[2] + 1
                c.execute(
                    "UPDATE user_statistics SET correct_answers = %s, total_attempts = %s, last_reviewed = CURRENT_TIMESTAMP "
                    "WHERE id = %s",
                    (new_correct, new_total, result[0])
                )
            else:
                # Создаем новую запись
                c.execute(
                    "INSERT INTO user_statistics (user_id, word_id, word_type, correct_answers, total_attempts) "
                    "VALUES (%s, %s, %s, %s, 1)",
                    (user_id, word_id, word_type, 1 if correct else 0)
                )

            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка при обновлении статистики: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()


class EnglishCardBot:
    """Основной класс бота"""

    def __init__(self, token: str):
        self.token = token
        self.db = Database()
        # Запасные слова на случай, если у пользователя мало слов
        self.backup_words = ['dream', 'love', 'life', 'time', 'day', 'night', 'book', 'house', 'car', 'dog']

    @staticmethod
    def get_main_keyboard() -> ReplyKeyboardMarkup:
        """Главное меню (всегда внизу)"""
        keyboard = [
            [KeyboardButton("Дальше 🚀")],
            [KeyboardButton("Добавить слово ✨"), KeyboardButton("Удалить слово")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    @staticmethod
    def get_answer_keyboard(options: List[str]) -> ReplyKeyboardMarkup:
        """
        Клавиатура с вариантами ответов
        4 варианта ответа + кнопки меню внизу (как в дизайне)
        """
        keyboard = [
            [KeyboardButton(options[0]), KeyboardButton(options[1])],
            [KeyboardButton(options[2]), KeyboardButton(options[3])],
            [KeyboardButton("Дальше 🚀")],
            [KeyboardButton("Добавить слово ✨"), KeyboardButton("Удалить слово")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    def generate_options(self, correct: str, all_words: List[Tuple]) -> List[str]:
        """Генерирует 4 варианта ответа (1 правильный + 3 неправильных)"""
        options = [correct]
        # Все английские слова из списка, кроме правильного
        all_en = list(set([w[1] for w in all_words if w[1] != correct]))

        # Добавляем слова из базы пользователя
        while len(options) < 4 and all_en:
            word = random.choice(all_en)
            if word not in options:
                options.append(word)
                all_en.remove(word)

        # Если не хватает, добавляем из запасного списка
        while len(options) < 4:
            word = random.choice(self.backup_words)
            if word not in options:
                options.append(word)

        random.shuffle(options)
        return options

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Приветственное сообщение (точно как в задании)"""
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
        """Показывает следующее слово с кнопками внизу"""
        user_id = update.effective_user.id

        # Загружаем слова если нужно
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

        # Если дошли до конца - начинаем сначала
        if index >= len(words):
            context.user_data['index'] = 0
            index = 0
            random.shuffle(context.user_data['words'])
            words = context.user_data['words']

        ru, en, wtype, wid = words[index]
        options = self.generate_options(en, words)

        # Сохраняем текущее слово
        context.user_data['current'] = {'ru': ru, 'en': en, 'id': wid, 'type': wtype}
        context.user_data['options'] = options

        # Отправляем сообщение с клавиатурой внизу (как в дизайне)
        text = f"*Выбери перевод слова:*\n- {ru}"
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=self.get_answer_keyboard(options)
        )

    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обрабатывает ответ пользователя"""
        user_id = update.effective_user.id
        answer = update.message.text

        # Проверяем не нажал ли пользователь кнопку меню
        if answer in ["Дальше 🚀", "Добавить слово ✨", "Удалить слово", "🔄 Попробовать снова"]:
            await self.handle_menu(update, context)
            return

        current = context.user_data.get('current', {})
        options = context.user_data.get('options', [])

        # Проверяем, есть ли такой вариант в списке
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

        # Обновляем статистику
        correct = (answer == current['en'])
        self.db.update_statistics(user_id, current['id'], current['type'], correct)

        if correct:
            # ПРАВИЛЬНЫЙ ОТВЕТ - как в дизайне
            text = f"*Отлично!❤️*\n{current['en']} -> {current['ru']}"

            # Показываем сообщение и кнопку Дальше
            keyboard = [
                [KeyboardButton("Дальше 🚀")],
                [KeyboardButton("Добавить слово ✨"), KeyboardButton("Удалить слово")]
            ]
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            )

            # Увеличиваем индекс для следующего слова
            context.user_data['index'] = context.user_data.get('index', 0) + 1

        else:
            # НЕПРАВИЛЬНЫЙ ОТВЕТ - показываем правильный и даем попробовать снова
            text = f"*Неверно!* 😕\n\nПравильный ответ: *{current['en']}*"

            # Кнопка для повторной попытки
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
        """Повторная попытка ответить на тот же вопрос"""
        current = context.user_data.get('current', {})
        options = context.user_data.get('options', [])

        if not current or not options:
            await self.next_word(update, context)
            return

        text = f"*Выбери перевод слова:*\n- {current['ru']}"
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=self.get_answer_keyboard(options)
        )

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
        """Обрабатывает нажатия на кнопки меню"""
        text = update.message.text

        if text == "Дальше 🚀":
            await self.next_word(update, context)
            return None
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
                    "📭 У вас пока нет личных слов для удаления.\n"
                    "Общие слова удалять нельзя.",
                    reply_markup=self.get_main_keyboard()
                )
                return ConversationHandler.END

            # Показываем первые 10 слов (если их много)
            words_list = "\n".join([f"• {ru} — {en}" for ru, en in words[:10]])
            if len(words) > 10:
                words_list += f"\n• ... и еще {len(words) - 10} слов"

            await update.message.reply_text(
                f"🗑 *Удаление слова*\n\n"
                f"Ваши слова:\n{words_list}\n\n"
                f"Отправьте слово на русском, которое хотите удалить:\n"
                f"Или /cancel для отмены",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/cancel")]], resize_keyboard=True)
            )
            return DELETING_WORD
        elif text == "🔄 Попробовать снова":
            await self.retry(update, context)
            return None

        return None

    async def add_word(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Добавление нового слова"""
        text = update.message.text

        if text.lower() == '/cancel':
            await update.message.reply_text(
                "❌ Отменено",
                reply_markup=self.get_main_keyboard()
            )
            return ConversationHandler.END

        if '-' not in text:
            await update.message.reply_text(
                "❌ Неверный формат. Используйте: слово - перевод\n"
                "Например: книга - book",
                reply_markup=self.get_main_keyboard()
            )
            return ADDING_WORD

        try:
            ru, en = text.split('-', 1)
            ru = ru.strip()
            en = en.strip()

            if not ru or not en:
                await update.message.reply_text(
                    "❌ Оба поля должны быть заполнены",
                    reply_markup=self.get_main_keyboard()
                )
                return ADDING_WORD

            user_id = update.effective_user.id
            success, msg = self.db.add_user_word(user_id, ru, en)

            # Очищаем кэш слов, чтобы новое слово появилось
            if 'words' in context.user_data:
                del context.user_data['words']

            await update.message.reply_text(msg, reply_markup=self.get_main_keyboard())

        except Exception as e:
            logger.error(f"Ошибка при добавлении слова: {e}")
            await update.message.reply_text(
                "❌ Ошибка. Используйте формат: слово - перевод",
                reply_markup=self.get_main_keyboard()
            )

        return ConversationHandler.END

    async def delete_word(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Удаление слова"""
        text = update.message.text

        if text.lower() == '/cancel':
            await update.message.reply_text(
                "❌ Отменено",
                reply_markup=self.get_main_keyboard()
            )
            return ConversationHandler.END

        user_id = update.effective_user.id
        success, msg = self.db.delete_user_word(user_id, text)

        # Очищаем кэш слов
        if 'words' in context.user_data:
            del context.user_data['words']

        await update.message.reply_text(msg, reply_markup=self.get_main_keyboard())
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отмена текущего действия"""
        await update.message.reply_text(
            "❌ Отменено",
            reply_markup=self.get_main_keyboard()
        )
        return ConversationHandler.END

    def run(self) -> None:
        """Запуск бота"""
        app = Application.builder().token(self.token).build()

        # Обработчик диалога для добавления слова
        add_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex('^Добавить слово ✨$'), self.handle_menu)],
            states={ADDING_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_word)]},
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )

        # Обработчик диалога для удаления слова
        del_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex('^Удалить слово$'), self.handle_menu)],
            states={DELETING_WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.delete_word)]},
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )

        # Регистрация всех обработчиков
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("cancel", self.cancel))
        app.add_handler(add_handler)
        app.add_handler(del_handler)

        # Обработчик всех текстовых сообщений (ответы на вопросы и кнопки меню)
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_answer
        ))

        logger.info("🤖 Бот запущен!")
        logger.info("✅ 10 общих слов загружено")
        logger.info("✅ 3 таблицы в базе данных PostgreSQL")
        logger.info("✅ Автоматическое создание БД работает")
        logger.info("✅ Поддержка добавления/удаления своих слов")
        app.run_polling()


if __name__ == '__main__':
    bot = EnglishCardBot(BOT_TOKEN)
    bot.run()