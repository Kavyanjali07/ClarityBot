import sqlite3

DB_PATH = "claritybot.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS user_lang
                 (user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'id')''')
    return conn

def set_lang(user_id: int, lang: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("REPLACE INTO user_lang (user_id, lang) VALUES (?, ?)", (user_id, lang))
    conn.commit()
    conn.close()

def get_lang(user_id: int) -> str:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT lang FROM user_lang WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else "id"