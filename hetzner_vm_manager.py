import os
import time
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

STARTUP_SCRIPT = """#!/bin/bash
set -e

# Install dependencies
apt-get update
apt-get install -y python3 python3-pip wget curl jq

# Create working directory
mkdir -p /root/game-server
cd /root/game-server

# Download Python dependencies
cat > requirements.txt << 'EOFPIP'
aiohttp==3.9.1
requests==2.31.0
EOFPIP
pip3 install -r requirements.txt

# Download the Godot server binary from master
echo "Downloading game server binary..."
curl -X POST MASTER_URL_PLACEHOLDER/download_binary \
  -H "Content-Type: application/json" \
  -d '{"access_key":"ACCESS_KEY_PLACEHOLDER"}' \
  -o server.x86_64

chmod +x server.x86_64

# Verify download
if [ ! -f server.x86_64 ]; then
    echo "Failed to download server binary"
    exit 1
fi

# Copy VM manager script
cat > vm_game_server_manager.py << 'EOFPY'
# ... (your existing VM manager code)
EOFPY

# Set environment variables
export MASTER_SERVER_URL="MASTER_URL_PLACEHOLDER"
export VM_ID="VM_ID_PLACEHOLDER"
export GODOT_SERVER_BIN="./server.x86_64"

# Start the VM manager
nohup python3 vm_game_server_manager.py > /var/log/game-server.log 2>&1 &

echo "Game server VM started successfully"
"""

def get_headers():
    if not HETZNER_API_TOKEN:
        return None
    return {
        "Authorization": f"Bearer {HETZNER_API_TOKEN}",
        "Content-Type": "application/json"
    }

def create_vm(vm_id: str, master_server_url: str) -> Optional[Dict]:
    headers = get_headers()
    if not headers:
        print("Hetzner API token not configured")
        return None

    try:
        startup_script = STARTUP_SCRIPT.replace("MASTER_URL_PLACEHOLDER", master_server_url)
        startup_script = startup_script.replace("VM_ID_PLACEHOLDER", vm_id)
        startup_script = startup_script.replace("ACCESS_KEY_PLACEHOLDER", DATASTORE_PASSWORD)

        payload = {
            "name": f"game-vm-{vm_id[:8]}",
            "server_type": VM_TYPE,
            "image": VM_IMAGE,
            "location": VM_LOCATION,
            "user_data": startup_script,
            "start_after_create": True,
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

        if response.status_code == 201:
            data = response.json()
            server = data.get("server", {})

            ipv4 = server.get("public_net", {}).get("ipv4", {})
            ip = ipv4.get("ip") if ipv4 else None

            return {
                "vm_id": vm_id,
                "server_id": server.get("id"),
                "name": server.get("name"),
                "ip": ip,
                "status": server.get("status"),
                "created": time.time()
            }
        else:
            print(f"Error creating VM: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        print(f"Error creating VM: {e}")
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

if HETZNER_API_TOKEN:
    print("Hetzner Cloud API initialized")
else:
    print("Warning: HETZNER_API_TOKEN not set. VM management will not work.")
