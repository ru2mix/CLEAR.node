
import aiosqlite
from dependencies import increment_admin_revision
from ws_router import manager
from fastapi import APIRouter, Depends, Request, HTTPException
from cache import auth_cache, rights_cache, accessible_ids_cache, users_cache, pending_cache
from database import get_db
from dependencies import require_manage_users
from utils import log_event, get_user_id
from models import UserGroupUpdate

router = APIRouter(prefix="/admin", tags=["Admin Users"])

@router.get("/users")
async def get_all_users(user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    cached_users = users_cache.get("all")
    if cached_users: return cached_users

    c = await db.cursor()
    try:
        # МАГИЯ ЗДЕСЬ: Склеиваем обычных юзеров и токены в один список!
        await c.execute("""
            SELECT u.Id, u.Username, u.Email, u.LastConnect, ug.GroupId, u.IsActive 
            FROM Users u 
            LEFT JOIN UserGroups ug ON u.Id = ug.UserId 
            WHERE u.IsApproved = 1 
            
            UNION ALL 
            
            SELECT t.Id, '[Токен] ' || t.Description, 'Локальный Токен', t.CreatedAt, ug.GroupId, t.IsActive 
            FROM LocalTokens t 
            LEFT JOIN UserGroups ug ON t.Id = ug.UserId
            
            ORDER BY LastConnect DESC
        """)
        rows = await c.fetchall()
        result = [{"id": r[0], "username": r[1], "email": r[2], "last_connect": r[3], "group_id": r[4] if r[4] else "", "is_active": bool(r[5] if r[5] is not None else 1)} for r in rows]
    except:
        # Запасной вариант для старых баз без колонки IsActive
        await c.execute("""
            SELECT u.Id, u.Username, u.Email, u.LastConnect, ug.GroupId, 1 
            FROM Users u 
            LEFT JOIN UserGroups ug ON u.Id = ug.UserId 
            WHERE u.IsApproved = 1 
            
            UNION ALL 
            
            SELECT t.Id, '[Токен] ' || t.Description, 'Локальный Токен', t.CreatedAt, ug.GroupId, 1 
            FROM LocalTokens t 
            LEFT JOIN UserGroups ug ON t.Id = ug.UserId
            
            ORDER BY LastConnect DESC
        """)
        rows = await c.fetchall()
        result = [{"id": r[0], "username": r[1], "email": r[2], "last_connect": r[3], "group_id": r[4] if r[4] else "", "is_active": True} for r in rows]

    users_cache.set("all", result)
    return result

@router.put("/users/{target_user_id}/group")
async def update_user_group(target_user_id: str, req: UserGroupUpdate, request: Request, user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("""SELECT 1 FROM Groups g JOIN UserGroups ug ON g.Id = ug.GroupId 
                 WHERE ug.UserId = ? AND g.IsDeleted = 0 AND g.IsSuperAdmin = 1""", (get_user_id(user),))
    caller_is_super = await c.fetchone() is not None

    if req.group_id:
        await c.execute("SELECT IsSuperAdmin FROM Groups WHERE Id = ?", (req.group_id,))
        grp = await c.fetchone()
        if grp and grp[0] == 1 and not caller_is_super:
            raise HTTPException(403, "Только Супер-Администратор может назначать эту группу.")

    await c.execute("DELETE FROM UserGroups WHERE UserId = ?", (target_user_id,))
    if req.group_id:
        await c.execute("INSERT INTO UserGroups (UserId, GroupId) VALUES (?, ?)", (target_user_id, req.group_id))
        
        await c.execute("UPDATE DbVersion SET Revision = Revision + 1")
        await c.execute("SELECT Revision FROM DbVersion LIMIT 1")
        new_rev_row = await c.fetchone()
        new_rev = new_rev_row[0]
        
        await c.execute("SELECT IsSuperAdmin FROM Groups WHERE Id = ?", (req.group_id,))
        grp = await c.fetchone()
        if grp and grp[0] == 1:
            await c.execute("UPDATE Entities SET Revision = ?", (new_rev,))
        else:
            await c.execute("""
                UPDATE Entities SET Revision = ? WHERE Id IN (
                    WITH RECURSIVE children AS (
                        SELECT EntityId AS Id FROM EntityPermissions WHERE GroupId = ?
                        UNION ALL
                        SELECT e.Id FROM Entities e JOIN children c ON e.FolderId = c.Id
                    )
                    SELECT Id FROM children
                )
            """, (new_rev, req.group_id))
            
    await db.commit()
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    await log_event(db, "Изменение прав", user, request.client.host, f"Пользователю {target_user_id} назначена группа: {req.group_id}")
    
    auth_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    users_cache.clear()
    return {"status": "ok"}

@router.delete("/users/{user_id}")
async def delete_user(request: Request, user_id: str, current_user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    admin_id = get_user_id(current_user)
    if str(user_id) == str(admin_id): raise HTTPException(400, "Нельзя отключить самого себя")
    c = await db.cursor()
    await c.execute("UPDATE Users SET IsActive = 0 WHERE Id = ?", (user_id,))

    await db.commit()
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})
    await c.execute("UPDATE LocalTokens SET IsActive = 0 WHERE Id = ?", (user_id,))
    auth_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    users_cache.clear()
    return {"status": "ok"}

@router.post("/users/{user_id}/restore")
async def restore_user(request: Request, user_id: str, current_user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE Users SET IsActive = 1 WHERE Id = ?", (user_id,))

    await db.commit()
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})
    await c.execute("UPDATE LocalTokens SET IsActive = 0 WHERE Id = ?", (user_id,))
    auth_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    users_cache.clear()
    return {"status": "ok"}

@router.get("/pending_users")
async def get_pending_users(user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    cached_pending = pending_cache.get("all")
    if cached_pending: return cached_pending

    c = await db.cursor()
    try:
        await c.execute("SELECT Id, Username, Email, FirstConnect, IsActive FROM Users WHERE IsApproved = 0 ORDER BY FirstConnect DESC")
        rows = await c.fetchall()
        result = [{"id": r[0], "username": r[1], "email": r[2], "first_connect": r[3], "is_active": bool(r[4] if r[4] is not None else 1)} for r in rows]
    except:
        await c.execute("SELECT Id, Username, Email, FirstConnect FROM Users WHERE IsApproved = 0 ORDER BY FirstConnect DESC")
        rows = await c.fetchall()
        result = [{"id": r[0], "username": r[1], "email": r[2], "first_connect": r[3], "is_active": True} for r in rows]
    
    pending_cache.set("all", result)
    return result

@router.post("/pending_users/{target_user_id}/approve")
async def approve_user(target_user_id: str, request: Request, user = Depends(require_manage_users), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE Users SET IsApproved = 1 WHERE Id = ?", (target_user_id,))
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