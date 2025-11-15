from typing import Dict, Any
import time
import asyncio
from player_save_tracker import save_tracker
from config import CACHE_TTL

CURRENCY_NAME = "Blips"
currency_cache = {}

async def creditCurrency(userId: int, amount: int) -> Dict[str, Any]:
    from player_data import getPlayerData, savePlayerData, invalidate_player_cache
    if amount <= 0:
        return {"success": False, "error": {"code": "INVALID_AMOUNT", "message": "Amount must be positive"}}

    save_id = await save_tracker.start_save(userId, "credit_currency")

    try:
        playerData = getPlayerData(userId)
        if not playerData:
            await save_tracker.complete_save(save_id, success=False)
            return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}
        currentCurrency = playerData.get("currency", 0)
        newCurrency = currentCurrency + amount
        playerData["currency"] = newCurrency
        await savePlayerData(userId, playerData)
        invalidate_player_cache(userId)
        _invalidate_currency_cache(userId)

        await save_tracker.complete_save(save_id, success=True)
        return {"success": True, "data": {"previousBalance": currentCurrency, "newBalance": newCurrency, "amount": amount}}
    except Exception as e:
        await save_tracker.complete_save(save_id, success=False)
        raise

async def debitCurrency(userId: int, amount: int) -> Dict[str, Any]:
    from player_data import getPlayerData, savePlayerData, invalidate_player_cache
    if amount <= 0:
        return {"success": False, "error": {"code": "INVALID_AMOUNT", "message": "Amount must be positive"}}

    save_id = await save_tracker.start_save(userId, "debit_currency")

    try:
        playerData = getPlayerData(userId)
        if not playerData:
            await save_tracker.complete_save(save_id, success=False)
            return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}
        currentCurrency = playerData.get("currency", 0)
        if currentCurrency < amount:
            await save_tracker.complete_save(save_id, success=False)
            return {"success": False, "error": {"code": "INSUFFICIENT_FUNDS", "message": "Not enough currency"}}
        newCurrency = currentCurrency - amount
        playerData["currency"] = newCurrency
        await savePlayerData(userId, playerData)
        invalidate_player_cache(userId)
        _invalidate_currency_cache(userId)

        await save_tracker.complete_save(save_id, success=True)
        return {"success": True, "data": {"previousBalance": currentCurrency, "newBalance": newCurrency, "amount": amount}}
    except Exception as e:
        await save_tracker.complete_save(save_id, success=False)
        raise

def getCurrency(userId: int) -> Dict[str, Any]:
    from player_data import getPlayerData
    currentTime = time.time()
    cacheKey = f"currency_{userId}"
    if cacheKey in currency_cache:
        cached_data, expiry = currency_cache[cacheKey]
        if currentTime < expiry:
            return {"success": True, "data": {"balance": cached_data, "currencyName": CURRENCY_NAME}}
        else:
            del currency_cache[cacheKey]
    playerData = getPlayerData(userId)
    if not playerData:
        return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}
    balance = playerData.get("currency", 0)
    currency_cache[cacheKey] = (balance, currentTime + CACHE_TTL)
    return {"success": True, "data": {"balance": balance, "currencyName": CURRENCY_NAME}}

async def transferCurrency(fromUserId: int, toUserId: int, amount: int) -> Dict[str, Any]:
    if fromUserId == toUserId:
        return {"success": False, "error": {"code": "SAME_USER", "message": "Cannot transfer to yourself"}}
    debitResult = await debitCurrency(fromUserId, amount)
    if not debitResult["success"]:
        return debitResult
    creditResult = await creditCurrency(toUserId, amount)
    if not creditResult["success"]:
        await creditCurrency(fromUserId, amount)
        return creditResult
    return {"success": True, "data": {"from": fromUserId, "to": toUserId, "amount": amount}}

def _invalidate_currency_cache(userId: int):
    cacheKey = f"currency_{userId}"
    if cacheKey in currency_cache:
        del currency_cache[cacheKey]

def clear_currency_cache():
    global currency_cache
    currency_cache.clear()
