import aiosqlite
from dependencies import increment_admin_revision, require_manage_users, require_manage_roles
from ws_router import manager
from fastapi import APIRouter, Depends, Request, HTTPException
from cache import auth_cache, rights_cache, accessible_ids_cache, users_cache, pending_cache
from database import get_db
from utils import log_event, get_user_id
from models import UserGroupUpdate

router = APIRouter(prefix="/admin", tags=["Admin Users"])

@router.get("/users")
async def get_all_users(user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    cached_users = users_cache.get("all")
    if cached_users: return cached_users

    c = await db.cursor()
    try:
        await c.execute("""
            SELECT u.Id, u.Username, u.Email, u.LastConnect, ug.GroupId, u.IsActive 
            FROM Users u 
            LEFT JOIN UserGroups ug ON u.Id = ug.UserId 
            WHERE u.IsApproved = 1 ORDER BY u.LastConnect DESC
        """)
        rows = await c.fetchall()
        result = [{"id": r[0], "username": r[1], "email": r[2], "last_connect": r[3], "group_id": r[4] if r[4] else "", "is_active": bool(r[5] if r[5] is not None else 1)} for r in rows]
    except Exception as e:
        print(f"Error fetching users: {e}")
        result = []
    
    users_cache.set("all", result)
    return result

@router.get("/pending_users")
async def get_pending_users(user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    cached_pending = pending_cache.get("all")
    if cached_pending: return cached_pending

    c = await db.cursor()
    await c.execute("SELECT Id, Username, Email, FirstConnect FROM Users WHERE IsApproved = 0 ORDER BY FirstConnect DESC")
    rows = await c.fetchall()
    result = [{"id": r[0], "username": r[1], "email": r[2], "first_connect": r[3]} for r in rows]
    
    pending_cache.set("all", result)
    return result

@router.post("/pending_users/{target_user_id}/approve")
async def approve_user(target_user_id: str, request: Request, user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE Users SET IsApproved = 1, IsActive = 1 WHERE Id = ?", (target_user_id,))
    
    await c.execute("SELECT Value FROM ServerSettings WHERE Key = 'DefaultGroupId'")
    def_grp = await c.fetchone()
    if def_grp and def_grp[0]:
        await c.execute("INSERT OR IGNORE INTO UserGroups (UserId, GroupId) VALUES (?, ?)", (target_user_id, def_grp[0]))
    await db.commit()
    
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    await log_event(db, "Изменение прав", user, request.client.host, f"Одобрена заявка пользователя {target_user_id}")
    
    auth_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    pending_cache.clear()
    users_cache.clear() 
    return {"status": "ok"}

@router.delete("/pending_users/{target_user_id}")
async def reject_user(target_user_id: str, request: Request, user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE Users SET IsActive = 0 WHERE Id = ?", (target_user_id,))
    await db.commit()
    
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    auth_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    pending_cache.clear()
    users_cache.clear() 
    return {"status": "ok"}

@router.post("/pending_users/{target_user_id}/restore")
async def restore_pending_user(target_user_id: str, request: Request, user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE Users SET IsActive = 1 WHERE Id = ?", (target_user_id,))
    await db.commit()
    
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    auth_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    pending_cache.clear()
    users_cache.clear() 
    return {"status": "ok"}

@router.post("/users/{target_user_id}/group")
async def set_user_group(target_user_id: str, req: UserGroupUpdate, request: Request, user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    
    if not req.group_id:
        await c.execute("DELETE FROM UserGroups WHERE UserId = ?", (target_user_id,))
    else:
        await c.execute("DELETE FROM UserGroups WHERE UserId = ?", (target_user_id,))
        await c.execute("INSERT INTO UserGroups (UserId, GroupId) VALUES (?, ?)", (target_user_id, req.group_id))
        
    await db.commit()
    
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    await log_event(db, "Изменение прав", user, request.client.host, f"Изменена группа доступа пользователя {target_user_id}")
    
    groups_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    users_cache.clear()
    auth_cache.clear()
    return {"status": "ok"}

@router.delete("/users/{target_user_id}")
async def ban_user(target_user_id: str, request: Request, user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE Users SET IsActive = 0 WHERE Id = ?", (target_user_id,))
    await db.commit()
    
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    await log_event(db, "Изменение прав", user, request.client.host, f"Учетная запись отключена: {target_user_id}")
    
    auth_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    users_cache.clear()
    return {"status": "ok"}

@router.post("/users/{target_user_id}/restore")
async def restore_user(target_user_id: str, request: Request, user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE Users SET IsActive = 1 WHERE Id = ?", (target_user_id,))
    await db.commit()
    
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    await log_event(db, "Изменение прав", user, request.client.host, f"Учетная запись восстановлена: {target_user_id}")
    
    auth_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    users_cache.clear()
    return {"status": "ok"}