## this file was originally useful
## now it isnt at all, just mix this with main.py, or just put all
## endpoints of main.py here

from aiohttp import web
import time
import os
import asyncio
import auth_utils
#from auth_utils import hashPassword, verifyPassword
from moderation_service import validate_username
from game_database import get_account_by_username
from friends import addFriendDirect, removeFriend, getFriends, sendFriendRequest, getFriendRequests, acceptFriendRequest, rejectFriendRequest, cancelFriendRequest
from avatar_service import getFullAvatar, getAccessory, buyItem, listMarketItems, getUserAccessories, equipAccessory, unequipAccessory
from currency_system import creditCurrency, debitCurrency, getCurrency, transferCurrency
from player_data import getPlayerData, savePlayerData, createPlayerData, updatePlayerAvatar, setPlayerServer, getPlayerFullProfile
from pfp_service import getPfp, updateUserPfp

def checkRateLimit(clientIp):
    return auth_utils.checkRateLimit(clientIp)

def validateToken(token):
    return auth_utils.validateToken(token)

def getUserIdFromToken(token):
    username = auth_utils.getUsernameFromToken(token)
    if not username:
        return None

    result = get_account_by_username(username)
    return result["user_id"] if result else None

async def addFriendEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    friendId = requestData.get("friendId")

    if not userId or not friendId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = addFriendDirect(userId, friendId)
    if result["success"]:
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def removeFriendEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    friendId = requestData.get("friendId")

    if not userId or not friendId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = removeFriend(userId, friendId)
    return web.json_response(result)

async def getFriendsEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    friends = getFriends(userId)
    return web.json_response({"success": True, "data": friends})

async def getFullAvatarEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = requestData.get("userId")
    if not userId:
        userId = getUserIdFromToken(token)

    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    avatar = getFullAvatar(userId)
    return web.json_response({"success": True, "data": avatar})

async def getAccessoryEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    #token = requestData.get("token")
    #if not token or not validateToken(token):
    #    return web.json_response({"error": "invalid_token"}, status=401)

    accessoryId = requestData.get("accessoryId")
    if not accessoryId:
        return web.json_response({"error": "missing_accessory_id"}, status=400)

    accessory = getAccessory(accessoryId)
    if accessory:
        return web.json_response({"success": True, "data": accessory})
    else:
        return web.json_response({"success": False, "error": {"code": "NOT_FOUND", "message": "Accessory not found"}}, status=404)

async def buyItemEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    itemId = requestData.get("itemId")

    if not userId or not itemId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = await buyItem(userId, itemId)
    if result["success"]:
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def equipAccessoryEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    accessoryId = requestData.get("accessoryId")

    if not userId or not accessoryId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = await equipAccessory(userId, accessoryId)
    if result["success"]:
        asyncio.create_task(updateUserPfp(userId))
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def unequipAccessoryEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    accessoryId = requestData.get("accessoryId")

    if not userId or not accessoryId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = await unequipAccessory(userId, accessoryId)
    if result["success"]:
        asyncio.create_task(updateUserPfp(userId))
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def listMarketItemsEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    filterData = requestData.get("filter")
    pagination = requestData.get("pagination")

    result = listMarketItems(filterData, pagination)
    return web.json_response(result)

async def getUserAccessoriesEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = requestData.get("userId")
    if not userId:
        userId = getUserIdFromToken(token)

    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    accessories = getUserAccessories(userId)
    return web.json_response({"success": True, "data": accessories})

async def creditCurrencyEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    amount = requestData.get("amount")

    if not userId or not amount:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = await creditCurrency(userId, amount)
    if result["success"]:
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def debitCurrencyEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    amount = requestData.get("amount")

    if not userId or not amount:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = await debitCurrency(userId, amount)
    if result["success"]:
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def getCurrencyEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    result = getCurrency(userId)
    return web.json_response(result)

async def getPfpEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = requestData.get("userId")
    if not userId:
        userId = getUserIdFromToken(token)

    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    pfpUrl = getPfp(userId)
    return web.json_response({"success": True, "data": {"pfp": pfpUrl}})

async def updateAvatarEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    avatarData = requestData.get("avatar")

    if not userId or not avatarData:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = await updatePlayerAvatar(userId, avatarData)

    if result["success"]:
        await updateUserPfp(userId)

    return web.json_response(result)

async def getPlayerProfileEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = requestData.get("userId")
    if not userId:
        userId = getUserIdFromToken(token)

    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    result = getPlayerFullProfile(userId)
    return web.json_response(result)

async def setPlayerServerEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    serverId = requestData.get("serverId")

    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    result = await setPlayerServer(userId, serverId)
    return web.json_response(result)

async def sendFriendRequestEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    fromUserId = getUserIdFromToken(token)
    toUserId = requestData.get("toUserId")

    if not fromUserId or not toUserId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = sendFriendRequest(fromUserId, toUserId)
    if result["success"]:
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def getFriendRequestsEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    result = getFriendRequests(userId)
    return web.json_response(result)

async def acceptFriendRequestEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    requesterId = requestData.get("requesterId")

    if not userId or not requesterId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = acceptFriendRequest(userId, requesterId)
    if result["success"]:
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def rejectFriendRequestEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    requesterId = requestData.get("requesterId")

    if not userId or not requesterId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = rejectFriendRequest(userId, requesterId)
    if result["success"]:
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def cancelFriendRequestEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    targetUserId = requestData.get("targetUserId")

    if not userId or not targetUserId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    result = cancelFriendRequest(userId, targetUserId)
    if result["success"]:
        return web.json_response(result)
    else:
        return web.json_response(result, status=400)

async def checkFreeUsername(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")

    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    username = auth_utils.getUsernameFromToken(token)
    user_data = get_account_by_username(username)

    if not user_data:
        return web.json_response({"error": "user_not_found"}, status=404)

    user_id = user_data["user_id"]
    username_changes = user_data.get("username_changes", 0)

    cost = 0 if username_changes == 0 else 150

    return web.json_response({
        "required": cost
    })

async def changeUsername(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    new_username = requestData.get("new_username", "").strip()

    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    if not new_username:
        return web.json_response({"error": "missing_new_username"}, status=400)

    validation = validate_username(new_username)
    if not validation["valid"]:
        return web.json_response({"error": validation["error"]}, status=400)

    username = auth_utils.getUsernameFromToken(token)
    user_data = get_account_by_username(username)

    if not user_data:
        return web.json_response({"error": "user_not_found"}, status=404)

    user_id = user_data["user_id"]
    old_username = user_data["username"]
    username_changes = user_data.get("username_changes", 0)

    existing = get_account_by_username(new_username)
    if existing:
        return web.json_response({"error": "username_taken"}, status=409)

    cost = 0 if username_changes == 0 else 150

    if cost > 0:
        from currency_system import getCurrency, debitCurrency
        currency_result = getCurrency(user_id)
        if not currency_result["success"]:
            return web.json_response({"error": "failed_to_check_balance"}, status=500)

        balance = currency_result["data"]["balance"]
        if balance < cost:
            return web.json_response({
                "error": "insufficient_funds",
                "required": cost,
                "balance": balance
            }, status=400)

        debit_result = await debitCurrency(user_id, cost)
        if not debit_result["success"]:
            return web.json_response(debit_result, status=400)

    from game_database import update_username
    update_username(user_id, new_username)

    from database_manager import execute_query
    query = "UPDATE tokens SET username = ? WHERE username = ?"
    execute_query(query, (new_username, old_username))

    from player_data import getPlayerData, savePlayerData
    player_data = getPlayerData(user_id)
    if player_data:
        player_data["username"] = new_username
        await savePlayerData(user_id, player_data)

    auth_utils.clear_token_cache()

    return web.json_response({
        "success": True,
        "new_username": new_username,
        "cost": cost,
        "changes_count": username_changes + 1,
        "token_still_valid": True
    })

async def changePassword(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    old_password = requestData.get("old_password", "")
    new_password = requestData.get("new_password", "")

    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    if not old_password or not new_password:
        return web.json_response({"error": "missing_passwords"}, status=400)

    if len(new_password) < 6:
        return web.json_response({"error": "password_too_short"}, status=400)

    username = auth_utils.getUsernameFromToken(token)
    user_data = get_account_by_username(username)

    if not user_data:
        return web.json_response({"error": "user_not_found"}, status=404)

    if not verifyPassword(old_password, user_data["password"]):
        return web.json_response({"error": "incorrect_old_password"}, status=401)

    hashed_new_password = hashPassword(new_password)

    from game_database import update_password
    update_password(user_data["user_id"], hashed_new_password)

    return web.json_response({
        "success": True,
        "message": "Password changed successfully"
    })

async def joinFriendServer(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    friendId = requestData.get("friendId")

    if not userId or not friendId:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    friendData = getPlayerData(friendId)
    if not friendData:
        return web.json_response({"error": "friend_not_found"}, status=404)

    serverId = friendData.get("serverId")
    if not serverId:
        return web.json_response({"error": "friend_not_in_server"}, status=400)

    from vm_lifecycle_manager import vm_registry, vm_registry_lock
    import asyncio

    async with vm_registry_lock:
        for vm_id, vm_info in vm_registry.items():
            servers = vm_info.get("servers", {})
            if serverId in servers:
                server_data = servers[serverId]
                player_count = server_data.get("player_count", 0)

                # if plr count is 7 we wont let anyone else join
                # nvm, thinking about it again, we will let player count be at its max ONLY if it is a friend
                if player_count >= 8: # TODO: Make this configurable on the .env
                    return web.json_response({"error": "server_full"}, status=400)

                await setPlayerServer(userId, serverId)

                return web.json_response({
                    "success": True,
                    "data": {
                        "uid": serverId,
                        "ip": vm_info.get("ip"),
                        "port": server_data["port"],
                        "vm_id": vm_id
                    }
                })

    return web.json_response({"error": "server_not_found"}, status=404)

async def subscribePrivateServer(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    # TODO: THESE MUST BE CONFIGURABLE!!!!!!
    PRIVATE_SERVER_COST = 250
    SUBSCRIPTION_DAYS = 30

    from currency_system import getCurrency, debitCurrency
    from player_data import getPlayerData, savePlayerData
    import time

    currency_result = getCurrency(userId)
    if not currency_result["success"]:
        return web.json_response({"error": "failed_to_check_balance"}, status=500)

    balance = currency_result["data"]["balance"]
    if balance < PRIVATE_SERVER_COST:
        return web.json_response({
            "error": "insufficient_funds",
            "required": PRIVATE_SERVER_COST,
            "balance": balance
        }, status=400)

    debit_result = await debitCurrency(userId, PRIVATE_SERVER_COST)
    if not debit_result["success"]:
        return web.json_response(debit_result, status=400)

    playerData = getPlayerData(userId)
    if not playerData:
        return web.json_response({"error": "user_not_found"}, status=404)

    current_time = time.time()
    expires_time = current_time + (SUBSCRIPTION_DAYS * 86400)  # 30 days

    playerData["private_server_active"] = True
    playerData["private_server_expires"] = expires_time
    await savePlayerData(userId, playerData)

    from vm_game_server_manager import spawn_game_server
    from config import SERVER_PUBLIC_IP

    master_vm_id = f"main-{SERVER_PUBLIC_IP}"

    from vm_lifecycle_manager import vm_registry, vm_registry_lock

    async with vm_registry_lock:
        if master_vm_id in vm_registry:
            master_vm = vm_registry[master_vm_id]
            server_count = len(master_vm.get("servers", {}))
            # use unique port based on userid, idk if its the best idea, uid 1000000 will be port 1001000!
            # TODO: we MUST change this ASAP!
            next_port = 10000 + userId
            server_uid = f"private_{userId}_{master_vm_id}"

            success = await spawn_game_server(server_uid, next_port, owner_id=userId)

            if success:
                return web.json_response({
                    "success": True,
                    "data": {
                        "cost": PRIVATE_SERVER_COST,
                        "new_balance": debit_result["data"]["newBalance"],
                        "expires": expires_time,
                        "server_uid": server_uid,
                        "port": next_port
                    }
                })

    return web.json_response({"error": "failed_to_create_private_server"}, status=500)

async def cancelPrivateServer(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    from player_data import getPlayerData, savePlayerData

    playerData = getPlayerData(userId)
    if not playerData:
        return web.json_response({"error": "user_not_found"}, status=404)

    if not playerData.get("private_server_active", False):
        return web.json_response({"error": "no_active_subscription"}, status=400)

    # Stop the private server
    from vm_lifecycle_manager import vm_registry, vm_registry_lock
    from vm_game_server_manager import stop_game_server
    from config import SERVER_PUBLIC_IP

    master_vm_id = f"main-{SERVER_PUBLIC_IP}"
    server_uid = f"private_{userId}_{master_vm_id}"

    async with vm_registry_lock:
        if master_vm_id in vm_registry:
            master_vm = vm_registry[master_vm_id]
            if server_uid in master_vm.get("servers", {}):
                await stop_game_server(server_uid, graceful=True)

    playerData["private_server_active"] = False
    playerData["private_server_expires"] = 0
    await savePlayerData(userId, playerData)

    return web.json_response({
        "success": True,
        "message": "Private server subscription cancelled"
    })

async def getPrivateServerStatus(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    userId = getUserIdFromToken(token)
    if not userId:
        return web.json_response({"error": "user_not_found"}, status=404)

    from player_data import getPlayerData
    import time

    playerData = getPlayerData(userId)
    if not playerData:
        return web.json_response({"error": "user_not_found"}, status=404)

    active = playerData.get("private_server_active", False)
    expires = playerData.get("private_server_expires", 0)

    current_time = time.time()

    # check if subscription expired
    if active and expires < current_time:
        from player_data import savePlayerData
        playerData["private_server_active"] = False
        await savePlayerData(userId, playerData)
        active = False

    return web.json_response({
        "success": True,
        "data": {
            "active": active,
            "expires": expires if active else None,
            "days_remaining": int((expires - current_time) / 86400) if active and expires > current_time else 0
        }
    })

def addNewRoutes(webApp):
    webApp.add_routes([
        web.post("/friends/add", addFriendEndpoint),
        web.post("/friends/remove", removeFriendEndpoint),
        web.post("/friends/get", getFriendsEndpoint),
        web.post("/friends/send_request", sendFriendRequestEndpoint),
        web.post("/friends/get_requests", getFriendRequestsEndpoint),
        web.post("/friends/accept_request", acceptFriendRequestEndpoint),
        web.post("/friends/reject_request", rejectFriendRequestEndpoint),
        web.post("/friends/cancel_request", cancelFriendRequestEndpoint),
        web.post("/friends/join_server", joinFriendServer),

        web.post("/avatar/get_full", getFullAvatarEndpoint),
        web.post("/avatar/get_accessory", getAccessoryEndpoint),
        web.post("/avatar/buy_item", buyItemEndpoint),
        web.post("/avatar/equip", equipAccessoryEndpoint),
        web.post("/avatar/unequip", unequipAccessoryEndpoint),
        web.post("/avatar/list_market", listMarketItemsEndpoint),
        web.post("/avatar/get_user_accessories", getUserAccessoriesEndpoint),

        web.post("/currency/credit", creditCurrencyEndpoint),
        web.post("/currency/debit", debitCurrencyEndpoint),
        web.post("/currency/get", getCurrencyEndpoint),

        web.post("/player/get_pfp", getPfpEndpoint),
        web.post("/player/update_avatar", updateAvatarEndpoint),
        web.post("/player/get_profile", getPlayerProfileEndpoint),
        web.post("/player/set_server", setPlayerServerEndpoint),

        web.post("/account/change_username", changeUsername),
        web.post("/account/check_free_username", checkFreeUsername),
        web.post("/account/change_password", changePassword),

        web.post("/private_server/subscribe", subscribePrivateServer),
        web.post("/private_server/cancel", cancelPrivateServer),
        web.post("/private_server/status", getPrivateServerStatus),
    ])
