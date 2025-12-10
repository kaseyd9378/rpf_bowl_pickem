
import sqlite3
from pathlib import Path

DB_PATH = Path('bowl_pickem.db')

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS contests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        access_code TEXT NOT NULL,
        admin_code TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS games(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER NOT NULL,
        bowl_name TEXT NOT NULL,
        team1 TEXT NOT NULL,
        team2 TEXT NOT NULL,
        game_date TEXT,
        game_time_et TEXT,
        network TEXT,
        location TEXT,
        is_cfp INTEGER NOT NULL DEFAULT 0,
        cfp_round TEXT,
        points_per_win INTEGER NOT NULL DEFAULT 1,
        kickoff_et TEXT,
        kickoff_pt TEXT,
        lock_pt TEXT,
        winner TEXT,
        FOREIGN KEY(contest_id) REFERENCES contests(id)
    );

    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER NOT NULL,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'player',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(contest_id) REFERENCES contests(id)
    );

    CREATE TABLE IF NOT EXISTS picks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        pick TEXT NOT NULL CHECK (pick IN ('team1','team2')),
        points_awarded INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id, game_id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(game_id) REFERENCES games(id)
    );

    CREATE TABLE IF NOT EXISTS cfp_links(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        slot TEXT NOT NULL CHECK (slot IN ('team1','team2')),
        depends_on_game_id INTEGER NOT NULL,
        FOREIGN KEY(game_id) REFERENCES games(id),
        FOREIGN KEY(depends_on_game_id) REFERENCES games(id)
    );
    ''')
    conn.commit()
    conn.close()
