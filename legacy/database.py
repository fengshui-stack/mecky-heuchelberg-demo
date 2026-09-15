"""
Datenbank-Modul für Chat-Logs und Bot-Status
"""

import aiosqlite
from datetime import datetime, timedelta
from typing import Optional
import json

DATABASE_PATH = "chatbot.db"


async def init_database():
    """Initialisiert die SQLite Datenbank mit den benötigten Tabellen."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Tabelle für Chat-Sessions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT UNIQUE NOT NULL,
                bot_active BOOLEAN DEFAULT TRUE,
                last_message_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Tabelle für Chat-Nachrichten (Logs)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                sender TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (phone_number) REFERENCES chat_sessions(phone_number)
            )
        """)

        # Index für schnellere Abfragen
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_phone
            ON chat_messages(phone_number)
        """)

        await db.commit()


async def get_or_create_session(phone_number: str, session_timeout_hours: int = 24) -> dict:
    """
    Holt oder erstellt eine Chat-Session.
    Gibt zurück ob es eine neue Session ist (für Begrüßung).
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Prüfe ob Session existiert
        cursor = await db.execute(
            "SELECT * FROM chat_sessions WHERE phone_number = ?",
            (phone_number,)
        )
        session = await cursor.fetchone()

        now = datetime.now()
        is_new_session = False

        if session is None:
            # Neue Session erstellen
            await db.execute(
                """INSERT INTO chat_sessions (phone_number, bot_active, last_message_at)
                   VALUES (?, TRUE, ?)""",
                (phone_number, now.isoformat())
            )
            await db.commit()
            is_new_session = True
            bot_active = True
        else:
            # Prüfe Session Timeout
            last_message = datetime.fromisoformat(session["last_message_at"]) if session["last_message_at"] else None

            if last_message is None or (now - last_message) > timedelta(hours=session_timeout_hours):
                is_new_session = True

            bot_active = bool(session["bot_active"])

            # Update last_message_at
            await db.execute(
                "UPDATE chat_sessions SET last_message_at = ? WHERE phone_number = ?",
                (now.isoformat(), phone_number)
            )
            await db.commit()

        return {
            "phone_number": phone_number,
            "is_new_session": is_new_session,
            "bot_active": bot_active
        }


async def set_bot_status(phone_number: str, active: bool):
    """Setzt den Bot-Status für eine Telefonnummer (aktiv/inaktiv)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO chat_sessions (phone_number, bot_active, last_message_at)
               VALUES (?, ?, ?)
               ON CONFLICT(phone_number) DO UPDATE SET bot_active = ?""",
            (phone_number, active, datetime.now().isoformat(), active)
        )
        await db.commit()


async def get_bot_status(phone_number: str) -> bool:
    """Prüft ob der Bot für diese Nummer aktiv ist."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT bot_active FROM chat_sessions WHERE phone_number = ?",
            (phone_number,)
        )
        result = await cursor.fetchone()

        if result is None:
            return True  # Default: Bot ist aktiv

        return bool(result[0])


async def log_message(phone_number: str, content: str, sender: str, message_type: str = "text"):
    """Speichert eine Nachricht in der Datenbank."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO chat_messages (phone_number, message_type, content, sender, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (phone_number, message_type, content, sender, datetime.now().isoformat())
        )
        await db.commit()


async def get_chat_history(phone_number: str, limit: int = 50) -> list[dict]:
    """Holt die Chat-Historie für eine Telefonnummer."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM chat_messages
               WHERE phone_number = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (phone_number, limit)
        )
        rows = await cursor.fetchall()

        return [dict(row) for row in reversed(rows)]


async def get_all_chats() -> list[dict]:
    """Holt alle Chat-Sessions für das Dashboard."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT cs.*,
                      (SELECT content FROM chat_messages
                       WHERE phone_number = cs.phone_number
                       ORDER BY timestamp DESC LIMIT 1) as last_message,
                      (SELECT COUNT(*) FROM chat_messages
                       WHERE phone_number = cs.phone_number) as message_count
               FROM chat_sessions cs
               ORDER BY cs.last_message_at DESC"""
        )
        rows = await cursor.fetchall()

        return [dict(row) for row in rows]


async def get_recent_messages(limit: int = 100) -> list[dict]:
    """Holt die neuesten Nachrichten aller Chats für das Dashboard."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM chat_messages
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,)
        )
        rows = await cursor.fetchall()

        return [dict(row) for row in rows]
