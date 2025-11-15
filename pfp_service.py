import os
import json
import time
import subprocess
import asyncio
import platform
from PIL import Image
from typing import Optional, Dict, Any
from config import SERVER_PUBLIC_IP, GODOT_SERVER_BIN, VOLUME_PATH

PFPS_DIR = os.path.join(VOLUME_PATH, "pfps")
IS_WINDOWS = platform.system() == "Windows"
USE_XVFB = not IS_WINDOWS and os.environ.get("USE_XVFB", "true").lower() == "true"

pfp_queue = asyncio.Queue(maxsize=100)
active_renders = 0
MAX_CONCURRENT_RENDERS = 5 # more than this and server will die
render_tasks = []

def ensurePfpDirectory():
    os.makedirs(PFPS_DIR, exist_ok=True)

def avatar_hash(avatarData: Dict[str, Any]) -> str:
    colors = avatarData.get("bodyColors", {})
    ## im so confused, why tf when i just commented these out it renders accessories??????
    ## whatever, it works, just leave it like this
    #accessories = avatarData.get("accessories", [])

    hash_str = json.dumps({
        "colors": colors,
        #"accessories": [acc.get("id") for acc in accessories]
    }, sort_keys=True)

    import hashlib
    return hashlib.md5(hash_str.encode()).hexdigest()

async def generatePfp(userId: int, avatarData: Dict[str, Any]) -> str:
    ensurePfpDirectory()

    timestamp = int(time.time())
    filename = f"{userId}_{timestamp}.png"
    filepath = os.path.join(PFPS_DIR, filename)

    if not os.path.exists(GODOT_SERVER_BIN):
        print(f"Godot binary not found!!!")
        return generateFallbackPfp(userId)

    if IS_WINDOWS:
        config_path = f"avatar_config_{userId}_{timestamp}.json"
    else:
        config_path = f"/tmp/avatar_config_{userId}_{timestamp}.json"

    try:
        with open(config_path, 'w') as f:
            json.dump(avatarData, f)
    except Exception as e:
        print(f"Error writing avatar config: {e}")
        return generateFallbackPfp(userId)

    try:
        env = os.environ.copy()

        if USE_XVFB and os.path.exists("/usr/bin/xvfb-run"):
            cmd = [
                "xvfb-run",
                "-a",
                "-s", "-screen 0 1024x768x24 +extension GLX",
                GODOT_SERVER_BIN,
                "--rendering-driver", "opengl3",
                "--audio-driver", "Dummy",
                "--pfp-render",
                "--avatar-config", config_path,
                "--output", filepath
            ]
        else:
            cmd = [
                GODOT_SERVER_BIN,
                "--rendering-driver", "opengl3",
                "--audio-driver", "Dummy",
                "--pfp-render",
                "--avatar-config", config_path,
                "--output", filepath
            ]
            if not IS_WINDOWS:
                env["DISPLAY"] = ":99"

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env if not IS_WINDOWS else None
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=15.0
            )

            if process.returncode == 0 and os.path.exists(filepath):
                try:
                    img = Image.open(filepath)
                    w, h = img.size
                    left = (w - 512) // 2
                    top = (h - 512) // 2
                    right = left + 512
                    bottom = top + 512
                    img = img.crop((left, top, right, bottom))
                    img.save(filepath)
                except Exception as e:
                    print(f"Failed to crop generated PFP: {e}")

                try:
                    os.remove(config_path)
                except:
                    pass
                return filepath
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                stdout_msg = stdout.decode() if stdout else "No output"
                print(f"Godot render failed (code {process.returncode})")
                print(f"stderr: {error_msg}")
                print(f"stdout: {stdout_msg}")

        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            print(f"Godot render timeout for user {userId}")

    except FileNotFoundError as e:
        print(f"Godot binary not found: {e}")
    except Exception as e:
        print(f"Error rendering PFP for user {userId}: {e}")
        import traceback
        traceback.print_exc()

    try:
        if os.path.exists(config_path):
            os.remove(config_path)
    except:
        pass

    return generateFallbackPfp(userId)

def generateFallbackPfp(userId: int) -> str:
    timestamp = int(time.time())
    filename = f"{userId}_{timestamp}_fallback.png"
    filepath = os.path.join(PFPS_DIR, filename)

    try:
        from PIL import Image, ImageDraw, ImageFont

        colors = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A",
            "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E2"
        ]
        color = colors[userId % len(colors)]

        img = Image.new('RGB', (512, 512), color=color)
        draw = ImageDraw.Draw(img)

        try:
            if IS_WINDOWS:
                font = ImageFont.truetype("arial.ttf", 80)
            else:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
        except:
            font = ImageFont.load_default()

        text = f"#{userId}"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (512 - text_width) // 2
        y = (512 - text_height) // 2

        draw.text((x, y), text, fill='white', font=font)
        img.save(filepath)

    except ImportError as e:
        print(f"Error writing avatar config: {e}")
        return generateFallbackPfp(userId)

    return filepath

async def pfp_worker():
    global active_renders
    while True:
        try:
            user_id, avatar_data = await asyncio.wait_for(pfp_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        try:
            active_renders += 1
            await generatePfp(user_id, avatar_data)
        except Exception as e:
            print(f"Error in PFP worker for user {user_id}: {e}")
        finally:
            active_renders -= 1
            pfp_queue.task_done()

async def updateUserPfp(userId: int, force: bool = False) -> str:
    from avatar_service import getFullAvatar
    from player_data import getPlayerData, savePlayerData

    avatarData = getFullAvatar(userId)

    if not force:
        playerData = getPlayerData(userId)
        if playerData:
            current_hash = playerData.get("avatar_hash")
            new_hash = avatar_hash(avatarData)

            if current_hash == new_hash:
                print(f"Avatar unchanged for user {userId}, skipping PFP regeneration")
                return playerData.get("pfp", getPfp(userId))

    cleanupOldPfps(userId, keepRecent=0)

    if pfp_queue.qsize() >= MAX_CONCURRENT_RENDERS * 2:
        print(f"PFP queue full, using existing PFP for user {userId}")
        playerData = getPlayerData(userId)
        if playerData and playerData.get("pfp"):
            return playerData["pfp"]

    newPfpPath = await generatePfp(userId, avatarData)

    playerData = getPlayerData(userId)
    if playerData:
        port = os.environ.get('PORT', 8080)
        relative_path = os.path.relpath(newPfpPath, VOLUME_PATH)
        playerData["pfp"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"
        playerData["avatar_hash"] = avatar_hash(avatarData)
        await savePlayerData(userId, playerData)

    return newPfpPath

def getPfp(userId: int) -> str:
    from player_data import getPlayerData

    playerData = getPlayerData(userId)
    if playerData and "pfp" in playerData:
        return playerData["pfp"]

    defaultPfpPath = os.path.join(PFPS_DIR, "default.png")
    if not os.path.exists(defaultPfpPath):
        ensurePfpDirectory()
        try:
            from PIL import Image, ImageDraw

            img = Image.new('RGB', (512, 512), color='#2C3E50')
            draw = ImageDraw.Draw(img)

            draw.ellipse([156, 100, 356, 300], fill='#34495E')
            draw.ellipse([106, 280, 406, 480], fill='#34495E')

            img.save(defaultPfpPath)

        except ImportError as e:
            print(f"Error writing avatar config: {e}")
            return generateFallbackPfp(userId)

    port = os.environ.get('PORT', 8080)
    relative_path = os.path.relpath(defaultPfpPath, VOLUME_PATH)
    return f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

def cleanupOldPfps(userId: int, keepRecent: int = 5):
    ensurePfpDirectory()

    userPfps = []
    prefix = f"{userId}_"

    for filename in os.listdir(PFPS_DIR):
        if filename.startswith(prefix) and filename.endswith('.png'):
            filepath = os.path.join(PFPS_DIR, filename)
            try:
                timestamp = os.path.getctime(filepath)
                userPfps.append((timestamp, filepath))
            except:
                pass

    userPfps.sort(key=lambda x: x[0], reverse=True)

    for _, filepath in userPfps[keepRecent:]:
        try:
            os.remove(filepath)
        except Exception as e:
            print(f"Failed to remove old PFP {filepath}: {e}")

async def start_pfp_workers():
    for _ in range(MAX_CONCURRENT_RENDERS):
        task = asyncio.create_task(pfp_worker())
        render_tasks.append(task)

async def stop_pfp_workers():
    for task in render_tasks:
        task.cancel()
    await asyncio.gather(*render_tasks, return_exceptions=True)
