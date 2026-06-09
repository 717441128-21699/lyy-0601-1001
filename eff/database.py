import sqlite3
import os
from pathlib import Path
from datetime import datetime, date


def get_db_path():
    config_dir = Path.home() / ".eff"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "eff.db"


def get_config_path():
    config_dir = Path.home() / ".eff"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def get_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        priority INTEGER DEFAULT 1,
        due_date DATE,
        tags TEXT,
        status TEXT DEFAULT 'pending',
        parent_id INTEGER,
        estimated_time INTEGER,
        actual_time INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        FOREIGN KEY (parent_id) REFERENCES tasks (id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pomodoros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        start_time DATETIME NOT NULL,
        end_time DATETIME,
        duration INTEGER DEFAULT 25,
        status TEXT DEFAULT 'running',
        interruptions INTEGER DEFAULT 0,
        interruption_notes TEXT,
        FOREIGN KEY (task_id) REFERENCES tasks (id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        category TEXT,
        tags TEXT,
        template_name TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        content TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_date DATE NOT NULL UNIQUE,
        content TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()
