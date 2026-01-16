from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def entry_edit_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    """Keyboard for editing a logged entry."""
    builder = InlineKeyboardBuilder()

    # First row: main fields
    builder.row(
        InlineKeyboardButton(
            text="Упражнение",
            callback_data=f"edit:{entry_id}:exercise"
        ),
        InlineKeyboardButton(
            text="Вес",
            callback_data=f"edit:{entry_id}:weight"
        ),
    )

    # Second row: reps and comment
    builder.row(
        InlineKeyboardButton(
            text="Повторы",
            callback_data=f"edit:{entry_id}:reps"
        ),
        InlineKeyboardButton(
            text="Коммент",
            callback_data=f"edit:{entry_id}:comment"
        ),
    )

    # Third row: delete
    builder.row(
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"delete:{entry_id}"
        ),
    )

    return builder.as_markup()


def confirm_delete_keyboard(entry_id: int) -> InlineKeyboardMarkup:
    """Confirmation keyboard for deletion."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"confirm_delete:{entry_id}"
        ),
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"cancel_delete:{entry_id}"
        ),
    )
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Simple cancel keyboard."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data="cancel"
        ),
    )
    return builder.as_markup()


def history_navigation_keyboard(
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Navigation for history viewing."""
    builder = InlineKeyboardBuilder()

    buttons = []
    if current_page > 0:
        buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"history:{current_page - 1}"
        ))

    buttons.append(InlineKeyboardButton(
        text=f"{current_page + 1}/{total_pages}",
        callback_data="noop"
    ))

    if current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton(
            text="Вперёд ▶️",
            callback_data=f"history:{current_page + 1}"
        ))

    builder.row(*buttons)
    return builder.as_markup()


def exercise_list_keyboard(exercises: list[str]) -> InlineKeyboardMarkup:
    """Keyboard with list of exercises for stats."""
    builder = InlineKeyboardBuilder()

    for exercise in exercises[:10]:  # Limit to 10
        # Truncate long names
        display_name = exercise[:25] + "..." if len(exercise) > 25 else exercise
        builder.row(InlineKeyboardButton(
            text=display_name,
            callback_data=f"exercise_stats:{exercise[:50]}"  # Callback data limit
        ))

    return builder.as_markup()
