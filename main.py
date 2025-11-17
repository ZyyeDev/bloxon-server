import signal
import asyncio
import time
import uuid
import os
import json
import hashlib
import secrets
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from aiohttp import web
import aiohttp
from typing import Dict, Any, Optional, List
from database_manager import execute_query
import auth_utils
from api_extensions import addNewRoutes
from moderation.ModServer import moderationRun
from player_data import createPlayerData, getPlayerFullProfile
from config import (
    SERVER_PUBLIC_IP,
    BASE_PORT,
    GODOT_SERVER_BIN,
    DATASTORE_PASSWORD,
    DASHBOARD_PASSWORD,
    GOOGLE_PLAY_PACKAGE_NAME,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    VOLUME_PATH,
    CURRENT_SERVER_VERSION,
    BINARIES_DIR,
    VERSION_FILE,
    get_public_ip,
    get_local_ip,
    get_server_ip,
    generate_dashboard_password,
    get_current_binary_version,
    set_binary_version,
    DASHBOARD_CACHE_TTL,
    MAX_SERVERS_PER_VM,
    MAX_SERVERS_IN_MASTER
)
from game_database import (
    save_account, get_account_by_username, get_account_by_id,
    save_token, get_token, delete_old_tokens,
    save_datastore, get_datastore, delete_datastore, list_datastore_keys, delete_old_datastores,
    count_accounts, flush_write_buffer
)
from global_messages import (
    global_messages_queue,
    maintenance_mode,
    last_message_id,
    message_subscribers,
    subscriber_queues,
    subscribe_to_messages,
    unsubscribe_from_messages,
    broadcast_message,
    add_global_message,
    get_global_messages,
    get_latest_message_id,
    clear_old_messages,
    set_maintenance_mode,
    is_maintenance_mode,
    get_maintenance_status,
    broadcast_to_servers,
    send_message_to_server,
)
from payment_verification import verify_google_play_purchase, verify_ad_reward, get_currency_packages
from server_monitoring import get_system_stats
from vm_lifecycle_manager import (
    register_vm_heartbeat, request_new_vm, get_available_vm_for_server,
    get_vm_by_server_uid, vm_lifecycle_monitor, get_vm_stats,
    vm_registry, vm_registry_lock, create_vm
)
from player_save_tracker import save_tracker, save_tracker_monitor
from moderation_service import check_text_content, validate_username
import atexit
from vm_game_server_manager import spawn_game_server

shutdown_lock = threading.Lock()

serverList = {}
playerList = {}
blockedIps = {}

message_connections = {}

dashboard_cache = {"timestamp": 0, "data": None}

last_cleanup = 0
dashboard_sessions = {}

def emergencyShutdown():
    with shutdown_lock:
        try:
            asyncio.run(save_tracker.wait_for_all_saves(timeout=30.0))
            flush_write_buffer()
        except:
            pass

atexit.register(emergencyShutdown)

def checkRateLimit(clientIp):
    return auth_utils.checkRateLimit(clientIp)

def blockIp(clientIp, duration_minutes):
    blockedIps[clientIp] = time.time() + (duration_minutes * 60)

def validateToken(token):
    return auth_utils.validateToken(token)

def hashPassword(password):
    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    import base64
    return salt + ":" + base64.b64encode(password_hash).decode()

def verifyPassword(password, stored_hash):
    try:
        import base64
        salt, hash_part = stored_hash.split(":")
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return base64.b64encode(password_hash).decode() == hash_part
    except:
        return False

def generateToken():
    return secrets.token_urlsafe(32)

async def moderateText(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    text = requestData.get("text", "")

    if not text:
        return web.json_response({"error": "missing_text"}, status=400)

    result = check_text_content(text)

    return web.json_response({
        "success": True,
        "data": result
    })

# TODO: we must not use this!!!!!!!
# instead use registerUserWithCaptcha
# just keeping because im a lazyass to change the client too
async def registerUser(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "auth_rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except Exception as e:
        print(f"[REGISTER] Error parsing JSON: {e}")
        return web.json_response({"error": "invalid_json"}, status=400)

    username = requestData.get("username", "").strip()
    password = requestData.get("password", "")
    gender = requestData.get("gender", "").lower()
    # TODO: birthday should be implemented in the future
    #birthday = rerequestData.get("birthday", "")

    if not username or not password or gender not in ["male", "female", "none"]:
        print(f"[REGISTER] Invalid data")
        return web.json_response({"error": "invalid_data"}, status=400)

    validation = validate_username(username)
    if not validation["valid"]:
        return web.json_response({"error": validation["error"]}, status=400)

    if len(password) < 6:
        return web.json_response({"error": "password_too_short"}, status=400)

    try:
        existing = get_account_by_username(username)
        if existing:
            return web.json_response({"error": "username_taken"}, status=409)

        hashedPassword = hashPassword(password)

        token = generateToken()

        user_id = save_account(username, hashedPassword, gender)

        save_token(token, username)

        await createPlayerData(user_id, username)

        return web.json_response({
            "status": "registered",
            "token": token,
            "username": username,
            "user_id": user_id
        })

    except Exception as e:
        print(f"[REGISTER] EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({"error": "registration_failed", "details": str(e)}, status=500)

async def loginUser(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "auth_rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    username = requestData.get("username", "").strip()
    password = requestData.get("password", "")

    if not username or not password:
        return web.json_response({"error": "missing_credentials"}, status=400)

    user_data = get_account_by_username(username)
    if not user_data:
        return web.json_response({"error": "user_not_found"}, status=300)

    if not verifyPassword(password, user_data["password"]):
        return web.json_response({"error": "invalid_password"}, status=401)

    token = generateToken()
    save_token(token, username)

    return web.json_response({
        "status": "logged_in",
        "token": token,
        "username": username,
        "user_id": user_data["user_id"]
    })

async def vmHeartbeat(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    vm_id = requestData.get("vm_id")
    server_stats = requestData.get("servers", [])

    if not vm_id:
        return web.json_response({"error": "missing_vm_id"}, status=400)

    response = await register_vm_heartbeat(vm_id, server_stats)
    return web.json_response(response)

async def getMaintenanceStatus(httpRequest):
    status = get_maintenance_status()
    return web.json_response(status)

async def getGlobalMessages(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    since_id = requestData.get("since_id", 0)
    from global_messages import get_global_messages, get_latest_message_id
    messages = get_global_messages(since_id)

    return web.json_response({
        "success": True,
        "data": {
            "messages": messages,
            "latest_id": get_latest_message_id()
        }
    })

async def processPurchase(httpRequest):
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
    product_id = requestData.get("product_id")
    purchase_token = requestData.get("purchase_token")

    if not product_id or not purchase_token:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    try:
        result = await verify_google_play_purchase(user_id, product_id, purchase_token)
        return web.json_response(result)
    except Exception as e:
        print(f"Purchase error: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({"error": "internal_error", "details": str(e)}, status=500)

async def processAdReward(httpRequest):
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
    ad_network = requestData.get("ad_network", "admob")
    ad_unit_id = requestData.get("ad_unit_id")
    reward_amount = requestData.get("reward_amount", 10)

    if not ad_unit_id:
        return web.json_response({"error": "missing_ad_unit_id"}, status=400)

    try:
        result = await verify_ad_reward(user_id, ad_network, ad_unit_id, reward_amount)
        return web.json_response(result)
    except Exception as e:
        print(f"Ad reward error: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({"error": "internal_error", "details": str(e)}, status=500)

async def getCurrencyPackagesEndpoint(httpRequest):
    result = get_currency_packages()
    return web.json_response(result)

def verify_dashboard_session(session_token):
    if not session_token or session_token not in dashboard_sessions:
        return False

    session_data = dashboard_sessions[session_token]
    if time.time() - session_data["created"] > 3600:
        del dashboard_sessions[session_token]
        return False

    return True

async def dashboardLogin(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    password = requestData.get("password")

    if password == DASHBOARD_PASSWORD:
        session_token = secrets.token_urlsafe(32)
        dashboard_sessions[session_token] = {
            "created": time.time(),
            "ip": httpRequest.remote
        }
        return web.json_response({"success": True, "session_token": session_token})

    return web.json_response({"error": "invalid_password"}, status=401)

async def sendGlobalMessage(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    message_type = requestData.get("type")
    properties = requestData.get("properties", {})

    if not message_type:
        return web.json_response({"error": "missing_type"}, status=400)

    result = add_global_message(message_type, properties)
    return web.json_response(result)

async def setMaintenanceMode(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    enabled = requestData.get("enabled", False)
    message = requestData.get("message", "")

    result = set_maintenance_mode(enabled, message)
    return web.json_response(result)

async def getWeatherTypes(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    from game_database import get_weather_types
    weathers = get_weather_types()
    return web.json_response({"success": True, "data": weathers})

async def addWeatherType(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    weather_name = requestData.get("weather_name")
    if not weather_name:
        return web.json_response({"error": "missing_weather_name"}, status=400)

    from game_database import add_weather_type
    success = add_weather_type(weather_name)

    if success:
        return web.json_response({"success": True})
    else:
        return web.json_response({"error": "weather_exists"}, status=400)

async def removeWeatherType(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    weather_name = requestData.get("weather_name")
    if not weather_name:
        return web.json_response({"error": "missing_weather_name"}, status=400)

    from game_database import remove_weather_type
    success = remove_weather_type(weather_name)

    return web.json_response({"success": success})

async def getDashboardData(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        data = await httpRequest.text()
        if data:
            return web.json_response({"error": "invalid_json"}, status=400)
        requestData = {}

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    current_time = time.time()
    if dashboard_cache["data"] and (current_time - dashboard_cache["timestamp"]) < DASHBOARD_CACHE_TTL:
        return web.json_response(dashboard_cache["data"])

    vm_stats = get_vm_stats()
    system_stats = get_system_stats()

    rate_limit_data = []
    for ip in list(auth_utils.rateLimitDict.keys())[:100]:
        timestamps = auth_utils.rateLimitDict[ip]
        recent_requests = len(timestamps)
        if recent_requests > 0:
            rate_limit_data.append({
                "ip": ip,
                "requests": recent_requests,
                "blocked": ip in blockedIps,
                "block_expires": int(blockedIps[ip] - current_time) if ip in blockedIps else 0
            })

    rate_limit_data.sort(key=lambda x: x["requests"], reverse=True)

    from game_database import get_weather_types
    weather_types = get_weather_types()

    user_count = count_accounts()

    pending_saves = await save_tracker.get_pending_saves()

    result = {
        "stats": {
            "total_vms": vm_stats["total_vms"],
            "active_vms": vm_stats["active_vms"],
            "total_servers": vm_stats["total_servers"],
            "total_players": vm_stats["total_players"],
            "total_users": user_count,
            "pending_saves": len(pending_saves)
        },
        "vms": vm_stats["vms"],
        "rate_limits": rate_limit_data,
        "system": system_stats,
        "maintenance": is_maintenance_mode(),
        "weather_types": weather_types
    }

    dashboard_cache["timestamp"] = current_time
    dashboard_cache["data"] = result

    return web.json_response(result)

async def dashboardView(httpRequest):
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html = f.read()
    return web.Response(text=html, content_type="text/html")

async def cleanupTask():
    global last_cleanup
    while True:
        try:
            currentTime = time.time()
            if currentTime - last_cleanup > 60:
                delete_old_tokens(currentTime - 2592000)
                delete_old_datastores(currentTime - 86400)
                clear_old_messages(300)
                last_cleanup = currentTime
            await asyncio.sleep(10)
        except:
            await asyncio.sleep(10)

async def requestServer(httpRequest):
    if is_maintenance_mode():
        return web.json_response({"error": "maintenance_mode"}, status=503)

    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except Exception as e:
        print(f"Error parsing request: {e}")
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")
    if not token or not validateToken(token):
        return web.json_response({"error": "invalid_token"}, status=401)

    try:
        username = auth_utils.getUsernameFromToken(token)
        user_data = get_account_by_username(username)
        userId = user_data["user_id"] if user_data else None

        if not userId:
            return web.json_response({"error": "user_not_found"}, status=404)

        # check if user has an active private srv subscription
        from player_data import getPlayerData
        playerData = getPlayerData(userId)
        has_private_server = playerData.get("private_server_active", False)

        if has_private_server:
            # search a user private srv
            async with vm_registry_lock:
                for vm_id, vm_info in vm_registry.items():
                    if vm_info.get("status") != "active":
                        continue

                    servers = vm_info.get("servers", {})
                    for server_uid, server_data in servers.items():
                        if server_data.get("owner_id") == userId:
                            # found their srv
                            from player_data import setPlayerServer
                            await setPlayerServer(userId, server_uid)

                            vm_ip = vm_info.get("ip", SERVER_PUBLIC_IP)

                            return web.json_response({
                                "uid": server_uid,
                                "ip": vm_ip,
                                "port": server_data["port"],
                                "vm_id": vm_id,
                                "private": True
                            })

        async with vm_registry_lock:
            best_server = None
            best_player_count = 8

            for vm_id, vm_info in vm_registry.items():
                if vm_info.get("status") != "active":
                    continue

                servers = vm_info.get("servers", {})
                for server_uid, server_data in servers.items():
                    # skip private servers (obviously)
                    if server_data.get("owner_id") is not None:
                        continue

                    server_status = server_data.get("status", "unknown")
                    if server_status not in ["running", "starting"]:
                        continue

                    player_count = server_data.get("player_count", 0)

                    # leave 1 slot free so we don't accidentally hit 9 players if two people join at once
                    if player_count <= best_player_count-1:
                        if player_count < best_player_count:
                            best_player_count = player_count
                            vm_ip = vm_info.get("ip", SERVER_PUBLIC_IP)
                            best_server = {
                                "uid": server_uid,
                                "ip": vm_ip,
                                "port": server_data["port"],
                                "vm_id": vm_id,
                                "player_count": player_count
                            }

            if best_server:
                print(f"Found available server: {best_server['uid']} ({best_server['player_count']}/7 players)")

                from player_data import setPlayerServer
                await setPlayerServer(userId, best_server['uid'])

                return web.json_response({
                    "uid": best_server['uid'],
                    "ip": best_server['ip'],
                    "port": best_server['port'],
                    "vm_id": best_server['vm_id'],
                    "private": False
                })

        request_id = f"pending_{userId}_{int(time.time())}"

        master_vm_id = f"main-{SERVER_PUBLIC_IP}"
        async with vm_registry_lock:
            if master_vm_id in vm_registry:
                master_vm = vm_registry[master_vm_id]
                master_server_count = len(master_vm.get("servers", {}))


                if master_server_count < MAX_SERVERS_IN_MASTER:
                    next_port = 9000 + master_server_count
                    server_uid = f"{master_vm_id}-{next_port}"

                    print(f"Spawning new server on MASTER VM at port {next_port} (currently {master_server_count}/{MAX_SERVERS_IN_MASTER})")

                    success = await spawn_game_server(server_uid, next_port)

                    if success:
                        await asyncio.sleep(3)

                        from player_data import setPlayerServer
                        await setPlayerServer(userId, server_uid)

                        return web.json_response({
                            "uid": server_uid,
                            "ip": SERVER_PUBLIC_IP,
                            "port": next_port,
                            "vm_id": master_vm_id,
                            "private": False
                        })

        # try remote VMs
        async with vm_registry_lock:
            for vm_id, vm_info in vm_registry.items():
                if vm_id == master_vm_id:
                    continue

                if vm_info.get("status") != "active":
                    continue

                server_count = len(vm_info.get("servers", {}))

                if server_count < MAX_SERVERS_PER_VM:
                    vm_ip = vm_info.get("ip")
                    next_port = 9000 + server_count
                    server_uid = f"{vm_id}-{next_port}"

                    print(f"Requesting new server spawn on REMOTE VM {vm_id[:8]} at port {next_port}")

                    spawn_success = await request_vm_spawn_server(vm_ip, server_uid, next_port)

                    if spawn_success:
                        await asyncio.sleep(3)

                        from player_data import setPlayerServer
                        await setPlayerServer(userId, server_uid)

                        return web.json_response({
                            "uid": server_uid,
                            "ip": vm_ip,
                            "port": next_port,
                            "vm_id": vm_id,
                            "private": False
                        })

        # create new VM
        master_url = f"http://{SERVER_PUBLIC_IP}:{BASE_PORT}"
        print(f"creating new VM...")

        loop = asyncio.get_event_loop()
        vm_data = await loop.run_in_executor(None, lambda: request_new_vm_sync(master_url))

        if vm_data:
            vm_id = vm_data["vm_id"]
            vm_ip = vm_data.get("ip")

            print(f"Remote VM created: {vm_id}, IP: {vm_ip}")
            print(f"Waiting for initial Godot server to start...")

            max_wait = 90
            waited = 0
            server_ready = False

            while waited < max_wait:
                await asyncio.sleep(5)
                waited += 5

                async with vm_registry_lock:
                    vm_info = vm_registry.get(vm_id)

                if vm_info and len(vm_info.get("servers", {})) > 0:
                    servers = vm_info.get("servers", {})
                    first_server = list(servers.values())[0]
                    first_server_uid = list(servers.keys())[0]

                    print(f"Godot server ready!! UID: {first_server_uid}, Port: {first_server['port']}")
                    server_ready = True

                    from player_data import setPlayerServer
                    await setPlayerServer(userId, first_server_uid)

                    return web.json_response({
                        "uid": first_server_uid,
                        "ip": vm_ip,
                        "port": first_server["port"],
                        "vm_id": vm_id,
                        "private": False
                    })

                if waited % 15 == 0:
                    print(f"Still waiting for Godot server... ({waited}s)")

            if not server_ready:
                print(f"Timeout waiting for Godot server")
                return web.json_response({"error": "timeout"}, status=503)
        else:
            return web.json_response({"error": "failed_to_create_vm"}, status=503)

    except Exception as e:
        print(f"ERROR in requestServer: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({"error": "internal_error", "message": str(e)}, status=500)

def request_new_vm_sync(master_url: str) -> Optional[Dict]:
    vm_id = str(uuid.uuid4())
    print(f"Creating new remote VM: {vm_id}")

    vm_data = create_vm(vm_id, master_url)

    if vm_data:
        vm_registry[vm_id] = {
            "vm_id": vm_id,
            "server_id": vm_data.get("server_id"),
            "ip": vm_data.get("ip"),
            "last_heartbeat": time.time(),
            "servers": {},
            "total_players": 0,
            "status": "provisioning",
            "created": vm_data.get("created", time.time()),
            "is_master": False
        }

        print(f"Remote VM registered: {vm_id} (IP: {vm_data.get('ip')})")
        return vm_registry[vm_id]

    return None

async def cleanup_empty_master_servers():
    while True:
        try:
            await asyncio.sleep(30)

            master_vm_id = f"main-{SERVER_PUBLIC_IP}"
            async with vm_registry_lock:
                if master_vm_id not in vm_registry:
                    continue

                master_vm = vm_registry[master_vm_id]
                servers = master_vm.get("servers", {})
                current_time = time.time()

                servers_to_remove = []

                for server_uid, server_data in list(servers.items()):
                    # private servers should also be shut down
                    #if server_data.get("private", False):
                    #    continue

                    last_heartbeat = server_data.get("last_heartbeat", 0)

                    if current_time - last_heartbeat > 120:
                        print(f"Removing stale server {server_uid} from VM registry (no heartbeat for 120s)")
                        servers_to_remove.append(server_uid)
                        continue

                    player_count = server_data.get("player_count", 0)

                    if player_count == 0:
                        if "empty_since" not in server_data:
                            server_data["empty_since"] = current_time
                            print(f"Master server {server_uid} is now empty")
                        elif current_time - server_data["empty_since"] > 15: # This must be the same as in vm_lifecycle_manager, just keep like this for now
                            print(f"Shutting down empty master server: {server_uid}")
                            servers_to_remove.append(server_uid)
                    else:
                        if "empty_since" in server_data:
                            del server_data["empty_since"]

            for server_uid in servers_to_remove:
                try:
                    from vm_game_server_manager import stop_game_server
                    await stop_game_server(server_uid, graceful=True)
                    print(f"Successfully stopped server {server_uid}")
                except Exception as e:
                    print(f"Error stopping server {server_uid}: {e}")

                async with vm_registry_lock:
                    if master_vm_id in vm_registry:
                        servers = vm_registry[master_vm_id].get("servers", {})
                        if server_uid in servers:
                            del servers[server_uid]

                query = "UPDATE player_data SET server_id = NULL WHERE server_id = ?"
                execute_query(query, (server_uid,))

        except Exception as e:
            print(f"Error in cleanup_empty_master_servers: {e}")
            import traceback
            traceback.print_exc()

async def request_vm_spawn_server(vm_ip: str, server_uid: str, port: int):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://{vm_ip}:8081/spawn_server",
                json={
                    "server_uid": server_uid,
                    "port": port
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    print(f"Successfully requested server spawn on {vm_ip}:{port}")
                    return True
                else:
                    text = await response.text()
                    print(f"Failed to spawn server on {vm_ip}: {response.status} - {text}")
                    return False
    except Exception as e:
        print(f"Error contacting VM {vm_ip}: {e}")
        return False

async def heartbeatClient(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"status": "alive"})
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"status": "alive"})
    token = requestData.get("token")
    if not token:
        return web.json_response({"status": "alive"})
    if not validateToken(token):
        return web.json_response({"status": "alive"})
    username = auth_utils.getUsernameFromToken(token)
    if username in playerList:
        playerList[username]["last"] = time.time()
    return web.json_response({"status": "alive"})

async def validateTokenEndpoint(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except Exception as e:
        return web.json_response({"error": "invalid_json"}, status=400)

    token = requestData.get("token")

    if not token:
        return web.json_response({"error": "missing_token"}, status=400)

    try:
        if not validateToken(token):
            return web.json_response({"error": "invalid_token"}, status=401)

        username = auth_utils.getUsernameFromToken(token)

        user_data = get_account_by_username(username)

        if not user_data:
            return web.json_response({"error": "user_not_found"}, status=404)

        token_data = get_token(token)

        if not token_data:
            return web.json_response({"error": "token_not_found"}, status=404)

        return web.json_response({
            "status": "valid",
            "username": username,
            "user_id": user_data["user_id"],
            "expires_in": int(2592000 - (time.time() - token_data["created"]))
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": "internal_error", "details": str(e)}, status=500)

async def getUserById(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    user_id = requestData.get("user_id")

    if not user_id:
        return web.json_response({"error": "missing_user_id"}, status=400)

    user_data = get_account_by_id(user_id)

    if user_data:
        return web.json_response({
            "username": user_data["username"],
            "user_id": user_data["user_id"],
            "gender": user_data["gender"],
            "created": user_data["created"]
        })

    return web.json_response({"error": "user_not_found"}, status=404)

async def searchUsers(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    search_query = requestData.get("query", "").strip().lower()
    limit = requestData.get("limit", 20)

    if not search_query:
        return web.json_response({"error": "missing_query"}, status=400)

    if limit > 50:
        limit = 50

    query = "SELECT user_id, username FROM accounts WHERE LOWER(username) LIKE ? LIMIT ?"
    results = execute_query(query, (f"%{search_query}%", limit), fetch_all=True)

    users = [{"user_id": row[0], "username": row[1]} for row in results] if results else []

    return web.json_response({"users": users})

async def setDatastore(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    allowed_ips = ["127.0.0.1", "::1", SERVER_PUBLIC_IP]
    if clientIp not in allowed_ips:
        return web.json_response({"error": "unauthorized_ip"}, status=403)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    key = requestData.get("key")
    value = requestData.get("value")
    accessKey = requestData.get("access_key")

    if not key or not accessKey:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    if accessKey != DATASTORE_PASSWORD:
        return web.json_response({"error": "invalid_access_key"}, status=403)

    datastoreKey = f"server:{key}"

    if isinstance(value, (dict, list)):
        value_str = json.dumps(value)
    else:
        value_str = str(value) if value is not None else ""

    save_datastore(datastoreKey, value_str)

    return web.json_response({"status": "success", "key": key})

async def getDatastore(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    key = requestData.get("key")
    accessKey = requestData.get("access_key")

    if not key or not accessKey:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    if accessKey != DATASTORE_PASSWORD:
        return web.json_response({"error": "invalid_access_key"}, status=403)

    datastoreKey = f"server:{key}"

    result = get_datastore(datastoreKey)

    if result:
        value = result["value"]
        try:
            value = json.loads(value)
        except:
            pass

        return web.json_response({
            "key": key,
            "value": value,
            "timestamp": result["timestamp"]
        })

    return web.json_response({"error": "key_not_found"}, status=404)

async def removeDatastore(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    allowed_ips = ["127.0.0.1", "::1", SERVER_PUBLIC_IP]
    if clientIp not in allowed_ips:
        return web.json_response({"error": "unauthorized_ip"}, status=403)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    key = requestData.get("key")
    accessKey = requestData.get("access_key")

    if not key or not accessKey:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    if accessKey != DATASTORE_PASSWORD:
        return web.json_response({"error": "invalid_access_key"}, status=403)

    datastoreKey = f"server:{key}"

    delete_datastore(datastoreKey)

    return web.json_response({"status": "removed", "key": key})

async def listDatastoreKeys(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    accessKey = requestData.get("access_key")

    if not accessKey:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    if accessKey != DATASTORE_PASSWORD:
        return web.json_response({"error": "invalid_access_key"}, status=403)

    results = list_datastore_keys("server:")

    serverKeys = []
    for result in results:
        key = result["key"][7:]
        serverKeys.append({
            "key": key,
            "timestamp": result["timestamp"]
        })

    return web.json_response({"keys": serverKeys})

async def listAllAccessories(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    from avatar_service import listMarketItems
    result = listMarketItems(pagination={"page": 1, "limit": 1000})
    return web.json_response(result)

async def deleteAccessoryEndpoint(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    accessory_id = requestData.get("accessory_id")
    if not accessory_id:
        return web.json_response({"error": "missing_accessory_id"}, status=400)

    from avatar_service import deleteAccessory
    result = deleteAccessory(accessory_id)
    return web.json_response(result)

async def addAccessoryEndpoint(httpRequest):
    try:
        session_token = None
        fields = {}
        files = {}
        filenames = {}

        reader = await httpRequest.multipart()
        async for field in reader:
            if field.name == "session_token":
                session_token = await field.text()
            elif field.name in ["name", "type", "price", "equip_slot"]:
                fields[field.name] = await field.text()
            elif field.name in ["model", "texture", "mtl", "icon"]:
                files[field.name] = await field.read()
                filenames[field.name] = field.filename

        if not session_token or not verify_dashboard_session(session_token):
            return web.json_response({"error": "unauthorized"}, status=401)

        if not all(k in fields for k in ["name", "type", "price", "equip_slot"]):
            return web.json_response({"error": "missing_required_fields"}, status=400)

        if "model" not in files:
            return web.json_response({"error": "model_file_required"}, status=400)

        try:
            price = int(fields["price"])
        except:
            return web.json_response({"error": "invalid_price"}, status=400)

        from avatar_service import addAccessoryFromDashboard

        result = addAccessoryFromDashboard(
            name=fields["name"],
            accessory_type=fields["type"],
            price=price,
            equip_slot=fields["equip_slot"],
            model_data=files["model"],
            texture_data=files.get("texture"),
            mtl_data=files.get("mtl"),
            icon_data=files.get("icon"),
            model_filename=filenames.get("model"),
            texture_filename=filenames.get("texture"),
            mtl_filename=filenames.get("mtl")
        )

        return web.json_response(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=400)
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    access_key = requestData.get("access_key")
    user_id = requestData.get("user_id")
    amount = requestData.get("amount")

    if not access_key or not user_id or not amount:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    if access_key != DATASTORE_PASSWORD:
        return web.json_response({"error": "invalid_access_key"}, status=403)

    try:
        amount = int(amount)
        user_id = int(user_id)
    except:
        return web.json_response({"error": "invalid_amount_or_user_id"}, status=400)

    if amount <= 0:
        return web.json_response({"error": "amount_must_be_positive"}, status=400)

    from currency_system import creditCurrency
    result = await creditCurrency(user_id, amount)

    return web.json_response(result)

async def generateCaptcha(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    from captcha_system import generate_puzzle_captcha
    captcha_id, image_data = generate_puzzle_captcha()

    return web.json_response({
        "success": True,
        "captcha_id": captcha_id,
        "image": image_data
    })

async def verifyCaptcha(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    captcha_id = requestData.get("captcha_id")
    answer = requestData.get("answer")

    if not captcha_id or answer is None:
        return web.json_response({"error": "missing_fields"}, status=400)

    from captcha_system import verify_captcha
    success, message = verify_captcha(captcha_id, answer)

    return web.json_response({
        "success": success,
        "message": message
    })

async def registerUserWithCaptcha(httpRequest):
    clientIp = httpRequest.remote
    if not checkRateLimit(clientIp):
        return web.json_response({"error": "auth_rate_limit_exceeded"}, status=429)

    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    username = requestData.get("username", "").strip()
    password = requestData.get("password", "")
    gender = requestData.get("gender", "").lower()
    # TODO: birthday should be implemented in the future
    #birthday = rerequestData.get("birthday", "")
    captcha_id = requestData.get("captcha_id")
    captcha_answer = requestData.get("captcha_answer")

    if not username or not password or gender not in ["male", "female", "none"]:
        return web.json_response({"error": "invalid_data"}, status=400)

    validation = validate_username(username)
    if not validation["valid"]:
        return web.json_response({"error": validation["error"]}, status=400)

    if len(password) < 6:
        return web.json_response({"error": "password_too_short"}, status=400)

    from captcha_system import verify_captcha, is_first_account_from_ip, mark_ip_used

    if not is_first_account_from_ip(clientIp):
        success, message = verify_captcha(captcha_id, captcha_answer)
        if not success:
            return web.json_response({"error": "captcha_failed", "message": message}, status=400)

    existing = get_account_by_username(username)
    if existing:
        return web.json_response({"error": "username_taken"}, status=409)

    hashedPassword = hashPassword(password)
    token = generateToken()

    user_id = save_account(username, hashedPassword, gender)

    save_token(token, username)

    createPlayerData(user_id, username)
    mark_ip_used(clientIp)

    return web.json_response({
        "status": "registered",
        "token": token,
        "username": username,
        "user_id": user_id
    })

async def websocket_messages(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    connection_id = str(uuid.uuid4())
    message_connections[connection_id] = ws

    queue = await subscribe_to_messages(connection_id)

    receive_task = None
    queue_task = None

    try:
        receive_task = asyncio.create_task(ws.receive())
        queue_task = asyncio.create_task(queue.get())

        while not ws.closed:
            done, pending = await asyncio.wait(
                [receive_task, queue_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            if receive_task in done:
                try:
                    msg = receive_task.result()
                    if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                except Exception:
                    break
                receive_task = asyncio.create_task(ws.receive())

            if queue_task in done:
                try:
                    message = queue_task.result()
                    if not ws.closed:
                        await ws.send_json(message)
                except Exception:
                    break
                queue_task = asyncio.create_task(queue.get())

    except Exception as e:
        pass
    finally:
        if receive_task and not receive_task.done():
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass

        if queue_task and not queue_task.done():
            queue_task.cancel()
            try:
                await queue_task
            except asyncio.CancelledError:
                pass

        unsubscribe_from_messages(connection_id)
        if connection_id in message_connections:
            del message_connections[connection_id]

        if not ws.closed:
            await ws.close()

    return ws

async def getPaymentHistory(httpRequest):
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

    query = """SELECT payment_id, purchase_token, product_id, amount, currency_awarded, verified, created
               FROM payments WHERE user_id = ? ORDER BY created DESC LIMIT 100"""
    payments = execute_query(query, (user_id,), fetch_all=True)

    result = []
    for p in payments:
        result.append({
            "payment_id": p[0],
            "purchase_token": p[1],
            "product_id": p[2],
            "amount": p[3],
            "currency_awarded": p[4],
            "verified": bool(p[5]),
            "created": p[6]
        })

    return web.json_response({"success": True, "data": result})

async def vmStartupLog(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    access_key = requestData.get("access_key")
    if access_key != DATASTORE_PASSWORD:
        return web.json_response({"error": "unauthorized"}, status=403)

    vm_id = requestData.get("vm_id")
    message = requestData.get("message")

    print(f"[VM {vm_id[:8]}] {message}")

    return web.json_response({"success": True})

# I was bored and i did this idk
async def middleware404(app, handler):
    async def middleware_handler(request):
        try:
            response = await handler(request)
            if response.status in [404]:
                with open("404.html", "r") as f:
                    return web.Response(text=f.read(), content_type="text/html", status=response.status)
            return response
        except web.HTTPException as ex:
            if ex.status in [404]:
                with open("404.html", "r") as f:
                    return web.Response(text=f.read(), content_type="text/html", status=ex.status)
            raise
        except Exception:
            return web.Response(status=500, text="Internal Server Error")
    return middleware_handler

async def adminCreditCurrency(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    session_token = requestData.get("session_token")
    if not verify_dashboard_session(session_token):
        return web.json_response({"error": "unauthorized"}, status=401)

    user_id = requestData.get("user_id")
    amount = requestData.get("amount")

    if not user_id or not amount:
        return web.json_response({"error": "missing_required_fields"}, status=400)

    try:
        amount = int(amount)
        user_id = int(user_id)
    except:
        return web.json_response({"error": "invalid_amount_or_user_id"}, status=400)

    if amount <= 0:
        return web.json_response({"error": "amount_must_be_positive"}, status=400)

    from currency_system import creditCurrency
    result = await creditCurrency(user_id, amount)

    return web.json_response(result)

async def updateAccessoryEndpoint(httpRequest):
    try:
        session_token = None
        accessory_id = None
        fields = {}
        files = {}
        filenames = {}

        reader = await httpRequest.multipart()
        async for field in reader:
            if field.name == "session_token":
                session_token = await field.text()
            elif field.name == "accessory_id":
                accessory_id = await field.text()
            elif field.name in ["name", "type", "price", "equip_slot"]:
                fields[field.name] = await field.text()
            elif field.name in ["model", "texture", "mtl", "icon"]:
                data = await field.read()
                if data:
                    files[field.name] = data
                    filenames[field.name] = field.filename

        if not session_token or not verify_dashboard_session(session_token):
            return web.json_response({"error": "unauthorized"}, status=401)

        if not accessory_id:
            return web.json_response({"error": "missing_accessory_id"}, status=400)

        try:
            accessory_id = int(accessory_id)
        except:
            return web.json_response({"error": "invalid_accessory_id"}, status=400)

        price = None
        if "price" in fields:
            try:
                price = int(fields["price"])
            except:
                return web.json_response({"error": "invalid_price"}, status=400)

        from avatar_service import updateAccessoryFromDashboard

        result = updateAccessoryFromDashboard(
            accessory_id=accessory_id,
            name=fields.get("name"),
            accessory_type=fields.get("type"),
            price=price,
            equip_slot=fields.get("equip_slot"),
            model_data=files.get("model"),
            texture_data=files.get("texture"),
            mtl_data=files.get("mtl"),
            icon_data=files.get("icon"),
            model_filename=filenames.get("model"),
            texture_filename=filenames.get("texture"),
            mtl_filename=filenames.get("mtl")
        )

        return web.json_response(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=400)

async def getServerVersion(httpRequest):
    version = get_current_binary_version()
    return web.json_response({
        "success": True,
        "version": version,
        "required_version": CURRENT_SERVER_VERSION
    })

async def checkClientVersion(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)

    client_version = requestData.get("version", "")

    if client_version != CURRENT_SERVER_VERSION:
        return web.json_response({
            "success": False,
            "update_required": True,
            "current_version": CURRENT_SERVER_VERSION,
            "client_version": client_version
        }, status=426)

    return web.json_response({
        "success": True,
        "update_required": False
    })

async def uploadBinaryEndpoint(httpRequest):
    try:
        session_token = None
        version = None
        binary_data = None

        reader = await httpRequest.multipart()
        async for field in reader:
            if field.name == "session_token":
                session_token = await field.text()
            elif field.name == "version":
                version = await field.text()
            elif field.name == "binary":
                binary_data = await field.read()

        if not session_token or not verify_dashboard_session(session_token):
            return web.json_response({"error": "unauthorized"}, status=401)

        if not version or not binary_data:
            return web.json_response({"error": "missing_required_fields"}, status=400)

        os.makedirs(BINARIES_DIR, exist_ok=True)

        binary_path = os.path.join(BINARIES_DIR, "server.x86_64")
        with open(binary_path, 'wb') as f:
            f.write(binary_data)

        os.chmod(binary_path, 0o755)

        set_binary_version(version)

        return web.json_response({
            "success": True,
            "version": version,
            "message": "Binary uploaded successfully"
        })

    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def downloadBinary(httpRequest):
    try:
        requestData = await httpRequest.json()
    except:
        print("Download binary: Invalid JSON")
        return web.json_response({"error": "invalid_json"}, status=400)

    access_key = requestData.get("access_key")
    print(f"Binary download request with access_key: {access_key[:10]}... from {httpRequest.remote}")

    if access_key != DATASTORE_PASSWORD:
        print(f"Unauthorized binary download attempt from {httpRequest.remote}")
        return web.json_response({"error": "unauthorized"}, status=403)

    binary_path = os.path.join(BINARIES_DIR, "server.x86_64")
    print(f"Looking for binary at: {binary_path}, exists: {os.path.exists(binary_path)}")

    if not os.path.exists(binary_path):
        print(f"Binary not found at {binary_path}")
        return web.json_response({"error": "binary_not_found"}, status=404)

    file_size = os.path.getsize(binary_path)
    print(f"Serving binary: {binary_path} ({file_size} bytes) to {httpRequest.remote}")

    return web.FileResponse(binary_path)

def shutdownHandler(signalNum, frameObj):
    with shutdown_lock:
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(save_tracker.wait_for_all_saves(timeout=30.0))
            flush_write_buffer()
        except:
            pass
    os._exit(0)

signal.signal(signal.SIGINT, shutdownHandler)
signal.signal(signal.SIGTERM, shutdownHandler)

async def startApp():
    os.makedirs(os.path.join(VOLUME_PATH, "pfps"), exist_ok=True)
    os.makedirs(os.path.join(VOLUME_PATH, "models"), exist_ok=True)
    os.makedirs(os.path.join(VOLUME_PATH, "accessories"), exist_ok=True)
    os.makedirs(os.path.join(VOLUME_PATH, "icons"), exist_ok=True)

    master_vm_id = f"main-{SERVER_PUBLIC_IP}"
    async with vm_registry_lock:
        vm_registry[master_vm_id] = {
            "vm_id": master_vm_id,
            "ip": SERVER_PUBLIC_IP,
            "last_heartbeat": time.time(),
            "servers": {},
            "total_players": 0,
            "status": "active",
            "created": time.time(),
            "is_master": True
        }
    print(f"Master VM registered: {master_vm_id}")

    async def error_middleware(app, handler):
        async def middleware_handler(request):
            try:
                return await handler(request)
            except aiohttp.http_exceptions.BadStatusLine:
                return web.Response(status=400, text="Bad Request")
            except Exception as e:
                return web.Response(status=500, text="Internal Server Error")
        return middleware_handler

    webApp = web.Application(middlewares=[error_middleware,middleware404])
    webApp.add_routes([
        web.post("/auth/register", registerUser),
        web.post("/auth/login", loginUser),
        web.post("/auth/validate", validateTokenEndpoint),
        web.post("/auth/register_with_captcha", registerUserWithCaptcha),

        web.post("/datastore/set", setDatastore),
        web.post("/datastore/get", getDatastore),
        web.post("/datastore/remove", removeDatastore),
        web.post("/datastore/list_keys", listDatastoreKeys),

        web.post("/heartbeat_client", heartbeatClient),
        web.post("/vm/heartbeat", vmHeartbeat),

        web.post("/users/get_by_id", getUserById),
        web.post("/users/search", searchUsers),

        web.get("/maintenance_status", getMaintenanceStatus),
        web.post("/global_messages", getGlobalMessages),
        web.get("/ws/messages", websocket_messages),
        web.post("/request_server", requestServer),

        web.post("/payments/purchase", processPurchase),
        web.post("/payments/ad_reward", processAdReward),
        web.get("/payments/packages", getCurrencyPackagesEndpoint),
        web.post("/payments/history", getPaymentHistory),

        web.get("/dashboard", dashboardView),
        web.post("/api/dashboard", getDashboardData),
        web.post("/dashboard/login", dashboardLogin),
        web.post("/dashboard/send_message", sendGlobalMessage),
        web.post("/dashboard/set_maintenance", setMaintenanceMode),
        web.post("/dashboard/weather/list", getWeatherTypes),
        web.post("/dashboard/weather/add", addWeatherType),
        web.post("/dashboard/weather/remove", removeWeatherType),
        web.post("/dashboard/accessories/update", updateAccessoryEndpoint),
        web.post("/dashboard/credit_currency", adminCreditCurrency),
        web.post("/dashboard/accessories/list", listAllAccessories),
        web.post("/dashboard/accessories/add", addAccessoryEndpoint),
        web.post("/dashboard/accessories/delete", deleteAccessoryEndpoint),
        web.post("/dashboard/upload_binary", uploadBinaryEndpoint),
        web.post("/download_binary", downloadBinary),

        web.post("/captcha/generate", generateCaptcha),
        web.post("/captcha/verify", verifyCaptcha),

        web.post("/moderation", moderationRun),

        web.post("/vm/startup_log", vmStartupLog),

        web.get("/version", getServerVersion),
        web.post("/check_version", checkClientVersion),
    ])

    addNewRoutes(webApp)

    webApp.router.add_static("/pfps/", os.path.join(VOLUME_PATH, "pfps"))
    webApp.router.add_static("/models/", os.path.join(VOLUME_PATH, "models"))
    webApp.router.add_static("/accessories/", os.path.join(VOLUME_PATH, "accessories"))
    webApp.router.add_static("/icons/", os.path.join(VOLUME_PATH, "icons"))
    webApp.router.add_static("/public/", "./public")

    asyncio.create_task(cleanupTask())
    asyncio.create_task(vm_lifecycle_monitor())
    asyncio.create_task(save_tracker_monitor())
    asyncio.create_task(cleanup_empty_master_servers())
    return webApp

if __name__ == "__main__":
    os.makedirs("pfps", exist_ok=True)
    os.makedirs("models", exist_ok=True)
    os.makedirs("accessories", exist_ok=True)
    os.makedirs("icons", exist_ok=True)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_server():
        app = await startApp()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()

        print(f"Server started on {get_public_ip()}:8080")

        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            print("Shutting down...")
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await runner.cleanup()

    try:
        loop.run_until_complete(run_server())
    except KeyboardInterrupt:
        print("Shutdown complete")
    except Exception as e:
        print(f"Server error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except:
            pass
        loop.close()
