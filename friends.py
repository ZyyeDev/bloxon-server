import time
from typing import List, Dict, Any
from game_database import (
    save_friend,
    get_friends as fb_get_friends,
    delete_friend,
    save_friend_request,
    get_friend_requests_incoming,
    get_friend_requests_outgoing,
    delete_friend_request
)

def sendFriendRequest(fromUserId: int, toUserId: int) -> Dict[str, Any]:
    if fromUserId == toUserId:
        return {"success": False, "error": {"code": "SELF_REQUEST", "message": "Cannot send friend request to yourself"}}

    friends = getFriends(toUserId)
    if fromUserId in friends:
        return {"success": False, "error": {"code": "ALREADY_FRIENDS", "message": "Already friends with this user"}}

    incoming = get_friend_requests_incoming(toUserId)
    if fromUserId in incoming:
        return {"success": False, "error": {"code": "REQUEST_EXISTS", "message": "Friend request already sent"}}

    outgoing = get_friend_requests_outgoing(fromUserId)
    if toUserId in outgoing:
        return {"success": False, "error": {"code": "REQUEST_EXISTS", "message": "Friend request already sent"}}

    my_incoming = get_friend_requests_incoming(fromUserId)
    if toUserId in my_incoming:
        return acceptFriendRequest(fromUserId, toUserId)

    save_friend_request(fromUserId, toUserId)

    return {"success": True, "data": {"fromUserId": fromUserId, "toUserId": toUserId, "timestamp": time.time()}}

def getFriendRequests(userId: int) -> Dict[str, Any]:
    incoming = get_friend_requests_incoming(userId)
    outgoing = get_friend_requests_outgoing(userId)

    return {"success": True, "data": {"incoming": incoming, "outgoing": outgoing}}

def acceptFriendRequest(userId: int, requesterId: int) -> Dict[str, Any]:
    incoming = get_friend_requests_incoming(userId)
    if requesterId not in incoming:
        return {"success": False, "error": {"code": "REQUEST_NOT_FOUND", "message": "Friend request not found"}}

    delete_friend_request(requesterId, userId)

    save_friend(userId, requesterId)
    save_friend(requesterId, userId)

    return {"success": True, "data": {"userId": userId, "friendId": requesterId, "timestamp": time.time()}}

def rejectFriendRequest(userId: int, requesterId: int) -> Dict[str, Any]:
    incoming = get_friend_requests_incoming(userId)
    if requesterId not in incoming:
        return {"success": False, "error": {"code": "REQUEST_NOT_FOUND", "message": "Friend request not found"}}

    delete_friend_request(requesterId, userId)

    return {"success": True, "data": {"userId": userId, "requesterId": requesterId}}

def cancelFriendRequest(userId: int, targetUserId: int) -> Dict[str, Any]:
    outgoing = get_friend_requests_outgoing(userId)
    if targetUserId not in outgoing:
        return {"success": False, "error": {"code": "REQUEST_NOT_FOUND", "message": "Outgoing friend request not found"}}

    delete_friend_request(userId, targetUserId)

    return {"success": True, "data": {"userId": userId, "targetUserId": targetUserId}}

def addFriendDirect(userId: int, friendId: int) -> Dict[str, Any]:
    if userId == friendId:
        return {"success": False, "error": {"code": "SELF_FRIEND", "message": "Cannot add yourself as friend"}}

    save_friend(userId, friendId)
    save_friend(friendId, userId)

    return {"success": True, "data": {"userId": userId, "friendId": friendId}}

def removeFriend(userId: int, friendId: int) -> Dict[str, Any]:
    delete_friend(userId, friendId)
    delete_friend(friendId, userId)

    return {"success": True, "data": {"userId": userId, "friendId": friendId}}

def getFriends(userId: int) -> List[int]:
    return fb_get_friends(userId)
