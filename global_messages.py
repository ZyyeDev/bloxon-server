import json
import time
import asyncio
from typing import Dict, Any, List
from collections import defaultdict
from config import SERVER_PUBLIC_IP, BASE_PORT
import requests

global_messages_queue = []
maintenance_mode = False
last_message_id = 0

message_subscribers = defaultdict(set)
subscriber_queues = {}

async def subscribe_to_messages(subscriber_id: str):
    if subscriber_id not in subscriber_queues:
        subscriber_queues[subscriber_id] = asyncio.Queue()

    message_subscribers["global"].add(subscriber_id)

    return subscriber_queues[subscriber_id]

def unsubscribe_from_messages(subscriber_id: str):
    if subscriber_id in message_subscribers["global"]:
        message_subscribers["global"].remove(subscriber_id)

    if subscriber_id in subscriber_queues:
        queue = subscriber_queues[subscriber_id]
        while not queue.empty():
            try:
                queue.get_nowait()
            except:
                pass
        del subscriber_queues[subscriber_id]

async def broadcast_message(message: Dict[str, Any]):
    dead_subscribers = []
    for subscriber_id in list(message_subscribers["global"]):
        if subscriber_id in subscriber_queues:
            try:
                subscriber_queues[subscriber_id].put_nowait(message)
            except asyncio.QueueFull:
                dead_subscribers.append(subscriber_id)
            except:
                dead_subscribers.append(subscriber_id)

    for subscriber_id in dead_subscribers:
        unsubscribe_from_messages(subscriber_id)

def add_global_message(message_type: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    global last_message_id, global_messages_queue

    last_message_id += 1
    message = {
        "id": last_message_id,
        "type": message_type,
        "properties": properties,
        "timestamp": time.time()
    }

    global_messages_queue.append(message)

    if len(global_messages_queue) > 100:
        global_messages_queue = global_messages_queue[-100:]

    asyncio.create_task(broadcast_message(message))

    return {"success": True, "data": {"message_id": last_message_id, "message": message}}

def get_global_messages(since_id: int = 0) -> List[Dict[str, Any]]:
    return [msg for msg in global_messages_queue if msg["id"] > since_id]

def get_latest_message_id() -> int:
    return last_message_id

def clear_old_messages(max_age_seconds: int = 300):
    global global_messages_queue
    current_time = time.time()
    global_messages_queue = [
        msg for msg in global_messages_queue
        if current_time - msg["timestamp"] < max_age_seconds
    ]

def set_maintenance_mode(enabled: bool, message: str = "") -> Dict[str, Any]:
    global maintenance_mode
    maintenance_mode = enabled

    if enabled:
        add_global_message("Maintenance", {
            "enabled": True,
            "message": message or "Server is entering maintenance mode"
        })
        asyncio.create_task(force_shutdown_all_servers())
    else:
        add_global_message("Maintenance", {
            "enabled": False,
            "message": "Server is back online"
        })

    return {"success": True, "data": {"maintenance_mode": maintenance_mode}}

async def force_shutdown_all_servers():
    await asyncio.sleep(30)

    from vm_lifecycle_manager import vm_registry, vm_registry_lock, shutdown_vm_gracefully
    from vm_game_server_manager import stop_game_server, game_server_processes
    from config import SERVER_PUBLIC_IP

    master_vm_id = f"main-{SERVER_PUBLIC_IP}"
    for server_uid in list(game_server_processes.keys()):
        try:
            print(f"Force stopping server: {server_uid}")
            await stop_game_server(server_uid, graceful=False)
        except Exception as e:
            print(f"Error stopping server {server_uid}: {e}")

    async with vm_registry_lock:
        vms_to_shutdown = []
        for vm_id, vm_info in vm_registry.items():
            if vm_id != master_vm_id and vm_info.get("status") == "active":
                vms_to_shutdown.append((vm_id, vm_info))

    for vm_id, vm_info in vms_to_shutdown:
        server_id = vm_info.get("server_id")
        vm_ip = vm_info.get("ip")
        if server_id and vm_ip:
            try:
                print(f"Force shutting down VM: {vm_id[:8]}")
                await shutdown_vm_gracefully(vm_ip, server_id)
            except Exception as e:
                print(f"Error shutting down VM {vm_id[:8]}: {e}")

def is_maintenance_mode() -> bool:
    return maintenance_mode

def get_maintenance_status() -> Dict[str, Any]:
    return {
        "maintenance": maintenance_mode,
        "status": "maintenance" if maintenance_mode else "active"
    }

async def broadcast_to_servers(message: Dict[str, Any], server_list: Dict):
    tasks = []
    for server_uid, server_info in server_list.items():
        task = send_message_to_server(server_info["ip"], server_info["port"], message)
        tasks.append(task)

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

async def send_message_to_server(ip: str, port: int, message: Dict[str, Any]):
    try:
        url = f"http://{ip}:{port}/global_message"
        requests.post(url, json=message, timeout=1)
    except:
        pass
