import asyncio
import logging
from datetime import date
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from .config import get_config
from .database import Database, Entry
from .transcribe import Transcriber
from .parser import ExerciseParser, reparse_exercise_name
from .analytics import (
    generate_insights,
    format_entry,
    format_training_summary,
    ExerciseInsight,
)
from .keyboards import (
    entry_edit_keyboard,
    confirm_delete_keyboard,
    cancel_keyboard,
    exercise_list_keyboard,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# FSM States
class EditStates(StatesGroup):
    waiting_for_exercise = State()
    waiting_for_weight = State()
    waiting_for_reps = State()
    waiting_for_comment = State()


# Global instances (initialized in main)
config = None
bot: Bot = None
dp = Dispatcher(storage=MemoryStorage())
db: Database = None
transcriber: Transcriber = None
parser: ExerciseParser = None


def _format_weight(weight: Optional[float]) -> str:
    """Format weight nicely."""
    if weight is None:
        return "—"
    if weight == int(weight):
        return f"{int(weight)} кг"
    return f"{weight:.1f} кг"


async def _build_entry_message(
    user_id: int,
    entry: Entry,
    training_num: int,
    set_num: int,
) -> str:
    """Build the message for a logged entry with insights."""
    lines = [f"✅ Записано в тренировку #{training_num} (подход {set_num})", ""]

    # Entry details
    lines.append(format_entry(entry))

    # Generate insights
    insights = await generate_insights(db, user_id, entry)
    if insights:
        lines.append("")
        lines.append("📊 Аналитика:")
        for insight in insights[:4]:  # Limit to 4 insights
            lines.append(f"{insight.emoji} {insight.text}")

    return "\n".join(lines)


# === Command Handlers ===

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Handle /start command."""
    await db.get_or_create_user(message.from_user.id)

    text = """👋 Привет! Я бот для логирования тренировок.

🎤 Отправь мне голосовое сообщение с описанием упражнения, и я запишу его в дневник.

Примеры:
• «присед 60 кг на 6 раз»
• «жим лёжа 80 на 5, тяжело»
• «подтягивания широким хватом 8 раз»

📝 Команды:
/today — текущая тренировка
/history — история тренировок
/stats — статистика
/exercise <название> — история упражнения

💡 После записи можно исправить любое поле кнопками."""

    await message.answer(text)


@dp.message(Command("today"))
async def cmd_today(message: Message):
    """Show today's training."""
    user_id = await db.get_or_create_user(message.from_user.id)
    entries = await db.get_today_entries(user_id)

    if not entries:
        await message.answer("📭 Сегодня ещё нет записей.\n\nОтправь голосовое сообщение, чтобы начать тренировку!")
        return

    text = format_training_summary(entries, date.today())
    training_num = await db.get_training_number(user_id)
    text = f"🏋️ Тренировка #{training_num}\n\n{text}"

    await message.answer(text)


@dp.message(Command("history"))
async def cmd_history(message: Message):
    """Show recent trainings."""
    user_id = await db.get_or_create_user(message.from_user.id)
    trainings = await db.get_recent_trainings(user_id, limit=5)

    if not trainings:
        await message.answer("📭 История пуста.\n\nОтправь голосовое сообщение, чтобы начать!")
        return

    lines = ["📚 Последние тренировки:", ""]

    for training_date, entries in trainings.items():
        summary = format_training_summary(entries, training_date)
        lines.append(summary)
        lines.append("")

    await message.answer("\n".join(lines))


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Show overall statistics."""
    user_id = await db.get_or_create_user(message.from_user.id)
    stats = await db.get_total_stats(user_id)

    if stats["total_sets"] == 0:
        await message.answer("📭 Статистика пуста.\n\nОтправь голосовое сообщение, чтобы начать!")
        return

    lines = [
        "📊 Общая статистика:",
        "",
        f"🏋️ Всего подходов: {stats['total_sets']}",
        f"📋 Упражнений: {stats['total_exercises']}",
        f"📆 Тренировок: {stats['total_trainings']}",
        "",
        f"📅 Первая тренировка: {stats['first_date']}",
        f"📅 Последняя: {stats['last_date']}",
        "",
        "Выбери упражнение для детальной статистики:",
    ]

    exercises = await db.get_all_exercises(user_id)
    keyboard = exercise_list_keyboard(exercises)

    await message.answer("\n".join(lines), reply_markup=keyboard)


@dp.message(Command("exercise"))
async def cmd_exercise(message: Message):
    """Show stats for specific exercise."""
    user_id = await db.get_or_create_user(message.from_user.id)

    # Extract exercise name from command
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        exercises = await db.get_all_exercises(user_id)
        if exercises:
            text = "📋 Укажи упражнение:\n/exercise <название>\n\nТвои упражнения:\n"
            text += "\n".join(f"• {e}" for e in exercises[:15])
        else:
            text = "📭 У тебя пока нет записанных упражнений."
        await message.answer(text)
        return

    exercise_query = parts[1].strip().lower()

    # Find matching exercise
    exercises = await db.get_all_exercises(user_id)
    matching = [e for e in exercises if exercise_query in e.lower()]

    if not matching:
        await message.answer(f"❌ Упражнение «{parts[1]}» не найдено.")
        return

    exercise = matching[0]  # Take first match
    await _show_exercise_stats(message, user_id, exercise)


async def _show_exercise_stats(message: Message, user_id: int, exercise: str):
    """Display stats for an exercise."""
    stats = await db.get_exercise_stats(user_id, exercise)
    history = await db.get_exercise_history(user_id, exercise, limit=5)

    lines = [
        f"📊 {exercise}",
        "",
        f"🏋️ Всего подходов: {stats['total_sets']}",
    ]

    if stats['max_weight']:
        lines.append(f"💪 Макс. вес: {_format_weight(stats['max_weight'])}")
    if stats['max_reps']:
        lines.append(f"🔄 Макс. повторений: {stats['max_reps']}")
    if stats['avg_weight']:
        lines.append(f"📈 Средний вес: {_format_weight(stats['avg_weight'])}")

    lines.extend([
        "",
        f"📅 Первый раз: {stats['first_date']}",
        f"📅 Последний: {stats['last_date']}",
    ])

    if history:
        lines.extend(["", "Последние подходы:"])
        for entry in history[:5]:
            date_str = entry.created_at.strftime("%d.%m")
            weight_str = _format_weight(entry.weight) if entry.weight else ""
            reps_str = f"×{entry.reps}" if entry.reps else ""
            lines.append(f"• {date_str}: {weight_str} {reps_str}".strip())

    await message.answer("\n".join(lines))


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel current operation."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять.")
        return

    await state.clear()
    await message.answer("❌ Действие отменено.")


# === Voice Message Handler ===

@dp.message(F.voice)
async def handle_voice(message: Message):
    """Process voice message and log exercise."""
    user_id = await db.get_or_create_user(message.from_user.id)

    # Send processing message
    processing_msg = await message.answer("🎤 Обрабатываю...")

    try:
        # Download voice file
        voice = message.voice
        file = await bot.get_file(voice.file_id)
        file_data = await bot.download_file(file.file_path)
        audio_bytes = file_data.read()

        # Transcribe
        logger.info(f"Transcribing voice message for user {message.from_user.id}")
        text = await transcriber.transcribe(audio_bytes)
        logger.info(f"Transcribed: {text}")

        if not text.strip():
            await processing_msg.edit_text("❌ Не удалось распознать речь. Попробуй ещё раз.")
            return

        # Parse exercise
        logger.info(f"Parsing exercise from: {text}")
        parsed = await parser.parse(text)
        logger.info(f"Parsed: {parsed}")

        # Save to database
        entry = await db.add_entry(
            user_id=user_id,
            exercise=parsed.exercise,
            exercise_raw=parsed.exercise_raw,
            weight=parsed.weight,
            reps=parsed.reps,
            comment=parsed.comment,
        )

        # Get training info
        training_num = await db.get_training_number(user_id)
        today_entries = await db.get_today_entries(user_id)
        set_num = len(today_entries)

        # Build response
        response_text = await _build_entry_message(user_id, entry, training_num, set_num)

        # Edit the processing message with result
        await processing_msg.edit_text(
            response_text,
            reply_markup=entry_edit_keyboard(entry.id),
        )

    except Exception as e:
        logger.exception(f"Error processing voice message: {e}")
        await processing_msg.edit_text(
            f"❌ Ошибка обработки: {str(e)}\n\nПопробуй ещё раз."
        )


# === Callback Handlers ===

@dp.callback_query(F.data.startswith("edit:"))
async def handle_edit(callback: CallbackQuery, state: FSMContext):
    """Handle edit button press."""
    _, entry_id, field = callback.data.split(":")
    entry_id = int(entry_id)

    entry = await db.get_entry(entry_id)
    if not entry:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    # Store entry_id and message_id in state for later
    await state.update_data(
        edit_entry_id=entry_id,
        edit_message_id=callback.message.message_id,
    )

    field_prompts = {
        "exercise": f"Текущее упражнение: {entry.exercise}\n\nВведи новое название:",
        "weight": f"Текущий вес: {_format_weight(entry.weight)}\n\nВведи новый вес (число в кг):",
        "reps": f"Текущие повторения: {entry.reps or '—'}\n\nВведи количество повторений:",
        "comment": f"Текущий комментарий: {entry.comment or '—'}\n\nВведи новый комментарий (или «-» для удаления):",
    }

    states = {
        "exercise": EditStates.waiting_for_exercise,
        "weight": EditStates.waiting_for_weight,
        "reps": EditStates.waiting_for_reps,
        "comment": EditStates.waiting_for_comment,
    }

    await state.set_state(states[field])
    await callback.message.answer(
        field_prompts[field],
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete:"))
async def handle_delete(callback: CallbackQuery):
    """Handle delete button - ask for confirmation."""
    entry_id = int(callback.data.split(":")[1])

    entry = await db.get_entry(entry_id)
    if not entry:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    await callback.message.answer(
        f"Удалить запись?\n\n{format_entry(entry)}",
        reply_markup=confirm_delete_keyboard(entry_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_delete:"))
async def handle_confirm_delete(callback: CallbackQuery):
    """Actually delete the entry."""
    entry_id = int(callback.data.split(":")[1])

    deleted = await db.delete_entry(entry_id)
    if deleted:
        await callback.message.edit_text("✅ Запись удалена.")
    else:
        await callback.message.edit_text("❌ Запись не найдена.")

    await callback.answer()


@dp.callback_query(F.data.startswith("cancel_delete:"))
async def handle_cancel_delete(callback: CallbackQuery):
    """Cancel deletion."""
    await callback.message.delete()
    await callback.answer("Отменено")


@dp.callback_query(F.data == "cancel")
async def handle_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel current edit operation."""
    await state.clear()
    await callback.message.delete()
    await callback.answer("Отменено")


@dp.callback_query(F.data.startswith("exercise_stats:"))
async def handle_exercise_stats(callback: CallbackQuery):
    """Show stats for selected exercise."""
    exercise = callback.data.split(":", 1)[1]
    user_id = await db.get_or_create_user(callback.from_user.id)
    await _show_exercise_stats(callback.message, user_id, exercise)
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    """Do nothing (for page number button)."""
    await callback.answer()


# === Edit State Handlers ===

@dp.message(EditStates.waiting_for_exercise)
async def process_exercise_edit(message: Message, state: FSMContext):
    """Process new exercise name."""
    data = await state.get_data()
    entry_id = data["edit_entry_id"]
    original_msg_id = data["edit_message_id"]

    new_exercise_raw = message.text.strip()

    # Re-parse to normalize
    new_exercise = await reparse_exercise_name(config.anthropic_api_key, new_exercise_raw)

    entry = await db.update_entry(
        entry_id,
        exercise=new_exercise,
        exercise_raw=new_exercise_raw,
    )

    await state.clear()
    await message.answer(f"✅ Упражнение изменено: {new_exercise}")

    # Update original message
    await _update_entry_message(message.chat.id, original_msg_id, entry)


@dp.message(EditStates.waiting_for_weight)
async def process_weight_edit(message: Message, state: FSMContext):
    """Process new weight."""
    data = await state.get_data()
    entry_id = data["edit_entry_id"]
    original_msg_id = data["edit_message_id"]

    try:
        # Handle various input formats
        text = message.text.strip().lower().replace(",", ".")
        text = text.replace("кг", "").replace("kg", "").strip()
        new_weight = float(text)
    except ValueError:
        await message.answer("❌ Введи число (например: 60 или 72.5)")
        return

    old_entry = await db.get_entry(entry_id)
    entry = await db.update_entry(entry_id, weight=new_weight)

    await state.clear()
    await message.answer(
        f"✅ Вес изменён: {_format_weight(old_entry.weight)} → {_format_weight(new_weight)}"
    )

    await _update_entry_message(message.chat.id, original_msg_id, entry)


@dp.message(EditStates.waiting_for_reps)
async def process_reps_edit(message: Message, state: FSMContext):
    """Process new reps count."""
    data = await state.get_data()
    entry_id = data["edit_entry_id"]
    original_msg_id = data["edit_message_id"]

    try:
        new_reps = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи целое число (например: 8)")
        return

    old_entry = await db.get_entry(entry_id)
    entry = await db.update_entry(entry_id, reps=new_reps)

    await state.clear()
    await message.answer(
        f"✅ Повторения изменены: {old_entry.reps or '—'} → {new_reps}"
    )

    await _update_entry_message(message.chat.id, original_msg_id, entry)


@dp.message(EditStates.waiting_for_comment)
async def process_comment_edit(message: Message, state: FSMContext):
    """Process new comment."""
    data = await state.get_data()
    entry_id = data["edit_entry_id"]
    original_msg_id = data["edit_message_id"]

    new_comment = message.text.strip()
    if new_comment == "-":
        new_comment = None

    entry = await db.update_entry(entry_id, comment=new_comment)

    await state.clear()
    await message.answer(f"✅ Комментарий изменён")

    await _update_entry_message(message.chat.id, original_msg_id, entry)


async def _update_entry_message(chat_id: int, message_id: int, entry: Entry):
    """Update the original entry message with new data."""
    try:
        user_id = entry.user_id
        training_num = await db.get_training_number(user_id)
        today_entries = await db.get_today_entries(user_id)

        # Find position of this entry in today's list
        set_num = next(
            (i + 1 for i, e in enumerate(today_entries) if e.id == entry.id),
            len(today_entries)
        )

        response_text = await _build_entry_message(user_id, entry, training_num, set_num)

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=response_text,
            reply_markup=entry_edit_keyboard(entry.id),
        )
    except Exception as e:
        logger.warning(f"Could not update original message: {e}")


# === Main ===

async def main():
    """Start the bot."""
    global config, bot, db, transcriber, parser

    # Load config
    config = get_config()

    # Initialize components
    bot = Bot(token=config.telegram_bot_token)
    db = Database(config.db_path)
    transcriber = Transcriber(config.openai_api_key)
    parser = ExerciseParser(config.anthropic_api_key)

    # Connect to database
    await db.connect()
    logger.info(f"Database connected: {config.db_path}")

    # Start polling
    logger.info("Starting bot...")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
