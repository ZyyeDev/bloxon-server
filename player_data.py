import os
import json
import time
import asyncio
from typing import Dict, Any, Optional
from config import (
    SERVER_PUBLIC_IP,
    VOLUME_PATH,
    CACHE_TTL
)
from game_database import (
    get_player_data as fb_get_player_data,
    save_player_data as fb_save_player_data,
    get_friends as fb_get_friends
)
from player_save_tracker import save_tracker

player_cache = {}

DEFAULT_PLAYER_SCHEMA = {
    "schemaVersion": 1,
    "currency": 10,
    "friends": [],
    "ownedAccessories": [],
    "avatar": {
        "bodyColors": {
            "head": "#ffccaa",
            "torso": "#00c9ff",
            "left_leg": "#b5ff00",
            "right_leg": "#b5ff00",
            "left_arm": "#ffccaa",
            "right_arm": "#ffccaa"
        },
        "accessories": []
    },
    "pfp": f"http://{SERVER_PUBLIC_IP}:{os.environ.get('PORT', 8080)}/pfps/default.png",
    "serverId": None,
    "private_server_active": False,
    "private_server_expires": 0
}

def ensurePlayerDataDefaults(playerData: Dict[str, Any]) -> Dict[str, Any]:
    result = playerData.copy()
    def applyDefaults(data: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
        for key, defaultValue in defaults.items():
            if key not in data:
                if isinstance(defaultValue, dict):
                    data[key] = {}
                    applyDefaults(data[key], defaultValue)
                else:
                    data[key] = defaultValue
            elif isinstance(defaultValue, dict) and isinstance(data[key], dict):
                applyDefaults(data[key], defaultValue)
        return data
    result = applyDefaults(result, DEFAULT_PLAYER_SCHEMA)
    if result.get("schemaVersion", 0) < DEFAULT_PLAYER_SCHEMA["schemaVersion"]:
        result["schemaVersion"] = DEFAULT_PLAYER_SCHEMA["schemaVersion"]
    return result

def getPlayerData(userId: int) -> Optional[Dict[str, Any]]:
    currentTime = time.time()
    cacheKey = f"player_{userId}"
    if cacheKey in player_cache:
        cached_data, expiry = player_cache[cacheKey]
        if currentTime < expiry:
            return ensurePlayerDataDefaults(cached_data)
        else:
            del player_cache[cacheKey]

    data = fb_get_player_data(userId)

    if data:
        if "ownedAccessories" in data and isinstance(data["ownedAccessories"], str):
            try:
                data["ownedAccessories"] = json.loads(data["ownedAccessories"])
            except:
                data["ownedAccessories"] = []

        if "avatar" in data and isinstance(data["avatar"], str):
            try:
                data["avatar"] = json.loads(data["avatar"])
            except:
                data["avatar"] = DEFAULT_PLAYER_SCHEMA["avatar"]

        player_cache[cacheKey] = (data, currentTime + CACHE_TTL)
        return ensurePlayerDataDefaults(data)

    return None

async def savePlayerData(userId: int, data: Dict[str, Any]):
    save_id = await save_tracker.start_save(userId, "player_data")

    try:
        data = ensurePlayerDataDefaults(data)

        if "ownedAccessories" in data and isinstance(data["ownedAccessories"], list):
            data["ownedAccessories"] = json.dumps(data["ownedAccessories"])

        if "avatar" in data and isinstance(data["avatar"], dict):
            data["avatar"] = json.dumps(data["avatar"])

        fb_save_player_data(userId, data)

        cacheKey = f"player_{userId}"
        if cacheKey in player_cache:
            del player_cache[cacheKey]

        await save_tracker.complete_save(save_id, success=True)
    except Exception as e:
        print(f"Error saving player data for user {userId}: {e}")
        await save_tracker.complete_save(save_id, success=False)
        raise

async def createPlayerData(userId: int, username: str) -> Dict[str, Any]:
    from friends import getFriends
    playerData = DEFAULT_PLAYER_SCHEMA.copy()
    playerData["username"] = username
    playerData["userId"] = userId
    playerData["friends"] = getFriends(userId)

    await savePlayerData(userId, playerData)

    return playerData

async def updatePlayerAvatar(userId: int, avatarData: Dict[str, Any]) -> Dict[str, Any]:
    playerData = getPlayerData(userId)
    if not playerData:
        return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}
    playerData["avatar"] = avatarData
    await savePlayerData(userId, playerData)
    return {"success": True, "data": playerData}

async def setPlayerServer(userId: int, serverId: Optional[str]) -> Dict[str, Any]:
    playerData = getPlayerData(userId)
    if not playerData:
        return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}
    
    playerData["serverId"] = serverId
    await savePlayerData(userId, playerData)
    return {"success": True, "data": {"userId": userId, "serverId": serverId}}

async def clearPlayerServer(userId: int) -> Dict[str, Any]:
    return await setPlayerServer(userId, None)

def getPlayerFullProfile(userId: int) -> Dict[str, Any]:
    from friends import getFriends
    from avatar_service import getUserAccessories
    from currency_system import getCurrency
    from pfp_service import getPfp
    playerData = getPlayerData(userId)
    if not playerData:
        return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}
    profile = playerData.copy()
    profile["friends"] = getFriends(userId)
    profile["ownedAccessories"] = getUserAccessories(userId)
    currencyResult = getCurrency(userId)
    if currencyResult["success"]:
        profile["currency"] = currencyResult["data"]["balance"]
    profile["pfp"] = getPfp(userId)
    return {"success": True, "data": profile}

def resetAllPlayerServers():
    print("Note: resetAllPlayerServers not implemented for SQLite (requires full table scan)")

def clear_player_cache():
    global player_cache
    player_cache.clear()

def invalidate_player_cache(userId: int):
    cacheKey = f"player_{userId}"
    if cacheKey in player_cache:
        del player_cache[cacheKey]
