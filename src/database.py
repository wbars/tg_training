import asyncpg
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
    def from_row(cls, row: asyncpg.Record) -> "Entry":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            exercise=row["exercise"],
            exercise_raw=row["exercise_raw"],
            weight=float(row["weight"]) if row["weight"] is not None else None,
            reps=row["reps"],
            comment=row["comment"],
            created_at=row["created_at"],
        )


class Database:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Initialize database connection pool and create tables."""
        self._pool = await asyncpg.create_pool(self.database_url)
        await self._create_tables()

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    exercise TEXT NOT NULL,
                    exercise_raw TEXT,
                    weight DECIMAL(10,2),
                    reps INTEGER,
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_entries_user_exercise
                    ON entries(user_id, exercise)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_entries_user_date
                    ON entries(user_id, created_at)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_entries_user_id
                    ON entries(user_id)
            """)

    async def get_or_create_user(self, telegram_id: int) -> int:
        """Get user ID by telegram_id, creating if necessary."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM users WHERE telegram_id = $1", telegram_id
            )
            if row:
                return row["id"]

            row = await conn.fetchrow(
                "INSERT INTO users (telegram_id) VALUES ($1) RETURNING id",
                telegram_id
            )
            return row["id"]

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
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO entries (user_id, exercise, exercise_raw, weight, reps, comment)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                user_id, exercise, exercise_raw, weight, reps, comment
            )
            return Entry.from_row(row)

    async def get_entry(self, entry_id: int) -> Optional[Entry]:
        """Get entry by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM entries WHERE id = $1", entry_id
            )
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
        param_count = 0

        if exercise is not None:
            param_count += 1
            updates.append(f"exercise = ${param_count}")
            values.append(exercise)
        if exercise_raw is not None:
            param_count += 1
            updates.append(f"exercise_raw = ${param_count}")
            values.append(exercise_raw)
        if weight is not None:
            param_count += 1
            updates.append(f"weight = ${param_count}")
            values.append(weight)
        if reps is not None:
            param_count += 1
            updates.append(f"reps = ${param_count}")
            values.append(reps)
        if comment is not None:
            param_count += 1
            updates.append(f"comment = ${param_count}")
            values.append(comment)

        if updates:
            param_count += 1
            values.append(entry_id)
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"UPDATE entries SET {', '.join(updates)} WHERE id = ${param_count}",
                    *values
                )

        return await self.get_entry(entry_id)

    async def delete_entry(self, entry_id: int) -> bool:
        """Delete an entry."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM entries WHERE id = $1", entry_id
            )
            return result == "DELETE 1"

    async def get_today_entries(self, user_id: int) -> list[Entry]:
        """Get all entries for today."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM entries
                WHERE user_id = $1 AND DATE(created_at) = CURRENT_DATE
                ORDER BY created_at ASC
                """,
                user_id
            )
            return [Entry.from_row(row) for row in rows]

    async def get_today_entry_number(self, user_id: int) -> int:
        """Get the number of entries logged today (for numbering)."""
        entries = await self.get_today_entries(user_id)
        return len(entries)

    async def get_training_number(self, user_id: int) -> int:
        """Get the training session number (unique days with entries)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(DISTINCT DATE(created_at)) as count
                FROM entries WHERE user_id = $1
                """,
                user_id
            )
            return row["count"] if row else 0

    async def get_last_entry_date(self, user_id: int) -> Optional[date]:
        """Get the date of the last entry."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT created_at FROM entries
                WHERE user_id = $1
                ORDER BY created_at DESC LIMIT 1
                """,
                user_id
            )
            if row:
                return row["created_at"].date()
            return None

    async def get_exercise_history(
        self, user_id: int, exercise: str, limit: int = 10
    ) -> list[Entry]:
        """Get history for a specific exercise."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM entries
                WHERE user_id = $1 AND exercise = $2
                ORDER BY created_at DESC LIMIT $3
                """,
                user_id, exercise, limit
            )
            return [Entry.from_row(row) for row in rows]

    async def get_exercise_max_weight(
        self, user_id: int, exercise: str
    ) -> Optional[float]:
        """Get maximum weight ever lifted for an exercise."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT MAX(weight) as max_weight FROM entries
                WHERE user_id = $1 AND exercise = $2 AND weight IS NOT NULL
                """,
                user_id, exercise
            )
            return float(row["max_weight"]) if row and row["max_weight"] else None

    async def get_exercise_max_reps(
        self, user_id: int, exercise: str, weight: Optional[float] = None
    ) -> Optional[int]:
        """Get maximum reps for an exercise (optionally at specific weight)."""
        async with self._pool.acquire() as conn:
            if weight is not None:
                row = await conn.fetchrow(
                    """
                    SELECT MAX(reps) as max_reps FROM entries
                    WHERE user_id = $1 AND exercise = $2 AND weight = $3 AND reps IS NOT NULL
                    """,
                    user_id, exercise, weight
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT MAX(reps) as max_reps FROM entries
                    WHERE user_id = $1 AND exercise = $2 AND reps IS NOT NULL
                    """,
                    user_id, exercise
                )
            return row["max_reps"] if row else None

    async def get_last_exercise_entry(
        self, user_id: int, exercise: str, exclude_today: bool = False
    ) -> Optional[Entry]:
        """Get the most recent entry for an exercise."""
        async with self._pool.acquire() as conn:
            if exclude_today:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM entries
                    WHERE user_id = $1 AND exercise = $2 AND DATE(created_at) < CURRENT_DATE
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    user_id, exercise
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM entries
                    WHERE user_id = $1 AND exercise = $2
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    user_id, exercise
                )
            return Entry.from_row(row) if row else None

    async def get_recent_trainings(
        self, user_id: int, limit: int = 5
    ) -> dict[date, list[Entry]]:
        """Get recent training sessions grouped by date."""
        async with self._pool.acquire() as conn:
            date_rows = await conn.fetch(
                """
                SELECT DISTINCT DATE(created_at) as training_date
                FROM entries WHERE user_id = $1
                ORDER BY training_date DESC LIMIT $2
                """,
                user_id, limit
            )
            dates = [row["training_date"] for row in date_rows]

            result = {}
            for d in dates:
                rows = await conn.fetch(
                    """
                    SELECT * FROM entries
                    WHERE user_id = $1 AND DATE(created_at) = $2
                    ORDER BY created_at ASC
                    """,
                    user_id, d
                )
                result[d] = [Entry.from_row(row) for row in rows]

            return result

    async def get_all_exercises(self, user_id: int) -> list[str]:
        """Get all unique exercises for a user."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT exercise FROM entries
                WHERE user_id = $1
                ORDER BY exercise
                """,
                user_id
            )
            return [row["exercise"] for row in rows]

    async def get_exercise_stats(
        self, user_id: int, exercise: str
    ) -> dict:
        """Get statistics for an exercise."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_sets,
                    MAX(weight) as max_weight,
                    MAX(reps) as max_reps,
                    AVG(weight) as avg_weight,
                    MIN(DATE(created_at)) as first_date,
                    MAX(DATE(created_at)) as last_date
                FROM entries
                WHERE user_id = $1 AND exercise = $2
                """,
                user_id, exercise
            )
            return {
                "total_sets": row["total_sets"],
                "max_weight": float(row["max_weight"]) if row["max_weight"] else None,
                "max_reps": row["max_reps"],
                "avg_weight": round(float(row["avg_weight"]), 1) if row["avg_weight"] else None,
                "first_date": str(row["first_date"]) if row["first_date"] else None,
                "last_date": str(row["last_date"]) if row["last_date"] else None,
            }

    async def get_total_stats(self, user_id: int) -> dict:
        """Get overall statistics for a user."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_sets,
                    COUNT(DISTINCT exercise) as total_exercises,
                    COUNT(DISTINCT DATE(created_at)) as total_trainings,
                    MIN(DATE(created_at)) as first_date,
                    MAX(DATE(created_at)) as last_date
                FROM entries WHERE user_id = $1
                """,
                user_id
            )
            return {
                "total_sets": row["total_sets"],
                "total_exercises": row["total_exercises"],
                "total_trainings": row["total_trainings"],
                "first_date": str(row["first_date"]) if row["first_date"] else None,
                "last_date": str(row["last_date"]) if row["last_date"] else None,
            }
