import aiosqlite
import os
import json

DB_FILE = "./data/bot_data.db"

async def init_db():
    if not os.path.exists("./data"): os.makedirs("./data")
    async with aiosqlite.connect(DB_FILE) as db:
        # Tabell for Kalender-events
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                dato TEXT, tittel TEXT, lagt_til_av TEXT
            )
        """)
        # Tabell for Quiz (Global state)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                answer TEXT, category TEXT, prompt TEXT, active INTEGER
            )
        """)
        # Tabell for Quiz Poeng
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_scores (
                user_id TEXT, score INTEGER, PRIMARY KEY (user_id)
            )
        """)
        
        # Tabell for aktive meldinger
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_quiz_messages (
                guild_id TEXT, channel_id TEXT, message_id TEXT
            )
        """)

        # NY: Tabell for å logge Albert sine AI-oppslag (valgfri, men nyttig)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_stats (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        """)
        
        await db.commit()

# --- EVENTS ---
async def add_event(dato, tittel, bruker):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO events VALUES (?, ?, ?)", (dato, tittel, bruker))
        await db.commit()

async def get_events(dato):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT tittel, lagt_til_av FROM events WHERE dato = ?", (dato,)) as cursor:
            return await cursor.fetchall()

# --- QUIZ STATE ---
async def set_quiz_state(answer, category, prompt):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR REPLACE INTO quiz_state (id, answer, category, prompt, active) VALUES (1, ?, ?, ?, 1)", (answer, category, prompt))
        await db.commit()

async def get_quiz_state():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT answer, category, active FROM quiz_state WHERE id = 1") as cursor:
            return await cursor.fetchone()

async def add_quiz_score(user_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO quiz_scores (user_id, score) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET score = score + 1", (str(user_id),))
        await db.commit()

# --- QUIZ MELDINGS-LOGG ---
async def log_quiz_message(guild_id, channel_id, message_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO active_quiz_messages VALUES (?, ?, ?)", 
                         (str(guild_id), str(channel_id), str(message_id)))
        await db.commit()

async def get_active_quiz_messages():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT guild_id, channel_id, message_id FROM active_quiz_messages") as cursor:
            return await cursor.fetchall()

async def clear_quiz_messages():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM active_quiz_messages")
        await db.commit()