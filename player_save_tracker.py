import time
import uuid
import asyncio
from typing import Dict, Set
import requests

active_saves = {}
active_saves_lock = asyncio.Lock()
save_timeout = 30.0

class PlayerSaveTracker:
    def __init__(self, vm_manager_url: str = None):
        self.vm_manager_url = vm_manager_url
    
    async def start_save(self, user_id: int, operation: str = "update") -> str:
        save_id = f"{user_id}_{operation}_{uuid.uuid4().hex[:8]}"
        
        async with active_saves_lock:
            active_saves[save_id] = {
                "user_id": user_id,
                "operation": operation,
                "start_time": time.time(),
                "status": "in_progress"
            }
        
        if self.vm_manager_url:
            try:
                requests.post(
                    f"{self.vm_manager_url}/track_save",
                    json={"save_id": save_id, "status": "start"},
                    timeout=2
                )
            except:
                pass
        
        return save_id
    
    async def complete_save(self, save_id: str, success: bool = True):
        async with active_saves_lock:
            if save_id in active_saves:
                active_saves[save_id]["status"] = "complete" if success else "failed"
                active_saves[save_id]["end_time"] = time.time()
                
                await asyncio.sleep(1)
                del active_saves[save_id]
        
        if self.vm_manager_url:
            try:
                requests.post(
                    f"{self.vm_manager_url}/track_save",
                    json={"save_id": save_id, "status": "complete" if success else "failed"},
                    timeout=2
                )
            except:
                pass
    
    async def get_pending_saves(self) -> Set[str]:
        async with active_saves_lock:
            return set(active_saves.keys())
    
    async def wait_for_all_saves(self, timeout: float = 30.0):
        start_time = time.time()
        
        while True:
            async with active_saves_lock:
                if len(active_saves) == 0:
                    return True
            
            if time.time() - start_time > timeout:
                async with active_saves_lock:
                    pending_count = len(active_saves)
                print(f"Timeout waiting for saves. {pending_count} still pending.")
                return False
            
            await asyncio.sleep(0.5)
    
    async def cleanup_stale_saves(self):
        current_time = time.time()
        stale_saves = []
        
        async with active_saves_lock:
            for save_id, save_info in active_saves.items():
                if current_time - save_info["start_time"] > save_timeout:
                    stale_saves.append(save_id)
            
            for save_id in stale_saves:
                print(f"Removing stale save: {save_id}")
                del active_saves[save_id]

save_tracker = PlayerSaveTracker()

async def save_tracker_monitor():
    while True:
        await save_tracker.cleanup_stale_saves()
        await asyncio.sleep(30)
