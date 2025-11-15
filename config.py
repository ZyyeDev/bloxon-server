import os
import socket
import requests
import secrets

def get_public_ip():
    try:
        response = requests.get('https://api.ipify.org?format=text', timeout=5)
        return response.text.strip()
    except:
        try:
            response = requests.get('https://icanhazip.com', timeout=5)
            return response.text.strip()
        except:
            return None

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_server_ip():
    public_ip = os.environ.get("SERVER_PUBLIC_IP")

    if public_ip:
        return public_ip

    public_ip = get_public_ip()
    if public_ip:
        return public_ip

    return get_local_ip()

def generate_dashboard_password():
    password_file = os.path.join("server_data", "dashboard.pwd")
    if os.path.exists(password_file):
        with open(password_file, "r") as f:
            return f.read().strip()

    password = secrets.token_urlsafe(32)
    os.makedirs("server_data", exist_ok=True)
    with open(password_file, "w") as f:
        f.write(password)
    os.chmod(password_file, 0o600)
    print(f"Generated dashboard password: {password}")
    return password

def get_current_binary_version():
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, 'r') as f:
            return f.read().strip()
    return "unknown"

def set_binary_version(version: str):
    with open(VERSION_FILE, 'w') as f:
        f.write(version)

SERVER_PUBLIC_IP = get_server_ip()
BASE_PORT = int(os.environ.get("PORT", 8080))
VOLUME_PATH = os.environ.get("VOLUME_PATH", "/mnt/volume")
BINARIES_DIR = os.environ.get("VOLUME_PATH", "/mnt/volume/binaries/")

CACHE_TTL = ((60*60)*24)*30 # 1 month, srry for it being ugly
DASHBOARD_CACHE_TTL = 10

RATE_LIMIT_WINDOW = 15 # time for reset max requests
RATELIMIT_MAX = 10000

MAX_SERVERS_PER_VM = int(os.environ.get("MAX_SERVERS_PER_VM", "6"))
MAX_SERVERS_IN_MASTER = int(os.environ.get("MAX_SERVERS_PER_VM", "4"))

GODOT_SERVER_BIN = os.environ.get("GODOT_SERVER_BIN", "/mnt/volume/binaries/server.x86_64")

DATASTORE_PASSWORD = os.environ.get("DATASTORE_PASSWORD", "@MEOW")
DASHBOARD_PASSWORD = generate_dashboard_password()

GOOGLE_PLAY_PACKAGE_NAME = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", "com.example")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")

CURRENT_SERVER_VERSION = "1.0.0"
VERSION_FILE = os.path.join(BINARIES_DIR, "version.txt")

if os.path.exists(VERSION_FILE):
    try:
        with open(VERSION_FILE) as f:
            CURRENT_SERVER_VERSION = f.read().strip()
    except IOError as e:
        print(e)
else:
    print("[WARNING] version file does not exist, this can be ignored")
    

MODELS_DIR = os.path.join(VOLUME_PATH, "models")
ICONS_DIR = os.path.join(VOLUME_PATH, "icons")

DB_DIR = os.path.join(VOLUME_PATH, "database")
BACKUP_DIR = os.path.join(VOLUME_PATH, "backups")

print(f"Server configured with IP: {SERVER_PUBLIC_IP}")
print(f"Server configured with PORT: {BASE_PORT}")
print(f"Godot binary path: {GODOT_SERVER_BIN}")
