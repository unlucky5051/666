import os
import logging
from dotenv import load_dotenv
from telegram import (
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup, Update
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from supabase import create_client, Client

# ---------- Логи ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------- Загрузка конфигурации ----------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MODERATOR_CHAT_ID = int(os.getenv("MODERATOR_CHAT_ID", "0"))

if not BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY or MODERATOR_CHAT_ID == 0:
    logger.error("Проверьте .env: BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, MODERATOR_CHAT_ID должны быть заданы.")
    raise SystemExit("Недостаточно переменных окружения.")

# ---------- Подключение к Supabase ----------
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- В памяти ----------
user_states = {}
pending_mod_replies = {}

# ---------- Вопросы ----------
QUESTIONS = {
    1: [
        {"text": "Какая природная особенность Ямало-Ненецкого автономного округа вам наиболее интересна?",
         "options": ["Тундра и её ландшафты", "Северное сияние", "Болота и реки"],
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/0000.jpg"},

        {"text": "Какая экологическая проблема региона вызывает у вас наибольшее беспокойство?",
         "options": ["Загрязнение от промышленности", "Изменение климата", "Загрязнение рек и озёр"],
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/mishki.jpg"},

        {"text": "Какие меры, по вашему мнению, нужно принять для сохранения природы ЯНАО?",
         "options": None,
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/priroda3.jpg"}
    ],
    2: [
        {"text": "Что, на ваш взгляд, важнее для будущего региона?",
         "options": ["Промышленное развитие", "Сохранение традиций", "Компромисс между ними"],
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/region4.jpg"},

        {"text": "Как вы относитесь к строительству новых дорог и мостов в ЯНАО?",
         "options": ["Поддерживаю — нужно развивать", "Нужно осторожно — с учётом природы", "Не важно / без разницы"],
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/dorogi5.jpg"},

        {"text": "Какие проекты или инициативы вы хотели бы видеть для развития ЯНАО?",
         "options": None,
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/vopros6.jpg"}
    ],
    3: [
        {"text": "Какие традиционные занятия жителей ЯНАО вы считаете наиболее важными для сохранения?",
         "options": ["Оленеводство", "Рыболовство", "Народные ремёсла"],
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/narod7.jpg"},

        {"text": "Как вы оцениваете уровень сохранения культуры и языка коренных народов?",
         "options": ["Хорошо сохраняется", "Требует срочной поддержки", "Практически утерян"],
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/culture8.jpg"},

        {"text": "Что, по вашему мнению, можно сделать для популяризации культуры ЯНАО среди молодёжи?",
         "options": None,
         "image_url": "https://kmbidgmqvjqnhmvvbjcv.supabase.co/storage/v1/object/public/survey-images/molodej9.jpg"}
    ]
}

# ---------- Функции БД ----------
def add_user(user_id: int, username: str = None, full_name: str = None):
    try:
        r = supabase.table("users").select("user_id").eq("user_id", user_id).execute()
        if not r.data:
            supabase.table("users").insert({
                "user_id": user_id, "username": username, "full_name": full_name
            }).execute()
        for n in (1, 2, 3):
            if not supabase.table("survey_progress").select("status").eq("user_id", user_id).eq("survey_number", n).execute().data:
                supabase.table("survey_progress").insert({
                    "user_id": user_id, "survey_number": n, "status": "not_started"
                }).execute()
    except Exception as e:
        logger.exception("add_user error: %s", e)

def get_survey_progress(user_id: int, survey_number: int) -> str:
    try:
        res = supabase.table("survey_progress").select("status").eq("user_id", user_id).eq("survey_number", survey_number).execute()
        if res.data:
            return res.data[0]["status"]
    except Exception as e:
        logger.exception("get_survey_progress error: %s", e)
    return "not_started"

def set_survey_progress(user_id: int, survey_number: int, status: str):
    try:
        supabase.table("survey_progress").upsert({
            "user_id": user_id, "survey_number": survey_number, "status": status
        }).execute()
    except Exception as e:
        logger.exception("set_survey_progress error: %s", e)

def insert_survey_result(user_id: int, survey_number: int, question_number: int, answer: str):
    try:
        supabase.table("survey_results").insert({
            "user_id": user_id, "survey_number": survey_number,
            "question_number": question_number, "answer": answer
        }).execute()
    except Exception as e:
        logger.exception("insert_survey_result error: %s", e)

def insert_feedback(user_id: int, message_text: str, status: str = "new"):
    try:
        r = supabase.table("feedback").insert({
            "user_id": user_id, "message": message_text, "status": status
        }).execute()
        if r.data and "id" in r.data[0]:
            return r.data[0]["id"]
    except Exception as e:
        logger.exception("insert_feedback error: %s", e)
    return None

def get_new_feedback():
    try:
        r = supabase.table("feedback").select("*").eq("status", "new").execute()
        return r.data or []
    except Exception as e:
        logger.exception("get_new_feedback error: %s", e)
        return []

def update_feedback_status(feedback_id: int, status: str):
    try:
        supabase.table("feedback").update({"status": status}).eq("id", feedback_id).execute()
    except Exception as e:
        logger.exception("update_feedback_status error: %s", e)

def insert_moderator_reply(feedback_id: int, moderator_id: int, reply_message: str):
    try:
        supabase.table("moderator_replies").insert({
            "feedback_id": feedback_id, "moderator_id": moderator_id, "reply_message": reply_message
        }).execute()
    except Exception as e:
        logger.exception("insert_moderator_reply error: %s", e)

def get_feedback_user(feedback_id: int):
    try:
        r = supabase.table("feedback").select("user_id").eq("id", feedback_id).execute()
        if r.data:
            return r.data[0]["user_id"]
    except Exception as e:
        logger.exception("get_feedback_user error: %s", e)
    return None

def get_user_results(user_id: int):
    try:
        r = supabase.table("survey_results").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return r.data or []
    except Exception as e:
        logger.exception("get_user_results error: %s", e)
        return []

# ---------- Клавиатуры ----------
def get_quick_keyboard():
    return ReplyKeyboardMarkup([
        ["📜 Меню", "🏆 Мои ответы"],
        ["🗣️ Обратная связь"]
    ], resize_keyboard=True)

# ---------- Обработчики ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username or "", user.full_name or "")
    await update.message.reply_text(
        "Привет! 👋\nЯ бот-опросник по теме ЯНАО.\nИспользуйте кнопки ниже.",
        reply_markup=get_quick_keyboard()
    )

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Опрос №1", callback_data="survey_1")],
        [InlineKeyboardButton("Опрос №2", callback_data="survey_2")],
        [InlineKeyboardButton("Опрос №3", callback_data="survey_3")],
        [InlineKeyboardButton("Обратная связь", callback_data="feedback_start")],
        [InlineKeyboardButton("Мои ответы", callback_data="my_results")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Главное меню:", reply_markup=markup)
    else:
        await update.message.reply_text("Главное меню:", reply_markup=markup)

async def _reply_denied(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "Вы не можете пройти этот опрос, так как не прошли предыдущие."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg)
    else:
        await update.message.reply_text(msg)

async def _send_question_to_user(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if user_id not in user_states:
        return
    state = user_states[user_id]
    survey = state["survey"]
    q_idx = state["question"]
    q_obj = QUESTIONS[survey][q_idx - 1]
    text = q_obj["text"]
    image_url = q_obj.get("image_url")
    options = q_obj.get("options")

    try:
        if image_url:
            if options is None:
                # Без кнопок, просто фото + текст
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=image_url,
                    caption=f"{text}\n\n(Пожалуйста, ответьте сообщением.)"
                )
            else:
                # Фото + текст + кнопки
                keyboard = [
                    [InlineKeyboardButton(opt, callback_data=f"answer_{survey}_{q_idx}_{i}")]
                    for i, opt in enumerate(options)
                ]
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=image_url,
                    caption=text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            # Если картинки нет
            if options is None:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"{text}\n\n(Пожалуйста, ответьте сообщением.)"
                )
            else:
                keyboard = [
                    [InlineKeyboardButton(opt, callback_data=f"answer_{survey}_{q_idx}_{i}")]
                    for i, opt in enumerate(options)
                ]
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
    except Exception as e:
        logger.exception("Ошибка при отправке вопроса: %s", e)

async def start_survey(user_id: int, survey_num: int, context: ContextTypes.DEFAULT_TYPE, reset: bool = False):
    """
    Запускает опрос. Если reset=True — удаляет старые ответы и начинает заново.
    """
    # Проверка последовательности
    if survey_num == 2 and get_survey_progress(user_id, 1) != "completed":
        return await context.bot.send_message(chat_id=user_id, text="Вы не можете пройти этот опрос, так как не прошли предыдущие.")
    if survey_num == 3 and (get_survey_progress(user_id, 1) != "completed" or get_survey_progress(user_id, 2) != "completed"):
        return await context.bot.send_message(chat_id=user_id, text="Вы не можете пройти этот опрос, так как не прошли предыдущие.")

    # Удаление старых ответов
    if reset:
        try:
            supabase.table("survey_results").delete().eq("user_id", user_id).eq("survey_number", survey_num).execute()
            logger.info(f"Старые ответы пользователя {user_id} по опросу {survey_num} удалены.")
        except Exception as e:
            logger.exception("Ошибка при удалении старых ответов: %s", e)

    # Если уже проходил и не reset
    if not reset and get_survey_progress(user_id, survey_num) == "completed":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Пройти заново", callback_data=f"repeat_{survey_num}")],
            [InlineKeyboardButton("Вернуться в меню", callback_data="show_menu")]
        ])
        return await context.bot.send_message(chat_id=user_id, text="Вы уже проходили этот опрос.", reply_markup=markup)

    # Запуск нового прохождения
    set_survey_progress(user_id, survey_num, "in_progress")
    user_states[user_id] = {"survey": survey_num, "question": 1}
    await _send_question_to_user(user_id, context)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    user_id = query.from_user.id

    if data == "show_menu":
        return await menu_handler(update, context)

    if data == "my_results":
        return await my_result_cmd_callback(update, context)

    if data.startswith("survey_"):
        return await start_survey(user_id, int(data.split("_")[1]), context, reset=False)

    if data.startswith("repeat_"):
        return await start_survey(user_id, int(data.split("_")[1]), context, reset=True)

    if data == "feedback_start":
        context.user_data["awaiting_feedback"] = True
        return await query.message.reply_text("Напишите ваше сообщение для тех. поддержки:")

    if data.startswith("answer_"):
        survey, q_idx, opt_i = map(int, data.split("_")[1:])
        opt_text = QUESTIONS[survey][q_idx - 1]["options"][opt_i]
        insert_survey_result(user_id, survey, q_idx, opt_text)
        user_states[user_id]["question"] += 1

        if user_states[user_id]["question"] > 3:
            set_survey_progress(user_id, survey, "completed")
            del user_states[user_id]

            buttons = [[InlineKeyboardButton("Вернуться в меню", callback_data="show_menu")]]
            if survey < 3:
                buttons.insert(0, [InlineKeyboardButton("Следующий опрос", callback_data=f"survey_{survey+1}")])
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Спасибо за прохождение опроса №{survey}! 📋",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="Спасибо за прохождение всех опросов! 🎉 Мы ценим ваше мнение ❤️",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
        else:
            await _send_question_to_user(user_id, context)
        return

    if data.startswith("reply_fb_"):
        fb_id = int(data.split("_")[-1])
        pending_mod_replies[user_id] = fb_id
        return await context.bot.send_message(chat_id=user_id, text=f"Введите ответ для обращения #{fb_id}:")

# ---------- Обработка текстов ----------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Ответ модератора
    if user_id in pending_mod_replies and user_id == MODERATOR_CHAT_ID:
        fb_id = pending_mod_replies.pop(user_id)
        insert_moderator_reply(fb_id, user_id, text)
        update_feedback_status(fb_id, "answered")
        target = get_feedback_user(fb_id)
        if target:
            await context.bot.send_message(chat_id=target, text=f"Ответ модератора:\n\n{text}")
        try:
            await update.message.edit_reply_markup(reply_markup=None)
        except:
            pass
        return await update.message.reply_text("Ответ отправлен.")

    # Ответ в опросе (свободный текст)
    if user_id in user_states:
        survey = user_states[user_id]["survey"]
        q_idx = user_states[user_id]["question"]
        if QUESTIONS[survey][q_idx - 1]["options"] is None:
            insert_survey_result(user_id, survey, q_idx, text)
            set_survey_progress(user_id, survey, "completed")
            del user_states[user_id]

            buttons = [[InlineKeyboardButton("Вернуться в меню", callback_data="show_menu")]]
            if survey < 3:
                buttons.insert(0, [InlineKeyboardButton("Следующий опрос", callback_data=f"survey_{survey+1}")])
                await update.message.reply_text(
                    f"Спасибо за прохождение опроса №{survey}! 📋",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                await update.message.reply_text(
                    "Спасибо за прохождение всех опросов! 🎉 Мы ценим ваше мнение ❤️",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            return

    # Обратная связь
    if context.user_data.get("awaiting_feedback"):
        fb_id = insert_feedback(user_id, text)
        context.user_data["awaiting_feedback"] = False
        await update.message.reply_text("Спасибо за сообщение.", reply_markup=get_quick_keyboard())
        if fb_id:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Ответить", callback_data=f"reply_fb_{fb_id}")]])
            await context.bot.send_message(chat_id=MODERATOR_CHAT_ID, text=f"Новое обращение #{fb_id} от {user_id}:\n\n{text}", reply_markup=kb)
        return

    # Быстрые кнопки
    if text in ("📜 Меню", "Показать меню"):
        return await menu_handler(update, context)
    if text in ("🏆 Мои ответы", "Мои ответы"):
        return await my_result_cmd(update, context)
    if text == "🗣️ Обратная связь":
        context.user_data["awaiting_feedback"] = True
        return await update.message.reply_text("Напишите ваше сообщение:", reply_markup=ReplyKeyboardRemove())

# ---------- Результаты ----------
async def _send_my_results(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    rows = get_user_results(user_id)
    if not rows:
        return await context.bot.send_message(chat_id=user_id, text="Нет сохранённых ответов.", reply_markup=get_quick_keyboard())
    grouped = {}
    for r in rows:
        s = r["survey_number"]
        qn = r["question_number"]
        ans = r["answer"]
        grouped.setdefault(s, {})[qn] = ans
    text_lines = []
    for s in sorted(grouped):
        text_lines.append(f"Опрос №{s}:")
        for qn in sorted(grouped[s]):
            text_lines.append(f"  Вопрос {qn}: {grouped[s][qn]}")
    await context.bot.send_message(chat_id=user_id, text="\n".join(text_lines), reply_markup=get_quick_keyboard())

async def my_result_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_my_results(update.effective_user.id, context)

async def my_result_cmd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await _send_my_results(update.callback_query.from_user.id, context)

# ---------- Модератор ----------
async def check_feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MODERATOR_CHAT_ID:
        return await update.message.reply_text("Нет прав.")
    items = get_new_feedback()
    if not items:
        return await update.message.reply_text("Новых сообщений нет.")
    for it in items:
        fb_id = it["id"]
        uid = it["user_id"]
        msg = it.get("message", "")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Ответить", callback_data=f"reply_fb_{fb_id}")]])
        await context.bot.send_message(chat_id=MODERATOR_CHAT_ID, text=f"#{fb_id} от {uid}:\n\n{msg}", reply_markup=kb)
    await update.message.reply_text(f"Отправлено {len(items)} обращений.")

# ---------- Main ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", menu_handler))
    app.add_handler(CommandHandler("my_result", my_result_cmd))
    app.add_handler(CommandHandler("check_feedback", check_feedback_cmd))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    logger.info("Запуск бота...")
    app.run_polling()

if __name__ == "__main__":
    main()