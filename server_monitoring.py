import psutil
import time
from typing import Dict, Any, List

def get_system_stats() -> Dict[str, Any]:
    cpu_percent = psutil.cpu_percent(interval=0.1)

    memory = psutil.virtual_memory()
    memory_used_mb = memory.used / (1024 * 1024)
    memory_total_mb = memory.total / (1024 * 1024)
    memory_percent = memory.percent

    disk = psutil.disk_usage('/')
    disk_used_gb = disk.used / (1024 * 1024 * 1024)
    disk_total_gb = disk.total / (1024 * 1024 * 1024)
    disk_percent = disk.percent

    return {
        "cpu": {
            "percent": round(cpu_percent, 2),
            "count": psutil.cpu_count()
        },
        "memory": {
            "used_mb": round(memory_used_mb, 2),
            "total_mb": round(memory_total_mb, 2),
            "percent": round(memory_percent, 2)
        },
        "disk": {
            "used_gb": round(disk_used_gb, 2),
            "total_gb": round(disk_total_gb, 2),
            "percent": round(disk_percent, 2)
        }
    }

def get_process_stats(process_list: Dict) -> List[Dict[str, Any]]:
    stats = []

    for server_uid, process in process_list.items():
        try:
            p = psutil.Process(process.pid)
            cpu = p.cpu_percent(interval=0.1)
            mem = p.memory_info().rss / (1024 * 1024)

            stats.append({
                "server_uid": server_uid,
                "short_uid": server_uid[:8],
                "cpu_percent": round(cpu, 2),
                "memory_mb": round(mem, 2),
                "status": p.status()
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            stats.append({
                "server_uid": server_uid,
                "short_uid": server_uid[:8],
                "cpu_percent": 0,
                "memory_mb": 0,
                "status": "terminated"
            })

    return stats

def get_network_stats() -> Dict[str, Any]:
    net_io = psutil.net_io_counters()

    return {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
        "packets_sent": net_io.packets_sent,
        "packets_recv": net_io.packets_recv
    }
