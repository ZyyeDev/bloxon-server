import os
import time
import uuid
import asyncio
import requests
from typing import Dict, List, Optional
from config import DATASTORE_PASSWORD

HETZNER_API_TOKEN = os.environ.get("HETZNER_API_TOKEN", "")
HETZNER_API_BASE = "https://api.hetzner.cloud/v1"
VM_IMAGE = os.environ.get("HETZNER_VM_IMAGE", "ubuntu-22.04")
VM_TYPE = os.environ.get("HETZNER_VM_TYPE", "cx23")
VM_LOCATION = os.environ.get("HETZNER_VM_LOCATION", "nbg1")
MAX_SERVERS_PER_VM = int(os.environ.get("MAX_SERVERS_PER_VM", "6"))
INACTIVE_TIME = 15 # just 15 secs to shutdown server instance if no plrs in, we do not need more

vm_registry = {}
vm_registry_lock = asyncio.Lock()

def get_vm_manager_script():
    try:
        with open("vm_game_server_manager.py", "r") as f:
            return f.read()
    except:
        return ""

def get_config_script():
    try:
        with open("config.py", "r") as f:
            config_content = f.read()

        lines = config_content.split("\n")
        filtered_lines = []

        for line in lines:
            if line.strip().startswith("SERVER_PUBLIC_IP"):
                continue
            filtered_lines.append(line)

        return "\n".join(filtered_lines)
    except:
        return ""

def get_env_content():
    try:
        with open(".env", "r") as f:
            return f.read()
    except:
        return ""

STARTUP_SCRIPT_TEMPLATE = """#!/bin/bash
set -ex

exec > >(tee -a /var/log/cloud-init-output.log) 2>&1

MASTER_URL="{master_url}"
VM_ID="{vm_id}"
ACCESS_KEY="{access_key}"

log_to_master() {{
    # tried 3 different ways to escape json in bash
    # printf finally worked, not touching this again
    local payload=$(printf '{{"vm_id":"%s","message":"%s","access_key":"%s"}}' "$VM_ID" "$1" "$ACCESS_KEY")

    curl -sS -X POST "$MASTER_URL/vm/startup_log" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        --connect-timeout 3 --max-time 5 2>/dev/null || true
}}

log_to_master "VM startup initiated" &

export DEBIAN_FRONTEND=noninteractive

mkdir -p /root/game-server
mkdir -p /mnt/volume/binaries
cd /root/game-server

VM_PUBLIC_IP=$(curl -s https://api.ipify.org)
if [ -z "$VM_PUBLIC_IP" ]; then
    VM_PUBLIC_IP=$(curl -s https://icanhazip.com)
fi

log_to_master "Downloading binary and installing packages" &

(apt-get update -y -qq && apt-get install -y -qq python3 python3-pip xvfb libgl1-mesa-dev libglu1-mesa-dev libx11-6 libxext6 libxrender1 curl wget > /dev/null 2>&1 && pip3 install -q aiohttp requests psutil python-dotenv cryptography) &
INSTALL_PID=$!

for i in {{1..5}}; do
    if curl -X POST "$MASTER_URL/download_binary" \
        -H "Content-Type: application/json" \
        -d "{{\\\"access_key\\\":\\\"$ACCESS_KEY\\\"}}" \
        -o /mnt/volume/binaries/server.x86_64 \
        --connect-timeout 30 \
        --max-time 300; then

        if [ -f /mnt/volume/binaries/server.x86_64 ] && [ -s /mnt/volume/binaries/server.x86_64 ]; then
            SIZE=$(stat -c%s /mnt/volume/binaries/server.x86_64)
            log_to_master "Binary downloaded: $SIZE bytes"
            break
        fi
    fi
    log_to_master "Download attempt $i failed"
    sleep 5
done &
DOWNLOAD_PID=$!

wait $INSTALL_PID
wait $DOWNLOAD_PID

if [ ! -s /mnt/volume/binaries/server.x86_64 ]; then
    log_to_master "ERROR: Binary download failed"
    exit 1
fi

chmod +x /mnt/volume/binaries/server.x86_64

cat > config.py << EOFCONFIG
SERVER_PUBLIC_IP = '$VM_PUBLIC_IP'

{config_code}
EOFCONFIG

cat > .env << 'EOFENV'
{env_content}
EOFENV

cat > vm_game_server_manager.py << 'EOFPY'
{vm_manager_code}
EOFPY

log_to_master "Starting VM manager"

# Test xvfb before starting
if ! command -v xvfb-run &> /dev/null; then
    log_to_master "ERROR: xvfb-run not found"
    exit 1
fi

nohup python3 vm_game_server_manager.py > /var/log/vm-manager.log 2>&1 &
echo $! > /var/run/vm-manager.pid
VM_PID=$!

sleep 3

if ps aux | grep -v grep | grep "vm_game_server_manager.py" > /dev/null; then
    VM_PID=$(cat /var/run/vm-manager.pid)
    log_to_master "VM manager running (PID: $VM_PID)"
else
    log_to_master "ERROR: VM manager failed to start"
    cat /var/log/vm-manager.log
    exit 1
fi

log_to_master "Setup complete"
"""

def get_headers():
    if not HETZNER_API_TOKEN:
        return None
    return {
        "Authorization": f"Bearer {HETZNER_API_TOKEN}",
        "Content-Type": "application/json"
    }

def wait_for_vm_manager(vm_ip: str, timeout: int = 180) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = requests.get(
                f"http://{vm_ip}:8081/status",
                timeout=5
            )
            if response.status_code == 200:
                print(f"VM manager is responding on {vm_ip}:8081")
                return True
        except:
            pass

        elapsed = int(time.time() - start)
        if elapsed % 15 == 0 and elapsed > 0:
            print(f"Waiting for VM manager... ({elapsed}s)")

        time.sleep(5)

    return False

def create_vm(vm_id: str, master_server_url: str) -> Optional[Dict]:
    headers = get_headers()
    if not headers:
        print("Hetzner API token not configured")
        return None

    try:
        vm_manager_code = get_vm_manager_script()
        if not vm_manager_code:
            print("ERROR: Could not load vm_game_server_manager.py")
            return None
        config_code = get_config_script()
        if not config_code:
            print("ERROR: Could not load config.py")
            return None
        env_content = get_env_content()
        if not env_content:
            print("ERROR: Could not load .env")
            return None

        print(f"Creating VM {vm_id[:8]}...")

        startup_script = STARTUP_SCRIPT_TEMPLATE.format(
            master_url=master_server_url,
            vm_id=vm_id,
            access_key=DATASTORE_PASSWORD,
            vm_manager_code=vm_manager_code,
            config_code=config_code,
            env_content=env_content,
            max_servers=MAX_SERVERS_PER_VM,
            vm_ip="$(/usr/bin/curl -s https://api.ipify.org)"
        )

        payload = {
            "name": f"game-vm-{vm_id[:8]}",
            "server_type": VM_TYPE,
            "image": VM_IMAGE,
            "location": VM_LOCATION,
            "start_after_create": True,
            "user_data": startup_script,
            "labels": {
                "type": "game-server",
                "vm_id": vm_id
            }
        }

        response = requests.post(
            f"{HETZNER_API_BASE}/servers",
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code != 201:
            print(f"Error creating VM: {response.status_code} - {response.text}")
            return None

        data = response.json()
        server = data.get("server", {})
        action = data.get("action", {})
        server_id = server.get("id")
        action_id = action.get("id")

        print(f"VM creation started - Server ID: {server_id}")

        # TODO: this should be configurable thru .env
        max_wait = 180
        waited = 0

        while waited < max_wait:
            time.sleep(5)
            waited += 5

            action_response = requests.get(
                f"{HETZNER_API_BASE}/actions/{action_id}",
                headers=headers,
                timeout=10
            )

            if action_response.status_code == 200:
                action_data = action_response.json()
                action_status = action_data.get("action", {}).get("status")

                if waited % 15 == 0:
                    print(f"VM creation status: {action_status} ({waited}s)")

                if action_status == "success":
                    print(f"VM created successfully")
                    break
                elif action_status == "error":
                    error_msg = action_data.get("action", {}).get("error", {}).get("message", "Unknown")
                    print(f"VM creation failed: {error_msg}")
                    delete_vm(server_id)
                    return None

        server_info = requests.get(
            f"{HETZNER_API_BASE}/servers/{server_id}",
            headers=headers,
            timeout=10
        )

        if server_info.status_code != 200:
            print(f"Failed to get server info")
            delete_vm(server_id)
            return None

        server_data = server_info.json().get("server", {})
        ipv4 = server_data.get("public_net", {}).get("ipv4", {})
        vm_ip = ipv4.get("ip")

        if not vm_ip:
            print(f"Failed to get VM IP")
            delete_vm(server_id)
            return None

        print(f"VM IP: {vm_ip}")
        print(f"Waiting for VM manager to start...")

        if not wait_for_vm_manager(vm_ip, timeout=180):
            print(f"VM manager failed to start within timeout")
            delete_vm(server_id)
            return None

        return {
            "vm_id": vm_id,
            "server_id": server_id,
            "name": server_data.get("name"),
            "ip": vm_ip,
            "status": "running",
            "created": time.time()
        }

    except Exception as e:
        print(f"Error creating VM: {e}")
        import traceback
        traceback.print_exc()
        return None

def delete_vm(server_id: int) -> bool:
    headers = get_headers()
    if not headers:
        return False

    try:
        response = requests.delete(
            f"{HETZNER_API_BASE}/servers/{server_id}",
            headers=headers,
            timeout=30
        )

        return response.status_code in [200, 204]

    except Exception as e:
        print(f"Error deleting VM: {e}")
        return False

def get_server(server_id: int) -> Optional[Dict]:
    headers = get_headers()
    if not headers:
        return None

    try:
        response = requests.get(
            f"{HETZNER_API_BASE}/servers/{server_id}",
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            server = data.get("server", {})

            ipv4 = server.get("public_net", {}).get("ipv4", {})
            ip = ipv4.get("ip") if ipv4 else None

            return {
                "server_id": server.get("id"),
                "name": server.get("name"),
                "ip": ip,
                "status": server.get("status"),
                "created": server.get("created")
            }

        return None

    except Exception as e:
        print(f"Error getting server: {e}")
        return None

def list_vms() -> List[Dict]:
    headers = get_headers()
    if not headers:
        return []

    try:
        params = {
            "label_selector": "type=game-server"
        }

        response = requests.get(
            f"{HETZNER_API_BASE}/servers",
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            servers = data.get("servers", [])
            result = []

            for server in servers:
                ipv4 = server.get("public_net", {}).get("ipv4", {})
                ip = ipv4.get("ip") if ipv4 else ""

                labels = server.get("labels", {})
                vm_id = labels.get("vm_id", "")

                result.append({
                    "server_id": server.get("id"),
                    "name": server.get("name"),
                    "vm_id": vm_id,
                    "ip": ip,
                    "status": server.get("status"),
                    "created": server.get("created")
                })

            return result

        return []

    except Exception as e:
        print(f"Error listing VMs: {e}")
        return []

def get_vm_status(server_id: int) -> Optional[str]:
    server = get_server(server_id)
    return server.get("status") if server else None

def get_vm_metrics(server_id: int, metric_type: str = "cpu", start: str = None, end: str = None) -> Optional[Dict]:
    headers = get_headers()
    if not headers:
        return None

    try:
        params = {
            "type": metric_type
        }

        if start:
            params["start"] = start
        if end:
            params["end"] = end

        response = requests.get(
            f"{HETZNER_API_BASE}/servers/{server_id}/metrics",
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code == 200:
            return response.json()

        return None

    except Exception as e:
        print(f"Error getting VM metrics: {e}")
        return None

async def register_vm_heartbeat(vm_id: str, server_stats: List[Dict]) -> Dict:
    async with vm_registry_lock:
        if vm_id not in vm_registry:
            vm_registry[vm_id] = {
                "vm_id": vm_id,
                "last_heartbeat": time.time(),
                "servers": {},
                "total_players": 0,
                "status": "active"
            }
        else:
            if vm_registry[vm_id].get("status") == "provisioning":
                vm_registry[vm_id]["status"] = "active"
                print(f"VM {vm_id[:8]} is now active")

        vm_info = vm_registry[vm_id]
        vm_info["last_heartbeat"] = time.time()

        old_servers = set(vm_info["servers"].keys())
        new_servers = set()

        total_players = 0

        for server in server_stats:
            server_uid = server.get("uid")
            if server_uid:
                new_servers.add(server_uid)
                player_count = server.get("player_count", 0)

                vm_info["servers"][server_uid] = {
                    "uid": server_uid,
                    "port": server.get("port"),
                    "player_count": player_count,
                    "status": server.get("status", "unknown"),
                    "last_heartbeat": time.time(),
                    "owner_id": server.get("owner_id"),
                    "private": server.get("private", False)
                }
                total_players += player_count

        removed_servers = old_servers - new_servers
        for server_uid in removed_servers:
            print(f"Server {server_uid} removed from VM {vm_id[:8]}")
            del vm_info["servers"][server_uid]

            from database_manager import execute_query
            query = "UPDATE player_data SET server_id = NULL WHERE server_id = ?"
            execute_query(query, (server_uid,))

        vm_info["total_players"] = total_players

        if total_players > 0:
            if 'empty_since' in vm_info:
                del vm_info['empty_since']

    return {"status": "ok", "command": None}

async def request_new_vm(master_url: str) -> Optional[Dict]:
    vm_id = str(uuid.uuid4())

    print(f"Creating new VM: {vm_id}")
    vm_data = create_vm(vm_id, master_url)

    if vm_data:
        async with vm_registry_lock:
            vm_registry[vm_id] = {
                "vm_id": vm_id,
                "server_id": vm_data.get("server_id"),
                "ip": vm_data.get("ip"),
                "last_heartbeat": time.time(),
                "servers": {},
                "total_players": 0,
                "status": "provisioning",
                "created": vm_data.get("created", time.time())
            }

        print(f"VM registered: {vm_id} (IP: {vm_data.get('ip')})")
        return vm_registry[vm_id]

    return None

def get_available_vm_for_server() -> Optional[str]:
    for vm_id, vm_info in vm_registry.items():
        if vm_info.get("status") != "active":
            continue

        server_count = len(vm_info.get("servers", {}))
        if server_count < MAX_SERVERS_PER_VM:
            return vm_id

    return None

def get_vm_by_server_uid(server_uid: str) -> Optional[Dict]:
    for vm_id, vm_info in vm_registry.items():
        if server_uid in vm_info.get("servers", {}):
            return vm_info

    return None

async def cleanup_failed_vm(vm_id: str):
    async with vm_registry_lock:
        if vm_id in vm_registry:
            vm_info = vm_registry[vm_id]
            if "server_id" in vm_info:
                delete_vm(vm_info["server_id"])
            del vm_registry[vm_id]

async def shutdown_vm_gracefully(vm_ip: str, server_id: int) -> bool:
    try:
        response = requests.post(
            f"http://{vm_ip}:8081/shutdown",
            json={"graceful": True},
            timeout=5
        )
        if response.status_code == 200:
            await asyncio.sleep(30)
    except:
        pass

    return delete_vm(server_id)

async def vm_lifecycle_monitor():
    while True:
        try:
            await asyncio.sleep(30)

            current_time = time.time()
            vms_to_cleanup = []
            vms_to_shutdown = []

            async with vm_registry_lock:
                for vm_id, vm_info in list(vm_registry.items()):
                    last_heartbeat = vm_info.get("last_heartbeat", 0)
                    total_players = vm_info.get("total_players", 0)
                    servers = vm_info.get("servers", {})
                    is_master = vm_info.get("is_master", False)

                    if is_master:
                        continue

                    all_servers_empty = all(
                        server.get("player_count", 0) == 0
                        for server in servers.values()
                    )

                    if current_time - last_heartbeat > 120:
                        if vm_info.get("status") == "active":
                            vm_info["status"] = "inactive"
                            print(f"VM {vm_id[:8]} marked as inactive")

                    if current_time - last_heartbeat > 180:
                        print(f"VM {vm_id[:8]} is stale, cleaning up")
                        vms_to_cleanup.append(vm_id)
                    elif vm_info.get("status") == "active" and all_servers_empty and len(servers) > 0:
                        if 'empty_since' not in vm_info:
                            vm_info['empty_since'] = current_time
                            print(f"VM {vm_id[:8]} empty, starting shutdown timer")
                        elif current_time - vm_info.get('empty_since', current_time) > INACTIVE_TIME:
                            print(f"VM {vm_id[:8]} has been empty, scheduling shutdown")
                            vms_to_shutdown.append((vm_id, vm_info))
                    elif not all_servers_empty and 'empty_since' in vm_info:
                        del vm_info['empty_since']
                        print(f"VM {vm_id[:8]} has active players again, cancelling shutdown timer")

            for vm_id in vms_to_cleanup:
                print(f"Cleaning up stale VM: {vm_id[:8]}")
                await cleanup_failed_vm(vm_id)

            for vm_id, vm_info in vms_to_shutdown:
                print(f"Shutting down empty VM: {vm_id[:8]}")
                server_id = vm_info.get("server_id")
                vm_ip = vm_info.get("ip")
                if server_id and vm_ip:
                    await shutdown_vm_gracefully(vm_ip, server_id)
                await cleanup_failed_vm(vm_id)

        except Exception as e:
            print(f"Error in VM lifecycle monitor: {e}")
            import traceback
            traceback.print_exc()

def get_vm_stats() -> Dict:
    total_vms = len(vm_registry)
    active_vms = sum(1 for vm in vm_registry.values() if vm.get("status") == "active")
    total_servers = sum(len(vm.get("servers", {})) for vm in vm_registry.values())
    total_players = sum(vm.get("total_players", 0) for vm in vm_registry.values())

    vm_list = []
    for vm_id, vm_info in vm_registry.items():
        vm_list.append({
            "vm_id": vm_id,
            "ip": vm_info.get("ip", "unknown"),
            "status": vm_info.get("status", "unknown"),
            "server_count": len(vm_info.get("servers", {})),
            "player_count": vm_info.get("total_players", 0),
            "last_heartbeat": vm_info.get("last_heartbeat", 0)
        })

    return {
        "total_vms": total_vms,
        "active_vms": active_vms,
        "total_servers": total_servers,
        "total_players": total_players,
        "vms": vm_list
    }

if HETZNER_API_TOKEN:
    print("Hetzner Cloud API initialized")
else:
    print("Warning: HETZNER_API_TOKEN not set")
