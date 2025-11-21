import os
import sys
import time
import uuid
import asyncio
import signal
import subprocess
from typing import Dict, Set
from aiohttp import web
from config import get_public_ip, GODOT_SERVER_BIN, MAX_SERVERS_PER_VM
import requests
import traceback

MASTER_SERVER_URL = os.environ.get("MASTER_SERVER_URL", f"http://{get_public_ip()}:8080") #os.environ.get("MASTER_SERVER_URL", "http://localhost:8080")
VM_ID = os.environ.get("VM_ID", str(uuid.uuid4()))
BASE_PORT = 9000

print("VM GAME SERVER MANAGER BIN: " + GODOT_SERVER_BIN)

game_server_processes = {}
game_server_info = {}
shutdown_flag = False
pending_saves = set()
pending_saves_lock = asyncio.Lock()
used_ports = set()

def get_next_available_port():
    for i in range(MAX_SERVERS_PER_VM):
        port = BASE_PORT + i
        if port not in used_ports:
            used_ports.add(port)
            return port
    return None

def release_port(port: int):
    if port in used_ports:
        used_ports.remove(port)

async def spawn_game_server(server_uid: str = None, port: int = None, owner_id: int = None):
    try:
        if port is None:
            port = get_next_available_port()
            if port is None:
                print(f"No available ports for new server")
                return False

        if server_uid is None:
            server_uid = f"{VM_ID}-{port}"

        is_private = owner_id is not None
        server_type = "PRIVATE" if is_private else "PUBLIC"
        print(f"Spawning {server_type} game server {server_uid} on port {port}")

        cmd = [
            "xvfb-run",
            "-a",
            "-s", "-screen 0 512x512x24",
            GODOT_SERVER_BIN,
            "--headless",
            "--server",
            "--port", str(port),
            "--master", MASTER_SERVER_URL,
            "--uid", server_uid,
        ]

        if is_private:
            cmd.extend(["--private", "--owner", str(owner_id)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        game_server_processes[server_uid] = proc
        game_server_info[server_uid] = {
            "port": port,
            "players": set(),
            "last_heartbeat": time.time(),
            "status": "starting",
            "owner_id": owner_id, # none for public servers, user_id for private
            "private": is_private
        }

        await asyncio.sleep(3)
        game_server_info[server_uid]["status"] = "running"

        print(f"Spawned {server_type} game server {server_uid} on port {port} with VM_ID {VM_ID}")
        return True
    except Exception as e:
        print(f"Failed to spawn game server {server_uid}: {e}")
        traceback.print_exc()
        if port:
            release_port(port)
        return False

async def stop_game_server(server_uid: str, graceful: bool = True):
    if server_uid not in game_server_processes:
        return False

    print(f'stopping server: {server_uid}')
    proc = game_server_processes[server_uid]

    if graceful:
        proc.terminate()
        try:
            # wait 10 secs to give the server to to save everything
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    else:
        proc.kill()
        await proc.wait()

    port = game_server_info[server_uid].get("port")
    if port:
        release_port(port)

    del game_server_processes[server_uid]
    if server_uid in game_server_info:
        del game_server_info[server_uid]

    return True

async def heartbeat_to_master():
    consecutive_failures = 0
    while not shutdown_flag:
        try:
            server_stats = []
            for server_uid, info in game_server_info.items():
                server_stats.append({
                    "uid": server_uid,
                    "port": info["port"],
                    "player_count": len(info["players"]),
                    "status": info["status"],
                    "owner_id": info.get("owner_id"),
                    "private": info.get("private", False)
                })

            payload = {
                "vm_id": VM_ID,
                "servers": server_stats,
                "timestamp": time.time(),
                "total_players": sum(len(info["players"]) for info in game_server_info.values())
            }

            print(f"Sending heartbeat to {MASTER_SERVER_URL}/vm/heartbeat")
            response = requests.post(
                f"{MASTER_SERVER_URL}/vm/heartbeat",
                json=payload,
                timeout=10
            )

            if response.status_code == 200:
                consecutive_failures = 0
                data = response.json()
                if data.get("command") == "shutdown":
                    asyncio.create_task(graceful_shutdown())
            else:
                consecutive_failures += 1
                print(f"Heartbeat failed: {response.status_code} - {response.text}")

        except Exception as e:
            consecutive_failures += 1
            print(f"Heartbeat error (failures: {consecutive_failures}): {e}")

        if consecutive_failures > 6:
            print("Too many heartbeat failures, shutting down...")
            asyncio.create_task(graceful_shutdown())
            break

        await asyncio.sleep(5)

async def update_server_players(request):
    try:
        data = await request.json()
        server_uid = data.get("server_uid")
        players = set(data.get("players", []))

        if server_uid in game_server_info:
            game_server_info[server_uid]["players"] = players
            game_server_info[server_uid]["last_heartbeat"] = time.time()

            return web.json_response({"success": True})

        return web.json_response({"error": "server_not_found"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def track_player_save(request):
    try:
        data = await request.json()
        save_id = data.get("save_id")
        status = data.get("status")

        async with pending_saves_lock:
            if status == "start":
                pending_saves.add(save_id)
            elif status == "complete" or status == "failed":
                pending_saves.discard(save_id)

        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def shutdown_endpoint(request):
    try:
        data = await request.json()
        graceful = data.get("graceful", True)
        if graceful:
            asyncio.create_task(graceful_shutdown())
        else:
            asyncio.create_task(force_shutdown())

        return web.json_response({"success": True, "message": "Shutdown initiated"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def status_endpoint(request):
    return web.json_response({
        "vm_id": VM_ID,
        "server_count": len(game_server_processes),
        "max_servers": MAX_SERVERS_PER_VM,
        "servers": [
            {
                "uid": uid,
                "port": info["port"],
                "player_count": len(info["players"]),
                "status": info["status"]
            }
            for uid, info in game_server_info.items()
        ],
        "pending_saves": len(pending_saves)
    })

async def wait_for_pending_saves(timeout: float = 30.0):
    start_time = time.time()
    while len(pending_saves) > 0:
        if time.time() - start_time > timeout:
            print(f"Warning: Timeout waiting for {len(pending_saves)} pending saves")
            break
        await asyncio.sleep(0.5)

    if len(pending_saves) == 0:
        print("All pending saves completed")
    else:
        print(f"Proceeding with {len(pending_saves)} pending saves still in progress")

async def graceful_shutdown():
    global shutdown_flag
    shutdown_flag = True

    print("Initiating graceful shutdown...")

    await wait_for_pending_saves(timeout=30.0)

    print("Stopping all game servers...")
    for server_uid in list(game_server_processes.keys()):
        await stop_game_server(server_uid, graceful=True)

    print("All game servers stopped. Exiting.")
    os._exit(0)

async def force_shutdown():
    global shutdown_flag
    shutdown_flag = True

    print("Force shutdown initiated...")

    for server_uid in list(game_server_processes.keys()):
        await stop_game_server(server_uid, graceful=False)

    print("Force shutdown complete. Exiting.")
    os._exit(0)

def signal_handler(sig, frame):
    print(f"Received signal {sig}")
    asyncio.create_task(graceful_shutdown())

async def spawn_server_endpoint(request):
    try:
        data = await request.json()
        server_uid = data.get("server_uid")
        port = data.get("port")

        if len(game_server_processes) >= MAX_SERVERS_PER_VM:
            return web.json_response({"error": "max_servers_reached"}, status=503)

        success = await spawn_game_server(server_uid, port)

        if success:
            return web.json_response({"success": True, "server_uid": server_uid or f"{VM_ID}-{port}", "port": port})
        else:
            return web.json_response({"error": "spawn_failed"}, status=500)

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def initial_server_spawn():
    await asyncio.sleep(5)

    print("Spawning initial game server...")
    port = get_next_available_port()
    if port:
        server_uid = f"{VM_ID}-{port}"
        success = await spawn_game_server(server_uid, port)
        if success:
            print(f"Initial server spawned successfully on port {port}")
        else:
            print("Failed to spawn initial server")

async def start_vm_manager():
    app = web.Application()
    app.add_routes([
        web.post("/update_players", update_server_players),
        web.post("/track_save", track_player_save),
        web.post("/shutdown", shutdown_endpoint),
        web.get("/status", status_endpoint),
        web.post("/spawn_server", spawn_server_endpoint)
    ])

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8081)
    await site.start()

    print(f"VM Manager started for VM {VM_ID}")

    asyncio.create_task(heartbeat_to_master())
    asyncio.create_task(initial_server_spawn())

    while not shutdown_flag:
        await asyncio.sleep(1)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    asyncio.run(start_vm_manager())
