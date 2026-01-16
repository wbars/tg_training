from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from .database import Database, Entry


@dataclass
class ExerciseInsight:
    """Insight about an exercise entry."""
    emoji: str
    text: str
    priority: int  # Lower = more important, shown first


async def generate_insights(
    db: Database,
    user_id: int,
    entry: Entry,
) -> list[ExerciseInsight]:
    """
    Generate analytics insights for a newly logged entry.

    Returns a list of insights sorted by priority.
    """
    insights = []
    today = date.today()

    # Get historical data
    history = await db.get_exercise_history(user_id, entry.exercise, limit=50)
    last_entry = await db.get_last_exercise_entry(
        user_id, entry.exercise, exclude_today=True
    )
    max_weight = await db.get_exercise_max_weight(user_id, entry.exercise)

    # Filter out current entry from history for comparisons
    history_without_current = [e for e in history if e.id != entry.id]

    # Check if this is a new exercise
    if len(history_without_current) == 0:
        insights.append(ExerciseInsight(
            emoji="🆕",
            text="Первое выполнение этого упражнения!",
            priority=1,
        ))
        return sorted(insights, key=lambda x: x.priority)

    # Check for personal record (weight)
    if entry.weight and max_weight:
        # Get max weight excluding current entry
        previous_max = max(
            (e.weight for e in history_without_current if e.weight),
            default=0
        )
        if entry.weight > previous_max:
            insights.append(ExerciseInsight(
                emoji="🏆",
                text=f"Личный рекорд веса! Было: {_format_weight(previous_max)}",
                priority=1,
            ))

    # Check for personal record (reps at same weight)
    if entry.weight and entry.reps:
        same_weight_entries = [
            e for e in history_without_current
            if e.weight == entry.weight and e.reps
        ]
        if same_weight_entries:
            max_reps_at_weight = max(e.reps for e in same_weight_entries)
            if entry.reps > max_reps_at_weight:
                insights.append(ExerciseInsight(
                    emoji="💪",
                    text=f"Рекорд повторений на {_format_weight(entry.weight)}! Было: {max_reps_at_weight}",
                    priority=2,
                ))

    # Compare with last session (not today)
    if last_entry:
        days_ago = (today - last_entry.created_at.date()).days

        # Time since last exercise
        if days_ago == 0:
            pass  # Same day, no need to mention
        elif days_ago == 1:
            insights.append(ExerciseInsight(
                emoji="📅",
                text="Вчера тоже делали это упражнение",
                priority=5,
            ))
        elif days_ago <= 7:
            insights.append(ExerciseInsight(
                emoji="📅",
                text=f"Последний раз: {days_ago} {_days_word(days_ago)} назад",
                priority=5,
            ))
        elif days_ago <= 14:
            insights.append(ExerciseInsight(
                emoji="⚠️",
                text=f"Больше недели перерыв ({days_ago} дней)",
                priority=3,
            ))
        else:
            weeks = days_ago // 7
            insights.append(ExerciseInsight(
                emoji="⚠️",
                text=f"Давно не делали: {weeks} {_weeks_word(weeks)} назад",
                priority=3,
            ))

        # Compare weight progress
        if entry.weight and last_entry.weight:
            diff = entry.weight - last_entry.weight
            if abs(diff) >= 0.5:  # Ignore tiny differences
                if diff > 0:
                    insights.append(ExerciseInsight(
                        emoji="📈",
                        text=f"+{diff:.1f} кг к прошлому разу ({_format_weight(last_entry.weight)})",
                        priority=4,
                    ))
                else:
                    insights.append(ExerciseInsight(
                        emoji="📉",
                        text=f"{diff:.1f} кг к прошлому разу ({_format_weight(last_entry.weight)})",
                        priority=4,
                    ))
            elif entry.reps and last_entry.reps:
                # Same weight, compare reps
                if entry.reps > last_entry.reps:
                    insights.append(ExerciseInsight(
                        emoji="📈",
                        text=f"+{entry.reps - last_entry.reps} повторений при том же весе",
                        priority=4,
                    ))
                elif entry.reps == last_entry.reps:
                    insights.append(ExerciseInsight(
                        emoji="🔄",
                        text="Тот же результат, что и в прошлый раз",
                        priority=6,
                    ))

    # Check week-ago comparison
    week_ago_start = today - timedelta(days=8)
    week_ago_end = today - timedelta(days=6)
    week_ago_entries = [
        e for e in history_without_current
        if week_ago_start <= e.created_at.date() <= week_ago_end
    ]
    if week_ago_entries and entry.weight:
        week_ago_weight = max(e.weight for e in week_ago_entries if e.weight) if any(e.weight for e in week_ago_entries) else None
        if week_ago_weight:
            diff = entry.weight - week_ago_weight
            if abs(diff) >= 2.5:
                if diff > 0:
                    insights.append(ExerciseInsight(
                        emoji="📊",
                        text=f"+{diff:.1f} кг за неделю",
                        priority=3,
                    ))

    return sorted(insights, key=lambda x: x.priority)


def _format_weight(weight: Optional[float]) -> str:
    """Format weight nicely."""
    if weight is None:
        return "—"
    if weight == int(weight):
        return f"{int(weight)} кг"
    return f"{weight:.1f} кг"


def _days_word(n: int) -> str:
    """Russian plural for days."""
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return "дня"
    else:
        return "дней"


def _weeks_word(n: int) -> str:
    """Russian plural for weeks."""
    if n % 10 == 1 and n % 100 != 11:
        return "неделю"
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return "недели"
    else:
        return "недель"


def format_entry(entry: Entry, include_time: bool = False) -> str:
    """Format an entry for display."""
    parts = [f"📋 {entry.exercise}"]

    weight_reps = []
    if entry.weight:
        weight_reps.append(_format_weight(entry.weight))
    if entry.reps:
        weight_reps.append(f"{entry.reps} повт.")

    if weight_reps:
        parts.append(f"🏋️ {' × '.join(weight_reps)}")

    if entry.comment:
        parts.append(f"💬 {entry.comment}")

    if include_time:
        time_str = entry.created_at.strftime("%H:%M")
        parts.append(f"🕐 {time_str}")

    return "\n".join(parts)


def format_entry_compact(entry: Entry) -> str:
    """Format entry in one line."""
    parts = [entry.exercise]
    if entry.weight:
        parts.append(_format_weight(entry.weight))
    if entry.reps:
        parts.append(f"×{entry.reps}")
    if entry.comment:
        parts.append(f"({entry.comment})")
    return " ".join(parts)


def format_training_summary(entries: list[Entry], training_date: date) -> str:
    """Format a full training session."""
    if not entries:
        return "Нет записей"

    date_str = _format_date(training_date)
    lines = [f"📆 {date_str}", ""]

    for i, entry in enumerate(entries, 1):
        time_str = entry.created_at.strftime("%H:%M")
        line = f"{i}. [{time_str}] {format_entry_compact(entry)}"
        lines.append(line)

    return "\n".join(lines)


def _format_date(d: date) -> str:
    """Format date in Russian."""
    today = date.today()
    if d == today:
        return "Сегодня"
    elif d == today - timedelta(days=1):
        return "Вчера"
    else:
        months = [
            "", "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ]
        return f"{d.day} {months[d.month]}"
