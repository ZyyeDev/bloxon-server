import re
import requests
from config import get_public_ip
from typing import Dict, Any

USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]+$')

BLOCKED_WORDS = [
    "admin", "moderator", "support", "official", "staff"
]

public_ip = get_public_ip()
MODERATION_API_URL = f"http://{public_ip}:8080/moderation"

def check_text_content(text: str) -> Dict[str, Any]:
    if not text:
        return {
            "flagged": False,
            "categories": {},
            "reason": None
        }

    text_lower = text.lower()

    categories = {
        "sexual": 0.0,
        "hate": 0.0,
        "violence": 0.0,
        "harassment": 0.0,
        "self-harm": 0.0,
        "sexual/minors": 0.0,
        "hate/threatening": 0.0,
        "violence/graphic": 0.0
    }

    flagged = False
    reasons = []

    for word in BLOCKED_WORDS:
        if word in text_lower:
            flagged = True
            categories["harassment"] = 0.8
            reasons.append("reserved word")

    try:
        response = requests.post(
            MODERATION_API_URL,
            json={"text": text},
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()

            for key in categories:
                if key in data:
                    categories[key] = data[key]

            threshold = 0.7
            for category, score in categories.items():
                if score >= threshold:
                    flagged = True
                    reasons.append(f"{category} ({score:.2f})")
    except:
        pass

    return {
        "flagged": flagged,
        "categories": categories,
        "reason": ", ".join(reasons) if reasons else None
    }

def validate_username(username: str) -> Dict[str, Any]:
    if not username:
        return {
            "valid": False,
            "error": "Username cannot be empty"
        }

    if len(username) < 3:
        return {
            "valid": False,
            "error": "Username must be at least 3 characters"
        }

    if len(username) > 20:
        return {
            "valid": False,
            "error": "Username must be at most 20 characters"
        }

    if ' ' in username:
        return {
            "valid": False,
            "error": "Username cannot contain spaces"
        }

    if not USERNAME_PATTERN.match(username):
        return {
            "valid": False,
            "error": "Username can only contain letters (a-z, A-Z), numbers (0-9), and underscores (_)"
        }

    moderation_result = check_text_content(username)
    if moderation_result["flagged"]:
        return {
            "valid": False,
            "error": "Username contains inappropriate content"
        }

    return {
        "valid": True,
        "error": None
    }
