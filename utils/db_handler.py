import sqlite3
import os
import datetime
import json

DB_PATH = "./data/albert_stats.db"

def init_db():
    """Oppretter databasen og tabeller hvis de ikke finnes."""
    if not os.path.exists("./data"):
        os.makedirs("./data")
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Hardware-profilering (Endret timestamp til TEXT for Python 3.12 kompatibilitet)
    c.execute('''CREATE TABLE IF NOT EXISTS hardware_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    temp REAL,
                    ipc REAL,
                    stalled_cycles REAL,
                    load REAL
                )''')

    # 2. AI-ytelse (token speed vs ressurser)
    c.execute('''CREATE TABLE IF NOT EXISTS ai_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    tokens_per_sec REAL,
                    temp REAL,
                    load REAL
                )''')

    # 3. Game Tracker (Scoreboard)
    c.execute('''CREATE TABLE IF NOT EXISTS game_tracker (
                    user_id TEXT,
                    server_id TEXT,
                    game_name TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, server_id, game_name)
                )''')

    # 4. Lagring av meldings-IDer for scoreboard-kanaler
    c.execute('''CREATE TABLE IF NOT EXISTS scoreboard_settings (
                    server_id TEXT PRIMARY KEY,
                    channel_id TEXT,
                    message_id TEXT
                )''')
    
    conn.commit()
    conn.close()

# --- HARDWARE & AI FUNKSJONER ---

def log_hardware(temp, ipc, stalled, load):
    """Logger hardware-stats til SQLite uten deprecation warnings."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    # Bruker isoformat() for å unngå SQLite adapter-advarsler i Python 3.12
    timestamp = datetime.datetime.now().isoformat()
    c.execute("INSERT INTO hardware_logs (timestamp, temp, ipc, stalled_cycles, load) VALUES (?, ?, ?, ?, ?)",
              (timestamp, temp, ipc, stalled, load))
    conn.commit(); conn.close()

def get_latest_hw_logs(limit=10):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM hardware_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = c.fetchall(); conn.close(); return rows

def log_ai_performance(tps, temp, load):
    """Logger AI-ytelse til SQLite."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    timestamp = datetime.datetime.now().isoformat()
    c.execute("INSERT INTO ai_performance (timestamp, tokens_per_sec, temp, load) VALUES (?, ?, ?, ?)",
              (timestamp, tps, temp, load))
    conn.commit(); conn.close()

def get_latest_ai_perf():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT tokens_per_sec, temp FROM ai_performance ORDER BY timestamp DESC LIMIT 1")
    row = c.fetchone(); conn.close(); return row

# --- GAME TRACKER FUNKSJONER ---

def update_game_time(user_id, server_id, game_name, seconds):
    """Oppdaterer total spilletid for en bruker på en spesifikk server."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''INSERT INTO game_tracker (user_id, server_id, game_name, duration_seconds)
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(user_id, server_id, game_name) 
                 DO UPDATE SET duration_seconds = duration_seconds + ?''',
              (str(user_id), str(server_id), game_name, seconds, seconds))
    conn.commit(); conn.close()

def get_server_scoreboard(server_id):
    """Henter global toppliste for spill (summen av alle brukeres tid)."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''SELECT game_name, SUM(duration_seconds) as total_time
                 FROM game_tracker 
                 WHERE server_id = ? 
                 GROUP BY game_name
                 ORDER BY total_time DESC LIMIT 15''', (str(server_id),))
    rows = c.fetchall(); conn.close(); return rows

def get_personal_stats(user_id, server_id):
    """Henter topp 5 spill for en spesifikk bruker på en server."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''SELECT game_name, duration_seconds 
                 FROM game_tracker 
                 WHERE user_id = ? AND server_id = ? 
                 ORDER BY duration_seconds DESC LIMIT 5''', (str(user_id), str(server_id)))
    rows = c.fetchall(); conn.close(); return rows

def save_scoreboard_msg(server_id, channel_id, message_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO scoreboard_settings VALUES (?, ?, ?)", 
              (str(server_id), str(channel_id), str(message_id)))
    conn.commit(); conn.close()

def get_scoreboard_msg(server_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT channel_id, message_id FROM scoreboard_settings WHERE server_id = ?", (str(server_id),))
    row = c.fetchone(); conn.close(); return row

# Initialiser databasen ved import
init_db()