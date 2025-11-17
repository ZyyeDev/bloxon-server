import os
import json
import hashlib
import time
import asyncio
from typing import Dict, Any, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import GOOGLE_PLAY_PACKAGE_NAME, GOOGLE_SERVICE_ACCOUNT_JSON
from database_manager import execute_query
from currency_system import creditCurrency

CURRENCY_PACKAGES = {
    "currency_500": {"amount": 500, "price_usd": 4.99},
    "currency_1200": {"amount": 1200, "price_usd": 9.99},
    "currency_2500": {"amount": 2500, "price_usd": 19.99},
    "currency_6000": {"amount": 6000, "price_usd": 39.99},
    "currency_14000": {"amount": 14000, "price_usd": 69.99},
    "currency_30000": {"amount": 30000, "price_usd": 119.99},
}

pending_payments = {}
pending_payments_lock = asyncio.Lock()
google_play_service = None

def get_google_play_service():
    global google_play_service
    if google_play_service:
        return google_play_service

    try:
        if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_JSON):
            return None

        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=['https://www.googleapis.com/auth/androidpublisher']
        )

        google_play_service = build('androidpublisher', 'v3', credentials=credentials)
        return google_play_service
    except Exception as e:
        print(f"Failed to initialize Google Play service: {e}")
        return None

async def save_pending_payment(user_id: int, product_id: str, purchase_token: str):
    async with pending_payments_lock:
        payment_id = f"{user_id}_{purchase_token[:16]}"
        pending_payments[payment_id] = {
            "user_id": user_id,
            "product_id": product_id,
            "purchase_token": purchase_token,
            "attempts": 0,
            "created": time.time(),
            "last_attempt": None
        }

        query = """INSERT INTO pending_payments (payment_id, user_id, product_id, purchase_token, attempts, created)
                   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(payment_id) DO UPDATE SET attempts = attempts"""
        execute_query(query, (payment_id, user_id, product_id, purchase_token, 0, time.time()))

        return payment_id

async def remove_pending_payment(payment_id: str):
    async with pending_payments_lock:
        if payment_id in pending_payments:
            del pending_payments[payment_id]

        query = "DELETE FROM pending_payments WHERE payment_id = ?"
        execute_query(query, (payment_id,))

async def load_pending_payments():
    query = "SELECT payment_id, user_id, product_id, purchase_token, attempts, created FROM pending_payments"
    results = execute_query(query, fetch_all=True)

    if results:
        async with pending_payments_lock:
            for row in results:
                payment_id = row[0]
                pending_payments[payment_id] = {
                    "user_id": row[1],
                    "product_id": row[2],
                    "purchase_token": row[3],
                    "attempts": row[4],
                    "created": row[5],
                    "last_attempt": None
                }
        print(f"Loaded {len(results)} pending payments")

async def verify_google_play_purchase(user_id: int, product_id: str, purchase_token: str) -> Dict[str, Any]:
    if product_id not in CURRENCY_PACKAGES:
        return {
            "success": False,
            "error": {"code": "INVALID_PRODUCT", "message": "Invalid product ID"}
        }

    query = "SELECT payment_id FROM payments WHERE purchase_token = ?"
    existing = execute_query(query, (purchase_token,), fetch_one=True)
    if existing:
        return {
            "success": False,
            "error": {"code": "ALREADY_PROCESSED", "message": "Purchase already processed"}
        }

    service = get_google_play_service()
    if not service:
        payment_id = await save_pending_payment(user_id, product_id, purchase_token)
        return {
            "success": False,
            "error": {"code": "SERVICE_UNAVAILABLE", "message": "Payment verification service unavailable"}
        }

    try:
        result = service.purchases().products().get(
            packageName=GOOGLE_PLAY_PACKAGE_NAME,
            productId=product_id,
            token=purchase_token
        ).execute()

        purchase_state = result.get('purchaseState')
        if purchase_state != 0:
            return {
                "success": False,
                "error": {"code": "INVALID_PURCHASE_STATE", "message": "Purchase not completed"}
            }

        #consumption_state = result.get('consumptionState')
        #if consumption_state == 1:
        #    return {
        #        "success": False,
        #        "error": {"code": "ALREADY_CONSUMED", "message": "Purchase already consumed"}
        #    }

        currency_amount = CURRENCY_PACKAGES[product_id]["amount"]

        credit_result = await creditCurrency(user_id, currency_amount)

        if not credit_result["success"]:
            return credit_result

        query = """INSERT INTO payments (user_id, purchase_token, product_id, amount, currency_awarded, verified, created)
                   VALUES (?, ?, ?, ?, ?, ?, ?)"""
        execute_query(query, (
            user_id,
            purchase_token,
            product_id,
            int(CURRENCY_PACKAGES[product_id]["price_usd"] * 100),
            currency_amount,
            True,
            time.time()
        ))

        asyncio.create_task(consume_purchase_async(service, product_id, purchase_token))

        return {
            "success": True,
            "data": {
                "currency_awarded": currency_amount,
                "new_balance": credit_result["data"]["newBalance"]
            }
        }

    except Exception as e:
        print(f"Payment verification error: {e}")
        import traceback
        traceback.print_exc()
        payment_id = await save_pending_payment(user_id, product_id, purchase_token)
        return {
            "success": False,
            "error": {"code": "VERIFICATION_FAILED", "message": str(e)}
        }

async def acknowledge_purchase_async(service, product_id: str, purchase_token: str):
    try:
        await asyncio.sleep(0)
        service.purchases().products().acknowledge(
            packageName=GOOGLE_PLAY_PACKAGE_NAME,
            productId=product_id,
            token=purchase_token,
            body={}
        ).execute()
    except Exception as ack_error:
        print(f"Purchase acknowledgment failed (non-critical): {ack_error}")

async def consume_purchase_async(service, product_id: str, purchase_token: str):
    try:
        await asyncio.sleep(0)
        service.purchases().products().consume(
            packageName=GOOGLE_PLAY_PACKAGE_NAME,
            productId=product_id,
            token=purchase_token
        ).execute()
        print(f"Successfully consumed purchase: {purchase_token}")
    except Exception as consume_error:
        print(f"Purchase consumption failed (non-critical): {consume_error}")

ad_reward_cooldowns = {}
AD_COOLDOWN_SECONDS = 30

# i was too lazy to make all the admob thing because i needed a dns and blah blah blah
# ik this is very bad, but idc. Its a placeholder.
# TODO: Make this more safe!!! (using admob api)
async def verify_ad_reward(user_id: int, ad_network: str, ad_unit_id: str,
                    reward_amount: int = 10) -> Dict[str, Any]:

    current_time = time.time()
    if user_id in ad_reward_cooldowns:
        last_reward_time = ad_reward_cooldowns[user_id]
        if current_time - last_reward_time < AD_COOLDOWN_SECONDS:
            return {
                "success": False,
                "error": {"code": "COOLDOWN_ACTIVE", "message": "Please wait before claiming another reward"}
            }

    if reward_amount > 50:
        return {
            "success": False,
            "error": {"code": "INVALID_AMOUNT", "message": "Reward amount exceeds maximum"}
        }

    credit_result = await creditCurrency(user_id, reward_amount)

    if not credit_result["success"]:
        return credit_result

    query = """INSERT INTO ad_rewards (user_id, ad_network, ad_unit_id, reward_amount, verified, created)
               VALUES (?, ?, ?, ?, ?, ?)"""
    execute_query(query, (user_id, ad_network, ad_unit_id, reward_amount, True, time.time()))

    ad_reward_cooldowns[user_id] = current_time

    return {
        "success": True,
        "data": {
            "reward_amount": reward_amount,
            "new_balance": credit_result["data"]["newBalance"]
        }
    }

async def retry_pending_payments():
    while True:
        try:
            await asyncio.sleep(60)

            async with pending_payments_lock:
                payments_to_retry = list(pending_payments.items())

            for payment_id, payment_data in payments_to_retry:
                if payment_data["attempts"] >= 5:
                    print(f"Payment {payment_id} failed after 5 attempts, removing")
                    await remove_pending_payment(payment_id)
                    continue

                last_attempt = payment_data.get("last_attempt")
                if last_attempt and time.time() - last_attempt < 300:
                    continue

                print(f"Retrying payment {payment_id}, attempt {payment_data['attempts'] + 1}")

                async with pending_payments_lock:
                    pending_payments[payment_id]["attempts"] += 1
                    pending_payments[payment_id]["last_attempt"] = time.time()

                query = "UPDATE pending_payments SET attempts = ?, last_attempt = ? WHERE payment_id = ?"
                execute_query(query, (pending_payments[payment_id]["attempts"], time.time(), payment_id))

                result = await verify_google_play_purchase(
                    payment_data["user_id"],
                    payment_data["product_id"],
                    payment_data["purchase_token"]
                )

                if result["success"]:
                    print(f"Payment {payment_id} succeeded on retry")

        except Exception as e:
            print(f"Error in payment retry: {e}")

def get_currency_packages() -> Dict[str, Any]:
    return {
        "success": True,
        "data": {
            "packages": [
                {"product_id": k, "amount": v["amount"], "price_usd": v["price_usd"]}
                for k, v in CURRENCY_PACKAGES.items()
            ]
        }
    }
