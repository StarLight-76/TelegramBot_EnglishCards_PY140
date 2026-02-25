"""
EnglishCard Bot - Telegram бот для изучения английских слов
Версия: SQLite с кнопками внизу как в дизайне
Студент: Дмитрий Кирильчук
Группа: PY-140
Курсовая работа «ТГ-чат-бот «Обучалка английскому языку»»
"""

import logging
import random
import sqlite3
from typing import List, Tuple

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

# ============ ТОКЕН ============
BOT_TOKEN = "8443609494:AAEvhmmm3gRnRStZ_UM-K4vu6RoaRujxbZc"
# ==================================

# Состояния для разговора
ADDING_WORD, DELETING_WORD = range(2)


class Database:
    """Класс для работы с SQLite базой данных"""

    def __init__(self, db_name: str = 'database/english_card.db'):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        c = conn.cursor()

        # Таблица 1: Общие слова для всех пользователей
        c.execute('''CREATE TABLE IF NOT EXISTS common_words
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ru_word TEXT UNIQUE NOT NULL,
                      en_word TEXT NOT NULL)''')

        # Таблица 2: Персональные слова пользователей
        c.execute('''CREATE TABLE IF NOT EXISTS user_words
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      ru_word TEXT NOT NULL,
                      en_word TEXT NOT NULL,
                      UNIQUE(user_id, ru_word))''')

        # Таблица 3: Статистика изучения слов
        c.execute('''CREATE TABLE IF NOT EXISTS user_statistics
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      word_id INTEGER NOT NULL,
                      word_type TEXT,
                      correct_answers INTEGER DEFAULT 0,
                      total_attempts INTEGER DEFAULT 0)''')

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
            c.execute("INSERT OR IGNORE INTO common_words (ru_word, en_word) VALUES (?, ?)", (ru, en))

        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована с 10 общими словами")

    def get_all_words_for_user(self, user_id: int) -> List[Tuple]:
        """Получает все слова для пользователя (общие + персональные)"""
        conn = self.get_connection()
        c = conn.cursor()

        # Получаем общие слова
        c.execute("SELECT ru_word, en_word, 'common', id FROM common_words")
        common = [(row['ru_word'], row['en_word'], 'common', row['id']) for row in c.fetchall()]

        # Получаем персональные слова пользователя
        c.execute("SELECT ru_word, en_word, 'personal', id FROM user_words WHERE user_id=?", (user_id,))
        personal = [(row['ru_word'], row['en_word'], 'personal', row['id']) for row in c.fetchall()]

        conn.close()
        # Объединяем и перемешиваем для разнообразия
        all_words = common + personal
        random.shuffle(all_words)
        return all_words

    def add_user_word(self, user_id: int, ru: str, en: str) -> tuple[bool, str]:
        """Добавляет персональное слово пользователя"""
        conn = self.get_connection()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO user_words (user_id, ru_word, en_word) VALUES (?, ?, ?)",
                     (user_id, ru.lower(), en.lower()))
            conn.commit()
            logger.info(f"Пользователь {user_id} добавил слово: {ru} - {en}")
            return True, "✅ Слово успешно добавлено!"
        except sqlite3.IntegrityError:
            return False, "❌ Это слово уже есть в вашем списке!"
        finally:
            conn.close()

    def delete_user_word(self, user_id: int, ru: str) -> tuple[bool, str]:
        """Удаляет персональное слово пользователя (только своё)"""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM user_words WHERE user_id=? AND ru_word=?", (user_id, ru.lower()))
        conn.commit()
        deleted = c.rowcount > 0
        conn.close()

        if deleted:
            logger.info(f"Пользователь {user_id} удалил слово: {ru}")
            return True, f"✅ Слово '{ru}' удалено"
        else:
            return False, f"❌ Слово '{ru}' не найдено в вашем списке"

    def get_user_personal_words(self, user_id: int) -> List[Tuple]:
        """Получает только персональные слова пользователя для отображения при удалении"""
        conn = self.get_connection()
        c = conn.cursor()
        c.execute("SELECT ru_word, en_word FROM user_words WHERE user_id=?", (user_id,))
        words = [(row['ru_word'], row['en_word']) for row in c.fetchall()]
        conn.close()
        return words

    def update_statistics(self, user_id: int, word_id: int, word_type: str, correct: bool):
        """Обновляет статистику изучения слов"""
        conn = self.get_connection()
        c = conn.cursor()

        c.execute("""SELECT id, correct_answers, total_attempts FROM user_statistics 
                   WHERE user_id=? AND word_id=? AND word_type=?""",
                 (user_id, word_id, word_type))
        result = c.fetchone()

        if result:
            # Обновляем существующую запись
            new_correct = result['correct_answers'] + (1 if correct else 0)
            new_total = result['total_attempts'] + 1
            c.execute("UPDATE user_statistics SET correct_answers=?, total_attempts=? WHERE id=?",
                     (new_correct, new_total, result['id']))
        else:
            # Создаем новую запись
            c.execute("""INSERT INTO user_statistics 
                       (user_id, word_id, word_type, correct_answers, total_attempts)
                       VALUES (?, ?, ?, ?, 1)""",
                     (user_id, word_id, word_type, 1 if correct else 0))

        conn.commit()
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

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обрабатывает нажатия на кнопки меню"""
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

        logger.info("🤖 Бот запущен с кнопками внизу как в дизайне!")
        logger.info("✅ 10 общих слов загружено")
        logger.info("✅ 3 таблицы в базе данных")
        logger.info("✅ Поддержка добавления/удаления своих слов")
        app.run_polling()


if __name__ == '__main__':
    bot = EnglishCardBot(BOT_TOKEN)
    bot.run()