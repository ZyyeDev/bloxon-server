import os
import json
import time
import re
from typing import Dict, List, Any, Optional
from config import (
    SERVER_PUBLIC_IP,
    VOLUME_PATH,
    MODELS_DIR,
    ICONS_DIR
)
from game_database import (
    get_accessory,
    save_accessory as fb_save_accessory,
    list_accessories,
    delete_accessory as fb_delete_accessory,
    save_accessory_purchase,
    get_next_accessory_id
)
from player_save_tracker import save_tracker
import asyncio

accessory_cache = {}

def loadAccessoriesData():
    pass

def saveAccessoriesData():
    pass

def fix_mtl_texture_paths(mtl_content: str, texture_filename: str) -> str:
    lines = mtl_content.split('\n')
    updated_lines = []

    texture_map_keywords = [
        'map_Kd', 'map_Ka', 'map_Ks', 'map_Bump', 'map_d',
        'bump', 'map_Ns', 'map_Ke', 'disp', 'decal'
    ]

    for line in lines:
        stripped = line.strip()
        updated = False

        for keyword in texture_map_keywords:
            if stripped.startswith(keyword):
                parts = line.split(None, 1)
                if len(parts) == 2:
                    updated_lines.append(f"{parts[0]} {texture_filename}")
                    updated = True
                    break

        if not updated:
            updated_lines.append(line)

    return '\n'.join(updated_lines)

def fix_obj_mtl_path(obj_content: str, mtl_filename: str) -> str:
    lines = obj_content.split('\n')
    updated_lines = []

    for line in lines:
        if line.strip().startswith('mtllib'):
            updated_lines.append(f"mtllib {mtl_filename}")
        else:
            updated_lines.append(line)

    return '\n'.join(updated_lines)

def getFullAvatar(userId: int) -> Dict[str, Any]:
    from player_data import getPlayerData

    playerData = getPlayerData(userId)
    if not playerData:
        return {
            "bodyColors": {
                "head": "#FFCC99",
                "torso": "#0066CC",
                "left_leg": "#00AA00",
                "right_leg": "#00AA00",
                "left_arm": "#FFCC99",
                "right_arm": "#FFCC99"
            },
            "accessories": []
        }

    avatar = playerData.get("avatar", {})
    if isinstance(avatar, str):
        try:
            avatar = json.loads(avatar)
        except:
            avatar = {}

    return {
        "bodyColors": avatar.get("bodyColors", {
            "head": "#FFCC99",
            "torso": "#0066CC",
            "left_leg": "#00AA00",
            "right_leg": "#00AA00",
            "left_arm": "#FFCC99",
            "right_arm": "#FFCC99"
        }),
        "accessories": avatar.get("accessories", [])
    }

def updateAccessoryFromDashboard(accessory_id: int, name: str = None, accessory_type: str = None,
                                price: int = None, equip_slot: str = None,
                                model_data: bytes = None, texture_data: bytes = None,
                                mtl_data: bytes = None, icon_data: bytes = None,
                                model_filename: str = None, texture_filename: str = None,
                                mtl_filename: str = None) -> Dict[str, Any]:
    from game_database import get_accessory, save_accessory as fb_save_accessory

    existing = get_accessory(accessory_id)
    if not existing:
        return {"success": False, "error": "Accessory not found"}

    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(ICONS_DIR, exist_ok=True)

    try:
        updated_name = name if name is not None else existing.get("name")
        updated_type = accessory_type if accessory_type is not None else existing.get("type")
        updated_price = price if price is not None else existing.get("price")
        updated_slot = equip_slot if equip_slot is not None else existing.get("equip_slot")

        model_path = existing.get("model_file")
        texture_path = existing.get("texture_file")
        mtl_path = existing.get("mtl_file")
        icon_path = existing.get("icon_file")

        new_texture_filename = None

        if texture_data:
            if texture_path and os.path.exists(texture_path):
                os.remove(texture_path)

            if texture_filename:
                ext = os.path.splitext(texture_filename)[1]
            else:
                ext = ".png"
            new_texture_filename = f"{accessory_id}_texture{ext}"
            texture_path = os.path.join(MODELS_DIR, new_texture_filename)

        if mtl_data:
            if mtl_path and os.path.exists(mtl_path):
                os.remove(mtl_path)

            new_mtl_filename = f"{accessory_id}_material.mtl"
            mtl_path = os.path.join(MODELS_DIR, new_mtl_filename)

            try:
                mtl_content = mtl_data.decode('utf-8', errors='ignore')

                if new_texture_filename:
                    mtl_content = fix_mtl_texture_paths(mtl_content, new_texture_filename)

                mtl_data = mtl_content.encode('utf-8')
            except Exception as e:
                print(f"Warning: Could not update MTL file references: {e}")

        if model_data:
            if model_path and os.path.exists(model_path):
                os.remove(model_path)

            if not model_filename:
                model_filename = f"{accessory_id}_model.glb"
            else:
                name_part, ext = os.path.splitext(model_filename)
                model_filename = f"{accessory_id}_model{ext}"

            model_path = os.path.join(MODELS_DIR, model_filename)

            model_ext = os.path.splitext(model_filename)[1].lower()
            if model_ext == '.obj' and mtl_data:
                try:
                    obj_content = model_data.decode('utf-8', errors='ignore')
                    new_mtl_name = f"{accessory_id}_material.mtl"
                    obj_content = fix_obj_mtl_path(obj_content, new_mtl_name)
                    model_data = obj_content.encode('utf-8')
                except Exception as e:
                    print(f"Warning: Could not update OBJ file references: {e}")

        if icon_data:
            if icon_path and os.path.exists(icon_path):
                os.remove(icon_path)

            icon_filename = f"{accessory_id}_icon.png"
            icon_path = os.path.join(ICONS_DIR, icon_filename)

        if model_data:
            with open(model_path, 'wb') as f:
                f.write(model_data)

        if texture_data:
            with open(texture_path, 'wb') as f:
                f.write(texture_data)

        if mtl_data:
            with open(mtl_path, 'wb') as f:
                f.write(mtl_data)

        if icon_data:
            with open(icon_path, 'wb') as f:
                f.write(icon_data)

        fb_save_accessory(
            accessory_id, updated_name, updated_type, updated_price,
            model_path, texture_path or "", mtl_path or "", updated_slot, icon_path or ""
        )

        cacheKey = f"accessory_{accessory_id}"
        if cacheKey in accessory_cache:
            del accessory_cache[cacheKey]

        return {"success": True, "data": {"accessoryId": accessory_id, "name": updated_name}}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

def getAccessory(accessoryId: int) -> Optional[Dict[str, Any]]:
    currentTime = time.time()
    cacheKey = f"accessory_{accessoryId}"

    if cacheKey in accessory_cache:
        cached_data, expiry = accessory_cache[cacheKey]
        if currentTime < expiry:
            return cached_data
        else:
            del accessory_cache[cacheKey]

    result = get_accessory(accessoryId)

    if not result:
        return None

    port = os.environ.get('PORT', 8080)
    accessory = {
        "id": result.get("accessory_id"),
        "name": result.get("name"),
        "type": result.get("type"),
        "price": result.get("price"),
        "modelFile": result.get("model_file"),
        "textureFile": result.get("texture_file"),
        "mtlFile": result.get("mtl_file"),
        "equipSlot": result.get("equip_slot"),
        "iconFile": result.get("icon_file"),
        "createdAt": result.get("created_at")
    }

    if accessory["modelFile"]:
        relative_path = os.path.relpath(accessory["modelFile"], VOLUME_PATH)
        accessory["downloadUrl"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

    if accessory["textureFile"]:
        relative_path = os.path.relpath(accessory["textureFile"], VOLUME_PATH)
        accessory["textureUrl"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

    if accessory["mtlFile"]:
        relative_path = os.path.relpath(accessory["mtlFile"], VOLUME_PATH)
        accessory["mtlUrl"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

    if accessory["iconFile"]:
        relative_path = os.path.relpath(accessory["iconFile"], VOLUME_PATH)
        accessory["iconUrl"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

    accessory_cache[cacheKey] = (accessory, currentTime + CACHE_TTL)
    return accessory

def checkItemOwnership(userId: int, itemId: int) -> bool:
    from player_data import getPlayerData

    playerData = getPlayerData(userId)
    if not playerData:
        return False

    owned_accessories = playerData.get("ownedAccessories", [])
    if isinstance(owned_accessories, str):
        try:
            owned_accessories = json.loads(owned_accessories)
        except:
            owned_accessories = []

    return itemId in owned_accessories

async def buyItem(userId: int, itemId: int) -> Dict[str, Any]:
    from currency_system import debitCurrency
    from player_data import getPlayerData, savePlayerData

    try:
        playerData = getPlayerData(userId)
        if not playerData:
            return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}

        owned = playerData.get("ownedAccessories", [])
        if isinstance(owned, str):
            try:
                owned = json.loads(owned)
            except:
                owned = []

        if "ownedAccessories" not in playerData:
            playerData["ownedAccessories"] = []

        if itemId in owned:
            return {"success": False, "error": {"code": "ALREADY_OWNED", "message": "Item already owned"}}

        accessory = getAccessory(itemId)
        if not accessory:
            return {"success": False, "error": {"code": "ITEM_NOT_FOUND", "message": "Item not found"}}

        price = accessory.get("price", 0)

        debitResult = await debitCurrency(userId, price)
        if not debitResult["success"]:
            return debitResult

        owned.append(itemId)
        playerData["ownedAccessories"] = owned

        save_id = await save_tracker.start_save(userId, "buy_item")
        await savePlayerData(userId, playerData)
        await save_tracker.complete_save(save_id, success=True)

        save_accessory_purchase(userId, itemId, price)

        return {"success": True, "data": {"itemId": itemId, "price": price, "newBalance": debitResult["data"]["newBalance"]}}
    except Exception as e:
        print(f"Error in buyItem: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": {"code": "PURCHASE_FAILED", "message": str(e)}}

async def equipAccessory(userId: int, accessoryId: int) -> Dict[str, Any]:
    from player_data import getPlayerData, savePlayerData

    if not checkItemOwnership(userId, accessoryId):
        return {"success": False, "error": {"code": "NOT_OWNED", "message": "Accessory not owned"}}

    accessory = getAccessory(accessoryId)
    if not accessory:
        return {"success": False, "error": {"code": "ITEM_NOT_FOUND", "message": "Accessory not found"}}

    playerData = getPlayerData(userId)
    if not playerData:
        return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}

    avatar = playerData.get("avatar", {})
    if isinstance(avatar, str):
        try:
            avatar = json.loads(avatar)
        except:
            avatar = {}

    if "avatar" not in playerData or not isinstance(playerData["avatar"], dict):
        playerData["avatar"] = {"bodyColors": {}, "accessories": []}
        avatar = playerData["avatar"]

    currentAccessories = avatar.get("accessories", [])

    equipSlot = accessory.get("equipSlot", accessory.get("type"))

    newAccessories = [acc for acc in currentAccessories if acc.get("equipSlot", acc.get("type")) != equipSlot]

    newAccessories.append({
        "id": accessoryId,
        "type": accessory.get("type"),
        "equipSlot": equipSlot,
        "modelFile": accessory.get("modelFile"),
        "textureFile": accessory.get("textureFile"),
        "mtlFile": accessory.get("mtlFile"),
        "downloadUrl": accessory.get("downloadUrl"),
        "textureUrl": accessory.get("textureUrl"),
        "mtlUrl": accessory.get("mtlUrl")
    })

    avatar["accessories"] = newAccessories
    playerData["avatar"] = avatar
    await savePlayerData(userId, playerData)

    return {"success": True, "data": {"equippedAccessory": accessoryId, "slot": equipSlot}}

async def unequipAccessory(userId: int, accessoryId: int) -> Dict[str, Any]:
    from player_data import getPlayerData, savePlayerData

    playerData = getPlayerData(userId)
    if not playerData:
        return {"success": False, "error": {"code": "USER_NOT_FOUND", "message": "User not found"}}

    avatar = playerData.get("avatar", {})
    if isinstance(avatar, str):
        try:
            avatar = json.loads(avatar)
        except:
            avatar = {}

    currentAccessories = avatar.get("accessories", [])

    newAccessories = [acc for acc in currentAccessories if acc.get("id") != accessoryId]

    if len(newAccessories) == len(currentAccessories):
        return {"success": False, "error": {"code": "NOT_EQUIPPED", "message": "Accessory not currently equipped"}}

    avatar["accessories"] = newAccessories
    playerData["avatar"] = avatar
    await savePlayerData(userId, playerData)

    return {"success": True, "data": {"unequippedAccessory": accessoryId}}

def listMarketItems(filter: Optional[Dict] = None, pagination: Optional[Dict] = None) -> Dict[str, Any]:
    filters = []

    if filter:
        if filter.get("type"):
            filters.append(("type", "==", filter["type"]))
        if filter.get("maxPrice"):
            filters.append(("price", "<=", filter["maxPrice"]))

    results = list_accessories(filters if filters else None)

    items = []
    port = os.environ.get('PORT', 8080)

    for result in results:
        item = {
            "id": result.get("accessory_id"),
            "name": result.get("name"),
            "type": result.get("type"),
            "price": result.get("price"),
            "modelFile": result.get("model_file"),
            "textureFile": result.get("texture_file"),
            "mtlFile": result.get("mtl_file"),
            "equipSlot": result.get("equip_slot"),
            "iconFile": result.get("icon_file"),
            "createdAt": result.get("created_at")
        }

        if item["modelFile"]:
            relative_path = os.path.relpath(item["modelFile"], VOLUME_PATH)
            item["downloadUrl"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

        if item["textureFile"]:
            relative_path = os.path.relpath(item["textureFile"], VOLUME_PATH)
            item["textureUrl"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

        if item["mtlFile"]:
            relative_path = os.path.relpath(item["mtlFile"], VOLUME_PATH)
            item["mtlUrl"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

        if item["iconFile"]:
            relative_path = os.path.relpath(item["iconFile"], VOLUME_PATH)
            item["iconUrl"] = f"http://{SERVER_PUBLIC_IP}:{port}/{relative_path}"

        items.append(item)

    items.sort(key=lambda x: (x["name"], x["id"]))

    totalItems = len(items)

    if pagination:
        page = pagination.get("page", 1)
        limit = pagination.get("limit", 20)
        start = (page - 1) * limit
        end = start + limit
        items = items[start:end]

    return {
        "success": True,
        "data": {
            "items": items,
            "total": totalItems,
            "page": pagination.get("page", 1) if pagination else 1,
            "limit": pagination.get("limit", 20) if pagination else len(items)
        }
    }

def getUserAccessories(userId: int) -> List[int]:
    from player_data import getPlayerData

    playerData = getPlayerData(userId)
    if not playerData:
        return []

    owned = playerData.get("ownedAccessories", [])
    if isinstance(owned, str):
        try:
            owned = json.loads(owned)
        except:
            owned = []

    return owned

def deleteAccessory(accessoryId: int) -> Dict[str, Any]:
    result = get_accessory(accessoryId)

    if not result:
        return {"success": False, "error": "Accessory not found"}

    files_to_delete = [
        result.get("model_file"),
        result.get("texture_file"),
        result.get("mtl_file"),
        result.get("icon_file")
    ]

    for file_path in files_to_delete:
        if file_path:
            full_path = file_path
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except:
                    pass

    fb_delete_accessory(accessoryId)

    cacheKey = f"accessory_{accessoryId}"
    if cacheKey in accessory_cache:
        del accessory_cache[cacheKey]

    return {"success": True, "data": {"deletedId": accessoryId}}

def addAccessoryFromDashboard(name: str, accessory_type: str, price: int, equip_slot: str,
                              model_data: bytes, texture_data: Optional[bytes] = None,
                              mtl_data: Optional[bytes] = None, icon_data: Optional[bytes] = None,
                              model_filename: str = None, texture_filename: str = None,
                              mtl_filename: str = None) -> Dict[str, Any]:
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(ICONS_DIR, exist_ok=True)

    try:
        accessory_id = get_next_accessory_id()

        if not model_filename:
            model_filename = f"{accessory_id}_model.glb"
        else:
            name_part, ext = os.path.splitext(model_filename)
            model_filename = f"{accessory_id}_model{ext}"

        model_path = os.path.join(MODELS_DIR, model_filename)

        texture_path = ""
        new_texture_filename = ""
        if texture_data:
            if texture_filename:
                ext = os.path.splitext(texture_filename)[1]
            else:
                ext = ".png"
            new_texture_filename = f"{accessory_id}_texture{ext}"
            texture_path = os.path.join(MODELS_DIR, new_texture_filename)

        mtl_path = ""
        new_mtl_filename = ""
        if mtl_data:
            new_mtl_filename = f"{accessory_id}_material.mtl"
            mtl_path = os.path.join(MODELS_DIR, new_mtl_filename)

            try:
                mtl_content = mtl_data.decode('utf-8', errors='ignore')

                if new_texture_filename:
                    mtl_content = fix_mtl_texture_paths(mtl_content, new_texture_filename)

                mtl_data = mtl_content.encode('utf-8')
            except Exception as e:
                print(f"Warning: Could not update MTL file references: {e}")

        model_ext = os.path.splitext(model_filename)[1].lower()
        if model_ext == '.obj' and new_mtl_filename:
            try:
                obj_content = model_data.decode('utf-8', errors='ignore')
                obj_content = fix_obj_mtl_path(obj_content, new_mtl_filename)
                model_data = obj_content.encode('utf-8')
            except Exception as e:
                print(f"Warning: Could not update OBJ file references: {e}")

        with open(model_path, 'wb') as f:
            f.write(model_data)

        if texture_data:
            with open(texture_path, 'wb') as f:
                f.write(texture_data)

        if mtl_data:
            with open(mtl_path, 'wb') as f:
                f.write(mtl_data)

        icon_path = ""
        if icon_data:
            icon_filename = f"{accessory_id}_icon.png"
            icon_path = os.path.join(ICONS_DIR, icon_filename)
            with open(icon_path, 'wb') as f:
                f.write(icon_data)

        fb_save_accessory(
            accessory_id, name, accessory_type, price,
            model_path, texture_path, mtl_path, equip_slot, icon_path
        )

        return {"success": True, "data": {"accessoryId": accessory_id, "name": name}}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

def clear_accessory_cache():
    global accessory_cache
    accessory_cache.clear()
