import sqlite3
import os
import json
import threading
import asyncio
import time
from typing import Dict, Any, Optional, List
from cryptography.fernet import Fernet
from concurrent.futures import ThreadPoolExecutor

DATA_DIR = "server_data"
DB_FILE = os.path.join(DATA_DIR, "gameserver.db")
KEY_FILE = os.path.join(DATA_DIR, "db_encryption.key")

db_lock = threading.RLock()
db_conn = None
query_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="db_")
write_buffer = []
write_buffer_lock = threading.Lock()
# dont change these plss
WRITE_BUFFER_SIZE = 50
WRITE_BUFFER_FLUSH_INTERVAL = 5.0
last_flush = time.time()

def generate_encryption_key():
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        os.chmod(KEY_FILE, 0o600)
        return key

    with open(KEY_FILE, "rb") as f:
        return f.read()

encryption_key = generate_encryption_key()
cipher = Fernet(encryption_key)

def encrypt_data(data: str) -> str:
    return cipher.encrypt(data.encode()).decode()

def decrypt_data(encrypted: str) -> str:
    try:
        return cipher.decrypt(encrypted.encode()).decode()
    except:
        return ""

def init_database():
    global db_conn
    os.makedirs(DATA_DIR, exist_ok=True)
    db_conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
    # copied these pragmas from somewhere, idk what they do nor i want to know
    # its 2 am and i just want to finish this
    db_conn.execute("PRAGMA journal_mode=WAL")
    db_conn.execute("PRAGMA synchronous=NORMAL")
    db_conn.execute("PRAGMA cache_size=20000")
    db_conn.execute("PRAGMA temp_store=MEMORY")
    db_conn.execute("PRAGMA query_only=False")
    db_conn.execute("PRAGMA mmap_size=30000000")
    db_conn.execute("PRAGMA page_size=4096")

    db_conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            gender TEXT NOT NULL,
            created REAL NOT NULL,
            username_changes INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            created REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS player_data (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            currency INTEGER DEFAULT 100,
            avatar_data TEXT,
            owned_accessories TEXT DEFAULT '[]',
            pfp TEXT,
            server_id TEXT,
            schema_version INTEGER DEFAULT 1,
            last_updated REAL,
            FOREIGN KEY (user_id) REFERENCES accounts(user_id)
        );

        CREATE TABLE IF NOT EXISTS friends (
            user_id INTEGER NOT NULL,
            friend_id INTEGER NOT NULL,
            created REAL NOT NULL,
            PRIMARY KEY (user_id, friend_id),
            FOREIGN KEY (user_id) REFERENCES accounts(user_id),
            FOREIGN KEY (friend_id) REFERENCES accounts(user_id)
        );

        CREATE TABLE IF NOT EXISTS friend_requests (
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            created REAL NOT NULL,
            PRIMARY KEY (from_user_id, to_user_id),
            FOREIGN KEY (from_user_id) REFERENCES accounts(user_id),
            FOREIGN KEY (to_user_id) REFERENCES accounts(user_id)
        );

        CREATE TABLE IF NOT EXISTS accessories (
            accessory_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            price INTEGER NOT NULL,
            model_file TEXT,
            texture_file TEXT,
            equip_slot TEXT,
            icon_file TEXT,
            mtl_file TEXT,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS datastores (
            key TEXT PRIMARY KEY,
            value TEXT,
            timestamp REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            purchase_token TEXT NOT NULL UNIQUE,
            product_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            currency_awarded INTEGER NOT NULL,
            verified BOOLEAN NOT NULL,
            created REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES accounts(user_id)
        );

        CREATE TABLE IF NOT EXISTS pending_payments (
            payment_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            purchase_token TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            created REAL NOT NULL,
            last_attempt REAL,
            FOREIGN KEY (user_id) REFERENCES accounts(user_id)
        );

        CREATE TABLE IF NOT EXISTS ad_rewards (
            reward_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ad_network TEXT NOT NULL,
            ad_unit_id TEXT NOT NULL,
            reward_amount INTEGER NOT NULL,
            verified BOOLEAN NOT NULL,
            created REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES accounts(user_id)
        );

        CREATE TABLE IF NOT EXISTS accessory_purchases (
            purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            accessory_id INTEGER NOT NULL,
            price_paid INTEGER NOT NULL,
            created REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES accounts(user_id),
            FOREIGN KEY (accessory_id) REFERENCES accessories(accessory_id)
        );

        CREATE TABLE IF NOT EXISTS weather_types (
            weather_id INTEGER PRIMARY KEY AUTOINCREMENT,
            weather_name TEXT UNIQUE NOT NULL,
            created REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_tokens_created ON tokens(created);
        CREATE INDEX IF NOT EXISTS idx_tokens_username ON tokens(username);
        CREATE INDEX IF NOT EXISTS idx_datastores_timestamp ON datastores(timestamp);
        CREATE INDEX IF NOT EXISTS idx_friends_user ON friends(user_id);
        CREATE INDEX IF NOT EXISTS idx_friend_requests_to ON friend_requests(to_user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_ad_rewards_user ON ad_rewards(user_id);
        CREATE INDEX IF NOT EXISTS idx_accounts_username ON accounts(username);
        CREATE INDEX IF NOT EXISTS idx_player_data_updated ON player_data(last_updated);
        CREATE INDEX IF NOT EXISTS idx_pending_payments_user ON pending_payments(user_id);
    """)

    db_conn.commit()
    return db_conn

def get_connection():
    global db_conn
    if db_conn is None:
        db_conn = init_database()
    return db_conn

def execute_query(query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False):
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(query, params)

            if fetch_one:
                result = cursor.fetchone()
                conn.commit()
                return result
            elif fetch_all:
                result = cursor.fetchall()
                conn.commit()
                return result
            else:
                conn.commit()
                return cursor.lastrowid
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                conn.rollback()
                raise
            raise
        except Exception as e:
            conn.rollback()
            raise

def execute_query_async(query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(
        query_executor,
        lambda: execute_query(query, params, fetch_one, fetch_all)
    )

def buffer_write(query: str, params: tuple):
    global last_flush

    with write_buffer_lock:
        write_buffer.append((query, params))

        should_flush = (
            len(write_buffer) >= WRITE_BUFFER_SIZE or
            (time.time() - last_flush) >= WRITE_BUFFER_FLUSH_INTERVAL
        )

    if should_flush:
        flush_write_buffer()

def flush_write_buffer():
    global last_flush

    with write_buffer_lock:
        if not write_buffer:
            return

        queries = write_buffer.copy()
        write_buffer.clear()

    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()

        try:
            for query, params in queries:
                cursor.execute(query, params)
            conn.commit()
            last_flush = time.time()
        except Exception as e:
            conn.rollback()
            raise

def save_payment_record(user_id: int, purchase_token: str, product_id: str,
                       amount: int, currency_awarded: int, verified: bool) -> int:
    query = """INSERT INTO payments
               (user_id, purchase_token, product_id, amount, currency_awarded, verified, created)
               VALUES (?, ?, ?, ?, ?, ?, ?)"""
    return execute_query(query, (user_id, purchase_token, product_id, amount,
                                 currency_awarded, verified, time.time()))

def save_ad_reward_record(user_id: int, ad_network: str, ad_unit_id: str,
                         reward_amount: int, verified: bool) -> int:
    query = """INSERT INTO ad_rewards
               (user_id, ad_network, ad_unit_id, reward_amount, verified, created)
               VALUES (?, ?, ?, ?, ?, ?)"""
    return execute_query(query, (user_id, ad_network, ad_unit_id, reward_amount,
                                 verified, time.time()))

def save_accessory_purchase(user_id: int, accessory_id: int, price_paid: int) -> int:
    query = """INSERT INTO accessory_purchases
               (user_id, accessory_id, price_paid, created)
               VALUES (?, ?, ?, ?)"""
    return execute_query(query, (user_id, accessory_id, price_paid, time.time()))

def get_weather_types() -> List[str]:
    query = "SELECT weather_name FROM weather_types ORDER BY weather_name"
    results = execute_query(query, fetch_all=True)
    return [row[0] for row in results] if results else []

def add_weather_type(weather_name: str) -> bool:
    try:
        execute_query("INSERT INTO weather_types (weather_name, created) VALUES (?, ?)",
                     (weather_name, time.time()))
        return True
    except:
        return False

def remove_weather_type(weather_name: str) -> bool:
    try:
        execute_query("DELETE FROM weather_types WHERE weather_name = ?", (weather_name,))
        return True
    except:
        return False

def cleanup_old_data(days: int = 30):
    cutoff = time.time() - (days * 86400)
    execute_query("DELETE FROM datastores WHERE timestamp < ?", (cutoff,))
    execute_query("DELETE FROM tokens WHERE created < ?", (cutoff,))

init_database()
