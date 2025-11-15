import time
import secrets
import random
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from typing import Tuple, Dict

captcha_store = {}
ip_first_account = set()
CAPTCHA_EXPIRY = 300

def generate_puzzle_captcha() -> Tuple[str, str]:
    captcha_id = secrets.token_urlsafe(16)
    
    num1 = random.randint(1, 20)
    num2 = random.randint(1, 20)
    answer = num1 + num2
    
    img = Image.new('RGB', (200, 80), color='white')
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except:
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except:
            font = ImageFont.load_default()
    
    text = f"{num1} + {num2} = ?"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (200 - text_width) // 2
    y = (80 - text_height) // 2
    
    draw.text((x, y), text, fill='black', font=font)
    
    for _ in range(50):
        x1 = random.randint(0, 200)
        y1 = random.randint(0, 80)
        x2 = random.randint(0, 200)
        y2 = random.randint(0, 80)
        draw.line([(x1, y1), (x2, y2)], fill='gray', width=1)
    
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_data = base64.b64encode(buffer.getvalue()).decode()
    
    captcha_store[captcha_id] = {
        "answer": answer,
        "created": time.time()
    }
    
    return captcha_id, img_data

def verify_captcha(captcha_id: str, answer: int) -> Tuple[bool, str]:
    if captcha_id not in captcha_store:
        return False, "Captcha expired or invalid"
    
    captcha_data = captcha_store[captcha_id]
    
    if time.time() - captcha_data["created"] > CAPTCHA_EXPIRY:
        del captcha_store[captcha_id]
        return False, "Captcha expired"
    
    correct_answer = captcha_data["answer"]
    del captcha_store[captcha_id]
    
    try:
        user_answer = int(answer)
    except:
        return False, "Invalid answer format"
    
    if user_answer == correct_answer:
        return True, "Correct"
    else:
        return False, "Incorrect answer"

def is_first_account_from_ip(ip: str) -> bool:
    return ip not in ip_first_account

def mark_ip_used(ip: str):
    ip_first_account.add(ip)

def cleanup_expired_captchas():
    current_time = time.time()
    expired = [k for k, v in captcha_store.items() if current_time - v["created"] > CAPTCHA_EXPIRY]
    for k in expired:
        del captcha_store[k]
