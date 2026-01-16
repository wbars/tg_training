import aiosqlite
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional


@dataclass
class Entry:
    id: int
    user_id: int
    exercise: str  # normalized name
    exercise_raw: str  # original parsed name
    weight: Optional[float]
    reps: Optional[int]
    comment: Optional[str]
    created_at: datetime

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Entry":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            exercise=row["exercise"],
            exercise_raw=row["exercise_raw"],
            weight=row["weight"],
            reps=row["reps"],
            comment=row["comment"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Initialize database connection and create tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._create_tables()

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        await self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                exercise TEXT NOT NULL,
                exercise_raw TEXT,
                weight REAL,
                reps INTEGER,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_entries_user_exercise
                ON entries(user_id, exercise);
            CREATE INDEX IF NOT EXISTS idx_entries_user_date
                ON entries(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_entries_user_id
                ON entries(user_id);
        """)
        await self._connection.commit()

    async def get_or_create_user(self, telegram_id: int) -> int:
        """Get user ID by telegram_id, creating if necessary."""
        cursor = await self._connection.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        if row:
            return row["id"]

        cursor = await self._connection.execute(
            "INSERT INTO users (telegram_id) VALUES (?)", (telegram_id,)
        )
        await self._connection.commit()
        return cursor.lastrowid

    async def add_entry(
        self,
        user_id: int,
        exercise: str,
        exercise_raw: str,
        weight: Optional[float],
        reps: Optional[int],
        comment: Optional[str],
    ) -> Entry:
        """Add a new training entry."""
        cursor = await self._connection.execute(
            """
            INSERT INTO entries (user_id, exercise, exercise_raw, weight, reps, comment)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, exercise, exercise_raw, weight, reps, comment),
        )
        await self._connection.commit()

        cursor = await self._connection.execute(
            "SELECT * FROM entries WHERE id = ?", (cursor.lastrowid,)
        )
        row = await cursor.fetchone()
        return Entry.from_row(row)

    async def get_entry(self, entry_id: int) -> Optional[Entry]:
        """Get entry by ID."""
        cursor = await self._connection.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        )
        row = await cursor.fetchone()
        return Entry.from_row(row) if row else None

    async def update_entry(
        self,
        entry_id: int,
        exercise: Optional[str] = None,
        exercise_raw: Optional[str] = None,
        weight: Optional[float] = None,
        reps: Optional[int] = None,
        comment: Optional[str] = None,
    ) -> Optional[Entry]:
        """Update an entry field."""
        entry = await self.get_entry(entry_id)
        if not entry:
            return None

        updates = []
        values = []

        if exercise is not None:
            updates.append("exercise = ?")
            values.append(exercise)
        if exercise_raw is not None:
            updates.append("exercise_raw = ?")
            values.append(exercise_raw)
        if weight is not None:
            updates.append("weight = ?")
            values.append(weight)
        if reps is not None:
            updates.append("reps = ?")
            values.append(reps)
        if comment is not None:
            updates.append("comment = ?")
            values.append(comment)

        if updates:
            values.append(entry_id)
            await self._connection.execute(
                f"UPDATE entries SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            await self._connection.commit()

        return await self.get_entry(entry_id)

    async def delete_entry(self, entry_id: int) -> bool:
        """Delete an entry."""
        cursor = await self._connection.execute(
            "DELETE FROM entries WHERE id = ?", (entry_id,)
        )
        await self._connection.commit()
        return cursor.rowcount > 0

    async def get_today_entries(self, user_id: int) -> list[Entry]:
        """Get all entries for today."""
        today = date.today().isoformat()
        cursor = await self._connection.execute(
            """
            SELECT * FROM entries
            WHERE user_id = ? AND date(created_at) = ?
            ORDER BY created_at ASC
            """,
            (user_id, today),
        )
        rows = await cursor.fetchall()
        return [Entry.from_row(row) for row in rows]

    async def get_today_entry_number(self, user_id: int) -> int:
        """Get the number of entries logged today (for numbering)."""
        entries = await self.get_today_entries(user_id)
        return len(entries)

    async def get_training_number(self, user_id: int) -> int:
        """Get the training session number (unique days with entries)."""
        cursor = await self._connection.execute(
            """
            SELECT COUNT(DISTINCT date(created_at)) as count
            FROM entries WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0

    async def get_last_entry_date(self, user_id: int) -> Optional[date]:
        """Get the date of the last entry."""
        cursor = await self._connection.execute(
            """
            SELECT created_at FROM entries
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        if row:
            return datetime.fromisoformat(row["created_at"]).date()
        return None

    async def get_exercise_history(
        self, user_id: int, exercise: str, limit: int = 10
    ) -> list[Entry]:
        """Get history for a specific exercise."""
        cursor = await self._connection.execute(
            """
            SELECT * FROM entries
            WHERE user_id = ? AND exercise = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, exercise, limit),
        )
        rows = await cursor.fetchall()
        return [Entry.from_row(row) for row in rows]

    async def get_exercise_max_weight(
        self, user_id: int, exercise: str
    ) -> Optional[float]:
        """Get maximum weight ever lifted for an exercise."""
        cursor = await self._connection.execute(
            """
            SELECT MAX(weight) as max_weight FROM entries
            WHERE user_id = ? AND exercise = ? AND weight IS NOT NULL
            """,
            (user_id, exercise),
        )
        row = await cursor.fetchone()
        return row["max_weight"] if row else None

    async def get_exercise_max_reps(
        self, user_id: int, exercise: str, weight: Optional[float] = None
    ) -> Optional[int]:
        """Get maximum reps for an exercise (optionally at specific weight)."""
        if weight is not None:
            cursor = await self._connection.execute(
                """
                SELECT MAX(reps) as max_reps FROM entries
                WHERE user_id = ? AND exercise = ? AND weight = ? AND reps IS NOT NULL
                """,
                (user_id, exercise, weight),
            )
        else:
            cursor = await self._connection.execute(
                """
                SELECT MAX(reps) as max_reps FROM entries
                WHERE user_id = ? AND exercise = ? AND reps IS NOT NULL
                """,
                (user_id, exercise),
            )
        row = await cursor.fetchone()
        return row["max_reps"] if row else None

    async def get_last_exercise_entry(
        self, user_id: int, exercise: str, exclude_today: bool = False
    ) -> Optional[Entry]:
        """Get the most recent entry for an exercise."""
        if exclude_today:
            today = date.today().isoformat()
            cursor = await self._connection.execute(
                """
                SELECT * FROM entries
                WHERE user_id = ? AND exercise = ? AND date(created_at) < ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, exercise, today),
            )
        else:
            cursor = await self._connection.execute(
                """
                SELECT * FROM entries
                WHERE user_id = ? AND exercise = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, exercise),
            )
        row = await cursor.fetchone()
        return Entry.from_row(row) if row else None

    async def get_recent_trainings(
        self, user_id: int, limit: int = 5
    ) -> dict[date, list[Entry]]:
        """Get recent training sessions grouped by date."""
        cursor = await self._connection.execute(
            """
            SELECT DISTINCT date(created_at) as training_date
            FROM entries WHERE user_id = ?
            ORDER BY training_date DESC LIMIT ?
            """,
            (user_id, limit),
        )
        dates = [row["training_date"] for row in await cursor.fetchall()]

        result = {}
        for d in dates:
            cursor = await self._connection.execute(
                """
                SELECT * FROM entries
                WHERE user_id = ? AND date(created_at) = ?
                ORDER BY created_at ASC
                """,
                (user_id, d),
            )
            rows = await cursor.fetchall()
            result[date.fromisoformat(d)] = [Entry.from_row(row) for row in rows]

        return result

    async def get_all_exercises(self, user_id: int) -> list[str]:
        """Get all unique exercises for a user."""
        cursor = await self._connection.execute(
            """
            SELECT DISTINCT exercise FROM entries
            WHERE user_id = ?
            ORDER BY exercise
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [row["exercise"] for row in rows]

    async def get_exercise_stats(
        self, user_id: int, exercise: str
    ) -> dict:
        """Get statistics for an exercise."""
        cursor = await self._connection.execute(
            """
            SELECT
                COUNT(*) as total_sets,
                MAX(weight) as max_weight,
                MAX(reps) as max_reps,
                AVG(weight) as avg_weight,
                MIN(date(created_at)) as first_date,
                MAX(date(created_at)) as last_date
            FROM entries
            WHERE user_id = ? AND exercise = ?
            """,
            (user_id, exercise),
        )
        row = await cursor.fetchone()
        return {
            "total_sets": row["total_sets"],
            "max_weight": row["max_weight"],
            "max_reps": row["max_reps"],
            "avg_weight": round(row["avg_weight"], 1) if row["avg_weight"] else None,
            "first_date": row["first_date"],
            "last_date": row["last_date"],
        }

    async def get_total_stats(self, user_id: int) -> dict:
        """Get overall statistics for a user."""
        cursor = await self._connection.execute(
            """
            SELECT
                COUNT(*) as total_sets,
                COUNT(DISTINCT exercise) as total_exercises,
                COUNT(DISTINCT date(created_at)) as total_trainings,
                MIN(date(created_at)) as first_date,
                MAX(date(created_at)) as last_date
            FROM entries WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return {
            "total_sets": row["total_sets"],
            "total_exercises": row["total_exercises"],
            "total_trainings": row["total_trainings"],
            "first_date": row["first_date"],
            "last_date": row["last_date"],
        }
