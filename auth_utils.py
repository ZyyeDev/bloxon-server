import time
from collections import deque
from database_manager import execute_query

from config import (
    SERVER_PUBLIC_IP,
    RATELIMIT_MAX,
    RATE_LIMIT_WINDOW,
    CACHE_TTL
)

rateLimitDict = {}
token_cache = {}
username_to_token = {}
blockedIps = {}
CLEANUP_INTERVAL = 120
last_cleanup = 0

def isServerIp(clientIp):
    server_ips = ["127.0.0.1", "::1", SERVER_PUBLIC_IP, "localhost"]
    if clientIp in server_ips:
        return True
    return False

# todo: this looks super ugly to me
# pls change in the future
def checkRateLimit(clientIp):
    global last_cleanup
    if isServerIp(clientIp):
        return True
    currentTime = time.time()
    if clientIp in blockedIps:
        if currentTime < blockedIps[clientIp]:
            return False
        else:
            del blockedIps[clientIp]
    if currentTime - last_cleanup > CLEANUP_INTERVAL:
        _cleanup_old_entries(currentTime)
        last_cleanup = currentTime
    if clientIp not in rateLimitDict:
        rateLimitDict[clientIp] = deque(maxlen=RATELIMIT_MAX)
    timestamps = rateLimitDict[clientIp]
    cutoff = currentTime - RATE_LIMIT_WINDOW
    while timestamps and timestamps[0] < cutoff:
        timestamps.popleft()
    if len(timestamps) >= RATELIMIT_MAX:
        return False
    timestamps.append(currentTime)
    return True

def _cleanup_old_entries(currentTime):
    cutoff = currentTime - (RATE_LIMIT_WINDOW * 2)
    to_delete = []
    for ip in rateLimitDict:
        if rateLimitDict[ip] and rateLimitDict[ip][-1] < cutoff:
            to_delete.append(ip)
    for ip in to_delete:
        del rateLimitDict[ip]

def validateToken(token):
    currentTime = time.time()
    if token in token_cache:
        cached_data = token_cache[token]
        if currentTime < cached_data['expiry']:
            return True
        else:
            username = cached_data.get('username')
            if username and username in username_to_token:
                del username_to_token[username]
            del token_cache[token]
    result = execute_query(
        "SELECT username, created FROM tokens WHERE token = ?",
        (token,), fetch_one=True
    )
    if not result:
        return False
    if currentTime - result[1] > 2592000:
        return False
    token_cache[token] = {
        'username': result[0],
        'expiry': currentTime + CACHE_TTL,
        'created': result[1]
    }
    username_to_token[result[0]] = token
    return True

def getUsernameFromToken(token):
    currentTime = time.time()
    if token in token_cache:
        cached_data = token_cache[token]
        if currentTime < cached_data['expiry']:
            return cached_data['username']
        else:
            username = cached_data.get('username')
            if username and username in username_to_token:
                del username_to_token[username]
            del token_cache[token]
    result = execute_query(
        "SELECT username, created FROM tokens WHERE token = ?",
        (token,), fetch_one=True
    )
    if result:
        token_cache[token] = {
            'username': result[0],
            'expiry': currentTime + CACHE_TTL,
            'created': result[1]
        }
        username_to_token[result[0]] = token
        return result[0]
    return None

def invalidate_token_cache(token):
    if token in token_cache:
        username = token_cache[token].get('username')
        if username and username in username_to_token:
            del username_to_token[username]
        del token_cache[token]

def clear_token_cache():
    global token_cache, username_to_token
    token_cache.clear()
    username_to_token.clear()

def get_cached_token_count():
    return len(token_cache)
