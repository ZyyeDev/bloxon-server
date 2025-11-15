import os
import time
import json
from typing import Dict, Any, Optional, List
from database_manager import execute_query, buffer_write, flush_write_buffer
from config import (
    VOLUME_PATH,
    DB_DIR,
    BACKUP_DIR
)

def ensure_volume_directories():
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(os.path.join(VOLUME_PATH, "pfps"), exist_ok=True)

ensure_volume_directories()

def save_account(username: str, password: str, gender: str) -> int:
    query = "INSERT INTO accounts (username, password, gender, created, username_changes) VALUES (?, ?, ?, ?, ?)"
    user_id = execute_query(query, (username, password, gender, time.time(), 0))
    return user_id

def get_account_by_username(username: str) -> Optional[Dict[str, Any]]:
    query = "SELECT user_id, username, password, gender, created, username_changes FROM accounts WHERE username = ?"
    result = execute_query(query, (username,), fetch_one=True)

    if result:
        return {
            "user_id": result[0],
            "username": result[1],
            "password": result[2],
            "gender": result[3],
            "created": result[4],
            "username_changes": result[5]
        }
    return None

def get_account_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    query = "SELECT user_id, username, password, gender, created, username_changes FROM accounts WHERE user_id = ?"
    result = execute_query(query, (user_id,), fetch_one=True)

    if result:
        return {
            "user_id": result[0],
            "username": result[1],
            "password": result[2],
            "gender": result[3],
            "created": result[4],
            "username_changes": result[5]
        }
    return None

def update_username(user_id: int, new_username: str):
    query = "UPDATE accounts SET username = ?, username_changes = username_changes + 1 WHERE user_id = ?"
    execute_query(query, (new_username, user_id))

def update_password(user_id: int, new_password: str):
    query = "UPDATE accounts SET password = ? WHERE user_id = ?"
    execute_query(query, (new_password, user_id))

def save_token(token: str, username: str):
    query = "INSERT OR REPLACE INTO tokens (token, username, created) VALUES (?, ?, ?)"
    execute_query(query, (token, username, time.time()))

def get_token(token: str) -> Optional[Dict[str, Any]]:
    query = "SELECT token, username, created FROM tokens WHERE token = ?"
    result = execute_query(query, (token,), fetch_one=True)

    if result:
        return {
            "token": result[0],
            "username": result[1],
            "created": result[2]
        }
    return None

def delete_old_tokens(cutoff_timestamp: float):
    query = "DELETE FROM tokens WHERE created < ?"
    execute_query(query, (cutoff_timestamp,))

def get_player_data(user_id: int) -> Optional[Dict[str, Any]]:
    query = """SELECT user_id, username, currency, avatar_data, owned_accessories,
               pfp, server_id, schema_version, last_updated
               FROM player_data WHERE user_id = ?"""
    result = execute_query(query, (user_id,), fetch_one=True)

    if result:
        return {
            "userId": result[0],
            "username": result[1],
            "currency": result[2],
            "avatar": result[3] if result[3] else "{}",
            "ownedAccessories": result[4] if result[4] else "[]",
            "pfp": result[5],
            "serverId": result[6],
            "schemaVersion": result[7],
            "last_updated": result[8]
        }
    return None

def save_player_data(user_id: int, data: Dict[str, Any]):
    query = """INSERT OR REPLACE INTO player_data
               (user_id, username, currency, avatar_data, owned_accessories, pfp, server_id, schema_version, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

    avatar_str = data.get("avatar", "{}")
    if isinstance(avatar_str, dict):
        avatar_str = json.dumps(avatar_str)

    accessories_str = data.get("ownedAccessories", "[]")
    if isinstance(accessories_str, list):
        accessories_str = json.dumps(accessories_str)

    execute_query(query, (
        user_id,
        data.get("username", ""),
        data.get("currency", 100),
        avatar_str,
        accessories_str,
        data.get("pfp", ""),
        data.get("serverId"),
        data.get("schemaVersion", 1),
        time.time()
    ))

def save_friend(user_id: int, friend_id: int):
    query = "INSERT OR IGNORE INTO friends (user_id, friend_id, created) VALUES (?, ?, ?)"
    execute_query(query, (user_id, friend_id, time.time()))

def get_friends(user_id: int) -> List[int]:
    query = "SELECT friend_id FROM friends WHERE user_id = ?"
    results = execute_query(query, (user_id,), fetch_all=True)
    return [row[0] for row in results] if results else []

def delete_friend(user_id: int, friend_id: int):
    query = "DELETE FROM friends WHERE user_id = ? AND friend_id = ?"
    execute_query(query, (user_id, friend_id))

def save_friend_request(from_user_id: int, to_user_id: int):
    query = "INSERT OR IGNORE INTO friend_requests (from_user_id, to_user_id, created) VALUES (?, ?, ?)"
    execute_query(query, (from_user_id, to_user_id, time.time()))

def get_friend_requests_incoming(user_id: int) -> List[int]:
    query = "SELECT from_user_id FROM friend_requests WHERE to_user_id = ?"
    results = execute_query(query, (user_id,), fetch_all=True)
    return [row[0] for row in results] if results else []

def get_friend_requests_outgoing(user_id: int) -> List[int]:
    query = "SELECT to_user_id FROM friend_requests WHERE from_user_id = ?"
    results = execute_query(query, (user_id,), fetch_all=True)
    return [row[0] for row in results] if results else []

def delete_friend_request(from_user_id: int, to_user_id: int):
    query = "DELETE FROM friend_requests WHERE from_user_id = ? AND to_user_id = ?"
    execute_query(query, (from_user_id, to_user_id))

def get_accessory(accessory_id: int) -> Optional[Dict[str, Any]]:
    query = """SELECT accessory_id, name, type, price, model_file, texture_file,
               equip_slot, icon_file, mtl_file, created_at
               FROM accessories WHERE accessory_id = ?"""
    result = execute_query(query, (accessory_id,), fetch_one=True)

    if result:
        return {
            "accessory_id": result[0],
            "name": result[1],
            "type": result[2],
            "price": result[3],
            "model_file": result[4],
            "texture_file": result[5],
            "equip_slot": result[6],
            "icon_file": result[7],
            "mtl_file": result[8],
            "created_at": result[9]
        }
    return None

def save_accessory(accessory_id: int, name: str, accessory_type: str, price: int,
                  model_file: str, texture_file: str, mtl_file: str, equip_slot: str, icon_file: str):
    query = """INSERT OR REPLACE INTO accessories
               (accessory_id, name, type, price, model_file, texture_file, equip_slot, icon_file, mtl_file, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    execute_query(query, (accessory_id, name, accessory_type, price, model_file,
                         texture_file, equip_slot, icon_file, mtl_file, time.time()))

def list_accessories(filters: Optional[List] = None) -> List[Dict[str, Any]]:
    query = """SELECT accessory_id, name, type, price, model_file, texture_file,
               equip_slot, icon_file, mtl_file, created_at
               FROM accessories"""

    where_clauses = []
    params = []

    if filters:
        for filter_item in filters:
            field, op, value = filter_item
            if op == "==":
                where_clauses.append(f"{field} = ?")
                params.append(value)
            elif op == "<=":
                where_clauses.append(f"{field} <= ?")
                params.append(value)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    results = execute_query(query, tuple(params), fetch_all=True)

    accessories = []
    for row in results:
        accessories.append({
            "accessory_id": row[0],
            "name": row[1],
            "type": row[2],
            "price": row[3],
            "model_file": row[4],
            "texture_file": row[5],
            "equip_slot": row[6],
            "icon_file": row[7],
            "mtl_file": row[8],
            "created_at": row[9]
        })

    return accessories

def delete_accessory(accessory_id: int):
    query = "DELETE FROM accessories WHERE accessory_id = ?"
    execute_query(query, (accessory_id,))

def get_next_accessory_id() -> int:
    query = "SELECT MAX(accessory_id) FROM accessories"
    result = execute_query(query, fetch_one=True)
    max_id = result[0] if result and result[0] else 0
    return max_id + 1

def save_accessory_purchase(user_id: int, accessory_id: int, price_paid: int):
    query = """INSERT INTO accessory_purchases (user_id, accessory_id, price_paid, created)
               VALUES (?, ?, ?, ?)"""
    execute_query(query, (user_id, accessory_id, price_paid, time.time()))

def save_datastore(key: str, value: str):
    query = "INSERT OR REPLACE INTO datastores (key, value, timestamp) VALUES (?, ?, ?)"
    execute_query(query, (key, value, time.time()))

def get_datastore(key: str) -> Optional[Dict[str, Any]]:
    query = "SELECT key, value, timestamp FROM datastores WHERE key = ?"
    result = execute_query(query, (key,), fetch_one=True)

    if result:
        return {
            "key": result[0],
            "value": result[1],
            "timestamp": result[2]
        }
    return None

def delete_datastore(key: str):
    query = "DELETE FROM datastores WHERE key = ?"
    execute_query(query, (key,))

def list_datastore_keys(prefix: str = "") -> List[Dict[str, Any]]:
    query = "SELECT key, timestamp FROM datastores WHERE key LIKE ?"
    results = execute_query(query, (f"{prefix}%",), fetch_all=True)

    return [{"key": row[0], "timestamp": row[1]} for row in results] if results else []

def delete_old_datastores(cutoff_timestamp: float):
    query = "DELETE FROM datastores WHERE timestamp < ?"
    execute_query(query, (cutoff_timestamp,))

def save_payment_record(user_id: int, purchase_token: str, product_id: str,
                       amount: int, currency_awarded: int, verified: bool):
    query = """INSERT INTO payments
               (user_id, purchase_token, product_id, amount, currency_awarded, verified, created)
               VALUES (?, ?, ?, ?, ?, ?, ?)"""
    execute_query(query, (user_id, purchase_token, product_id, amount,
                         currency_awarded, verified, time.time()))

def save_ad_reward_record(user_id: int, ad_network: str, ad_unit_id: str,
                         reward_amount: int, verified: bool):
    query = """INSERT INTO ad_rewards
               (user_id, ad_network, ad_unit_id, reward_amount, verified, created)
               VALUES (?, ?, ?, ?, ?, ?)"""
    execute_query(query, (user_id, ad_network, ad_unit_id, reward_amount,
                         verified, time.time()))

def get_weather_types() -> List[str]:
    query = "SELECT weather_name FROM weather_types ORDER BY weather_name"
    results = execute_query(query, fetch_all=True)
    return [row[0] for row in results] if results else []

def add_weather_type(weather_name: str) -> bool:
    try:
        query = "INSERT INTO weather_types (weather_name, created) VALUES (?, ?)"
        execute_query(query, (weather_name, time.time()))
        return True
    except:
        return False

def remove_weather_type(weather_name: str) -> bool:
    try:
        query = "DELETE FROM weather_types WHERE weather_name = ?"
        execute_query(query, (weather_name,))
        return True
    except:
        return False

def count_accounts() -> int:
    query = "SELECT COUNT(*) FROM accounts"
    result = execute_query(query, fetch_one=True)
    return result[0] if result else 0
