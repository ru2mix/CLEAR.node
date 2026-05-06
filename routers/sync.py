import aiosqlite
import asyncio
from ws_router import manager
from cache import workspace_key_cache, rights_cache, accessible_ids_cache
from fastapi import APIRouter, Depends, HTTPException, Request
from database import get_db
from dependencies import verify_user
from utils import get_user_id, log_event
from models import SyncRequest
from datetime import datetime

router = APIRouter(prefix="/sync", tags=["Sync"])

db_write_lock = asyncio.Lock()

@router.get("/workspace_key")
async def get_workspace_key(user = Depends(verify_user), db: aiosqlite.Connection = Depends(get_db)):
    user_id = get_user_id(user)
    
    cached_key = workspace_key_cache.get(user_id)
    if cached_key: return cached_key

    c = await db.cursor()
    try: await c.execute("SELECT IsApproved, IsActive FROM Users WHERE Id = ?", (user_id,))
    except: await c.execute("SELECT IsApproved, 1 FROM Users WHERE Id = ?", (user_id,))
    urow = await c.fetchone()
    
    if not urow or not urow[0]: 
        raise HTTPException(403, "No access to workspace key (not approved)")
    if urow[1] is not None and not bool(urow[1]): 
        raise HTTPException(403, "Account disabled")
        
    await c.execute("SELECT Value FROM ServerSettings WHERE Key = 'MasterKey'")
    row = await c.fetchone()
    
    result = {"key": row[0] if row else ""}
    workspace_key_cache.set(user_id, result)
    return result

@router.get("/my_rights")
async def get_my_rights(user = Depends(verify_user), db: aiosqlite.Connection = Depends(get_db)):
    user_id = get_user_id(user)
    
    cached_rights = rights_cache.get(user_id)
    if cached_rights: return cached_rights

    c = await db.cursor()
    username = user.get("username", "Unknown")
    email = user.get("email", "")

    await c.execute("SELECT IsApproved FROM Users WHERE Id = ?", (user_id,))
    user_row = await c.fetchone()

    if not user_row:
        await c.execute("SELECT COUNT(*) FROM Users")
        total_users_row = await c.fetchone()
        total_users = total_users_row[0]
        
        await c.execute("SELECT COUNT(*) FROM UserGroups WHERE UserId = ?", (user_id,))
        is_invited_row = await c.fetchone()
        is_invited = is_invited_row[0] > 0

        if total_users == 0:
            await c.execute("INSERT INTO Users (Id, Username, Email, IsApproved) VALUES (?, ?, ?, 1)", (user_id, username, email))
            await c.execute("INSERT INTO UserGroups (UserId, GroupId) VALUES (?, 'admin_group')", (user_id,))
            is_approved = True
        elif is_invited:
            await c.execute("INSERT INTO Users (Id, Username, Email, IsApproved) VALUES (?, ?, ?, 1)", (user_id, username, email))
            is_approved = True
        else:
            await c.execute("INSERT INTO Users (Id, Username, Email, IsApproved) VALUES (?, ?, ?, 0)", (user_id, username, email))
            is_approved = False
        await db.commit()
    else:
        is_approved = bool(user_row[0])
        try:
            await c.execute("SELECT IsActive FROM Users WHERE Id = ?", (user_id,))
            act_row = await c.fetchone()
            if act_row and act_row[0] is not None and not bool(act_row[0]):
                raise HTTPException(403, "Account disabled by administrator")
        except HTTPException:
            raise
        except Exception:
            pass
        await c.execute("UPDATE Users SET LastConnect = datetime('now', 'localtime'), Username = ?, Email = ? WHERE Id = ?", (username, email, user_id))
        await db.commit()

    r = { "is_superadmin": False, "can_add": False, "can_edit": False, "can_delete": False, "can_save_local": False, "can_manage_users": False, "can_read_log": False, "can_manage_roles": False, "can_manage_settings": False, "is_pending": not is_approved, "folders": {} }
    
    if not is_approved:
        rights_cache.set(user_id, r)
        return r

    await c.execute("""SELECT g.IsSuperAdmin, g.CanAdd, g.CanEdit, g.CanDelete, g.CanSaveLocal, g.CanManageUsers, g.CanReadLog, g.CanManageRoles, g.CanManageSettings 
                 FROM Groups g JOIN UserGroups ug ON g.Id = ug.GroupId WHERE ug.UserId = ? AND g.IsDeleted = 0""", (user_id,))
    rows = await c.fetchall()
    
    if rows:
        r["is_superadmin"] = any(x[0] for x in rows); r["can_add"] = any(x[1] for x in rows); r["can_edit"] = any(x[2] for x in rows)
        r["can_delete"] = any(x[3] for x in rows); r["can_save_local"] = any(x[4] for x in rows); r["can_manage_users"] = any(x[5] for x in rows)
        r["can_read_log"] = any(x[6] for x in rows); r["can_manage_roles"] = any(x[7] for x in rows); r["can_manage_settings"] = any(x[8] for x in rows)

    if r["is_superadmin"]:
        for k in r.keys(): 
            if k not in ["is_pending", "folders"]: r[k] = True

    if not r["is_superadmin"]:
        await c.execute("""
        WITH RECURSIVE
        EntityAccess AS (
            SELECT e.Id, e.FolderId,
                CASE WHEN EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN 1 ELSE 0 END AS HasRestrict,
                COALESCE((SELECT ep.AccessLevel FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND g.IsDeleted = 0 ORDER BY CASE ep.AccessLevel WHEN 'Нет доступа' THEN 1 WHEN 'none' THEN 1 WHEN 'Чтение / Запись' THEN 2 WHEN 'write' THEN 2 WHEN 'Чтение' THEN 3 WHEN 'read' THEN 3 END LIMIT 1), 'inherited') AS DirectAccess
            FROM Entities e
            WHERE e.FolderId = '' OR e.FolderId IS NULL OR NOT EXISTS (SELECT 1 FROM Entities p WHERE p.Id = e.FolderId)

            UNION ALL

            SELECT e.Id, e.FolderId,
                CASE WHEN ea.HasRestrict = 1 OR EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN 1 ELSE 0 END,
                CASE
                    WHEN EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN
                        COALESCE((SELECT ep.AccessLevel FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND g.IsDeleted = 0 ORDER BY CASE ep.AccessLevel WHEN 'Нет доступа' THEN 1 WHEN 'none' THEN 1 WHEN 'Чтение / Запись' THEN 2 WHEN 'write' THEN 2 WHEN 'Чтение' THEN 3 WHEN 'read' THEN 3 END LIMIT 1), ea.DirectAccess)
                    ELSE ea.DirectAccess
                END
            FROM Entities e
            JOIN EntityAccess ea ON e.FolderId = ea.Id
        )
        SELECT Id, DirectAccess FROM EntityAccess WHERE DirectAccess IN ('Чтение', 'Чтение / Запись', 'read', 'write')
        """, (user_id, user_id))
        rows_folders = await c.fetchall()
        r["folders"] = {row[0]: row[1] for row in rows_folders}

    rights_cache.set(user_id, r)
    return r

@router.get("/revision")
async def get_revision(user = Depends(verify_user), db: aiosqlite.Connection = Depends(get_db)):
    user_id = get_user_id(user)
    try:
        c = await db.cursor()
        await c.execute("UPDATE Users SET LastConnect = ? WHERE Id = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
        await db.commit()
    except Exception:
        pass
    c = await db.cursor()
    await c.execute("SELECT Revision FROM DbVersion LIMIT 1")
    rev_row = await c.fetchone()
    return {"revision": rev_row[0] if rev_row else 0}

@router.get("/accessible_ids")
async def get_accessible_ids(user = Depends(verify_user), db: aiosqlite.Connection = Depends(get_db)):
    user_id = get_user_id(user)
    
    cached_ids = accessible_ids_cache.get(user_id)
    if cached_ids: return cached_ids

    c = await db.cursor()
    await c.execute("SELECT IsApproved FROM Users WHERE Id = ?", (user_id,))
    row = await c.fetchone()
    if not row or not row[0]: return []

    await c.execute("SELECT 1 FROM Groups g JOIN UserGroups ug ON g.Id = ug.GroupId WHERE ug.UserId = ? AND g.IsSuperAdmin = 1 AND g.IsDeleted = 0", (user_id,))
    is_super = await c.fetchone() is not None

    if is_super:
        await c.execute("SELECT Id FROM Entities WHERE Deleted = 0")
    else:
        query = """
        WITH RECURSIVE
        EntityAccess AS (
            SELECT e.Id, e.FolderId,
                CASE WHEN EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN 1 ELSE 0 END AS HasRestrict,
                CASE 
                    WHEN EXISTS (SELECT 1 FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND ep.AccessLevel IN ('Нет доступа', 'none') AND g.IsDeleted = 0) THEN 0
                    WHEN EXISTS (SELECT 1 FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND ep.AccessLevel IN ('Чтение', 'Чтение / Запись', 'read', 'write') AND g.IsDeleted = 0) THEN 1 
                    ELSE 0 
                END AS HasAccess
            FROM Entities e
            WHERE e.FolderId = '' OR e.FolderId IS NULL OR NOT EXISTS (SELECT 1 FROM Entities p WHERE p.Id = e.FolderId)

            UNION ALL

            SELECT e.Id, e.FolderId,
                CASE WHEN ea.HasRestrict = 1 OR EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN 1 ELSE 0 END,
                CASE
                    WHEN EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN
                        CASE 
                            WHEN EXISTS (SELECT 1 FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND ep.AccessLevel IN ('Нет доступа', 'none') AND g.IsDeleted = 0) THEN 0
                            WHEN EXISTS (SELECT 1 FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND ep.AccessLevel IN ('Чтение', 'Чтение / Запись', 'read', 'write') AND g.IsDeleted = 0) THEN 1 
                            ELSE ea.HasAccess 
                        END
                    ELSE ea.HasAccess
                END
            FROM Entities e
            JOIN EntityAccess ea ON e.FolderId = ea.Id
        )
        SELECT e.Id
        FROM Entities e
        JOIN EntityAccess ea ON e.Id = ea.Id
        WHERE e.Deleted = 0 AND (ea.HasRestrict = 0 OR ea.HasAccess = 1)
        """
        await c.execute(query, (user_id, user_id, user_id, user_id))

    rows = await c.fetchall()
    result = [r[0] for r in rows]
    accessible_ids_cache.set(user_id, result)
    return result

@router.get("/pull")
async def pull_data(since_revision: int = 0, request: Request = None, user = Depends(verify_user), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    user_id = get_user_id(user)
    
    await c.execute("SELECT IsApproved FROM Users WHERE Id = ?", (user_id,))
    row = await c.fetchone()
    if not row or not row[0]: return []

    await c.execute("SELECT 1 FROM Groups g JOIN UserGroups ug ON g.Id = ug.GroupId WHERE ug.UserId = ? AND g.IsSuperAdmin = 1 AND g.IsDeleted = 0", (user_id,))
    is_super = await c.fetchone() is not None

    if is_super:
        await c.execute("SELECT Id, EncryptedData, Deleted, Revision FROM Entities WHERE Revision > ?", (since_revision,))
    else:
        query = """
        WITH RECURSIVE
        EntityAccess AS (
            SELECT e.Id, e.FolderId,
                CASE WHEN EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN 1 ELSE 0 END AS HasRestrict,
                CASE 
                    WHEN EXISTS (SELECT 1 FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND ep.AccessLevel IN ('Нет доступа', 'none') AND g.IsDeleted = 0) THEN 0
                    WHEN EXISTS (SELECT 1 FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND ep.AccessLevel IN ('Чтение', 'Чтение / Запись', 'read', 'write') AND g.IsDeleted = 0) THEN 1 
                    ELSE 0 
                END AS HasAccess
            FROM Entities e
            WHERE e.FolderId = '' OR e.FolderId IS NULL OR NOT EXISTS (SELECT 1 FROM Entities p WHERE p.Id = e.FolderId)

            UNION ALL

            SELECT e.Id, e.FolderId,
                CASE WHEN ea.HasRestrict = 1 OR EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN 1 ELSE 0 END,
                CASE
                    WHEN EXISTS (SELECT 1 FROM EntityPermissions WHERE EntityId = e.Id) THEN
                        CASE 
                            WHEN EXISTS (SELECT 1 FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND ep.AccessLevel IN ('Нет доступа', 'none') AND g.IsDeleted = 0) THEN 0
                            WHEN EXISTS (SELECT 1 FROM EntityPermissions ep JOIN UserGroups ug ON ep.GroupId = ug.GroupId JOIN Groups g ON g.Id = ug.GroupId WHERE ep.EntityId = e.Id AND ug.UserId = ? AND ep.AccessLevel IN ('Чтение', 'Чтение / Запись', 'read', 'write') AND g.IsDeleted = 0) THEN 1 
                            ELSE ea.HasAccess 
                        END
                    ELSE ea.HasAccess
                END
            FROM Entities e
            JOIN EntityAccess ea ON e.FolderId = ea.Id
        )
        SELECT e.Id, e.EncryptedData, e.Deleted, e.Revision
        FROM Entities e
        JOIN EntityAccess ea ON e.Id = ea.Id
        WHERE e.Revision > ? AND (ea.HasRestrict = 0 OR ea.HasAccess = 1)
        """
        await c.execute(query, (user_id, user_id, user_id, user_id, since_revision))

    rows = await c.fetchall()
    return [{"id": r[0], "encrypted_data": r[1], "deleted": bool(r[2]), "revision": r[3]} for r in rows]

@router.post("/push")
async def push_data(req: SyncRequest, request: Request, user = Depends(verify_user), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    user_id = get_user_id(user)

    await c.execute("SELECT IsApproved FROM Users WHERE Id = ?", (user_id,))
    row = await c.fetchone()
    if not row or not row[0]: 
        raise HTTPException(403, "Access denied: user is in quarantine.")

    is_super = can_add = can_edit = can_delete = False

    if not user.get("is_local_token"):
        await c.execute("""SELECT MAX(g.IsSuperAdmin), MAX(g.CanAdd), MAX(g.CanEdit), MAX(g.CanDelete) 
                     FROM Groups g JOIN UserGroups ug ON g.Id = ug.GroupId 
                     WHERE ug.UserId = ? AND g.IsDeleted = 0""", (user_id,))
        row = await c.fetchone()
        if not row or (not row[0] and not row[1] and not row[2] and not row[3]):
            await log_event(db, "Warning", user, request.client.host, "Unauthorized data submission attempt.")
            raise HTTPException(403, "No write permissions.")
        
        is_super, can_add, can_edit, can_delete = bool(row[0]), bool(row[1]), bool(row[2]), bool(row[3])
    else:
        is_super = can_add = can_edit = can_delete = True

    await c.execute("SELECT GroupId FROM UserGroups WHERE UserId = ?", (user_id,))
    user_groups_rows = await c.fetchall()
    user_groups = [r[0] for r in user_groups_rows]

    processed_count = 0
    
    await db.commit() 
    async with db_write_lock:
        try:
            await c.execute("BEGIN IMMEDIATE")
            await c.execute("UPDATE DbVersion SET Revision = Revision + 1")
            await c.execute("SELECT Revision FROM DbVersion LIMIT 1")
            new_rev_row = await c.fetchone()
            new_rev = new_rev_row[0]

            for item in req.entities:
                del_int = 1 if item.deleted else 0
                deleted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if item.deleted else None
                await c.execute("SELECT 1 FROM Entities WHERE Id = ?", (item.id,))
                exists = await c.fetchone() is not None

                if not is_super:
                    if del_int == 1 and not can_delete: continue  
                    if exists and del_int == 0 and not can_edit: continue 
                    if not exists and not can_add: continue 

                processed_count += 1
                if exists:
                    await c.execute("UPDATE Entities SET FolderId = ?, EncryptedData = ?, Revision = ?, Deleted = ?, DeletedAt = ? WHERE Id = ?", (item.folder_id, item.encrypted_data, new_rev, del_int, deleted_at, item.id))
                else: 
                    await c.execute("INSERT INTO Entities (Id, FolderId, EncryptedData, Deleted, Revision, DeletedAt) VALUES (?, ?, ?, ?, ?, ?)", (item.id, item.folder_id, item.encrypted_data, del_int, new_rev, deleted_at))
                    if not item.folder_id:
                        for g in user_groups:
                            await c.execute("INSERT OR IGNORE INTO EntityPermissions (EntityId, GroupId, AccessLevel) VALUES (?, ?, 'write')", (item.id, g))
            
            await db.commit()
            await log_event(db, "Data change", user, request.client.host, f"Successfully processed {processed_count} out of {len(req.entities)} objects.")
        except Exception as e:
            await db.rollback()
            print(f"Database error during write: {e}")
            raise HTTPException(500, "Error writing to database.")

    
    
    accessible_ids_cache.clear() 
    await manager.broadcast({"event": "new_revision", "revision": new_rev})
    
    return {"status": "ok", "new_revision": new_rev, "conflicts": []}

@router.get("/deleted")
async def pull_deleted_entities(since_revision: int = 0, user = Depends(verify_user), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    user_id = get_user_id(user)
    
    # Проверка, что пользователь авторизован и не в карантине
    await c.execute("SELECT IsApproved FROM Users WHERE Id = ?", (user_id,))
    row = await c.fetchone()
    if not row or not row[0]: 
        return []

    # Отдаем только те ID, которые были физически удалены после указанной ревизии
    await c.execute("SELECT Id, Revision FROM DeletedEntities WHERE Revision > ?", (since_revision,))
    rows = await c.fetchall()
    
    return [{"id": r[0], "revision": r[1]} for r in rows]