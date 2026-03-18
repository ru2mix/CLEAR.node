
import aiosqlite
from fastapi import APIRouter, Depends, Request, HTTPException
from cache import groups_cache, rights_cache, accessible_ids_cache
from database import get_db
from dependencies import require_manage_roles
from utils import log_event
from models import GroupCreate, PermissionSetReq, InviteReq, GroupUsersReq

router = APIRouter(prefix="/admin", tags=["Admin Groups"])

@router.get("/groups")
async def get_groups(user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    cached_groups = groups_cache.get("all")
    if cached_groups: return cached_groups

    c = await db.cursor()
    await c.execute("SELECT Id, Name, IsSuperAdmin, CanManageUsers, CanSaveLocal, CanAdd, CanEdit, CanDelete, IsHidden, IsDeleted, CanReadLog, CanManageRoles, CanManageSettings FROM Groups")
    rows = await c.fetchall()
    result = [{"id": r[0], "name": r[1], "is_superadmin": bool(r[2]), "can_manage_users": bool(r[3]), "can_save_local": bool(r[4]),
             "can_add": bool(r[5]), "can_edit": bool(r[6]), "can_delete": bool(r[7]), "is_hidden": bool(r[8]), "is_deleted": bool(r[9]),
             "can_read_log": bool(r[10]), "can_manage_roles": bool(r[11]), "can_manage_settings": bool(r[12])} for r in rows]
    
    groups_cache.set("all", result)
    return result

@router.post("/groups")
async def create_group(g: GroupCreate, request: Request, user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    from utils import get_user_id
    await c.execute("""SELECT 1 FROM Groups g JOIN UserGroups ug ON g.Id = ug.GroupId 
                 WHERE ug.UserId = ? AND g.IsDeleted = 0 AND g.IsSuperAdmin = 1""", (get_user_id(user),))
    caller_is_super = await c.fetchone() is not None

    if g.is_superadmin and not caller_is_super:
        raise HTTPException(403, "Только Супер-Администратор может создавать такие группы.")
        
    await c.execute("SELECT IsSuperAdmin FROM Groups WHERE Id = ?", (g.id,))
    existing = await c.fetchone()
    if existing and existing[0] == 1 and not caller_is_super:
        raise HTTPException(403, "Вы не можете изменять группу Супер-Администратора.")
    await c.execute("""INSERT OR REPLACE INTO Groups (Id, Name, IsSuperAdmin, CanManageUsers, CanSaveLocal, CanAdd, CanEdit, CanDelete, IsHidden, IsDeleted, CanReadLog, CanManageRoles, CanManageSettings) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
              (g.id, g.name, int(g.is_superadmin), int(g.can_manage_users), int(g.can_save_local), int(g.can_add), int(g.can_edit), int(g.can_delete), 
               int(g.is_hidden), int(g.is_deleted), int(g.can_read_log), int(g.can_manage_roles), int(g.can_manage_settings)))
    await db.commit()
    await log_event(db, "Изменение прав", user, request.client.host, f"Обновлена группа: '{g.name}'")
    
    groups_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    return {"status": "ok"}

@router.delete("/groups/{group_id}")
async def delete_group(group_id: str, request: Request, user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("SELECT Name FROM Groups WHERE Id = ?", (group_id,))
    row = await c.fetchone()
    g_name = row[0] if row else "Unknown"
    await c.execute("UPDATE Groups SET IsDeleted = 1 WHERE Id = ?", (group_id,))
    await db.commit()
    await log_event(db, "Удаление", user, request.client.host, f"Мягкое удаление группы: '{g_name}'")
    
    groups_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    return {"status": "ok"}

@router.delete("/groups/{group_id}/permissions")
async def clear_group_permissions(group_id: str, request: Request, user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE DbVersion SET Revision = Revision + 1")
    await c.execute("SELECT Revision FROM DbVersion LIMIT 1")
    new_rev_row = await c.fetchone()
    new_rev = new_rev_row[0]
    await c.execute("""
        UPDATE Entities SET Revision = ? WHERE Id IN (
            WITH RECURSIVE children AS (
                SELECT EntityId AS Id FROM EntityPermissions WHERE GroupId = ?
                UNION ALL
                SELECT e.Id FROM Entities e JOIN children c ON e.FolderId = c.Id
            )
            SELECT Id FROM children
        )
    """, (new_rev, group_id))
    
    await c.execute("DELETE FROM EntityPermissions WHERE GroupId = ?", (group_id,))
    await db.commit()
    
    groups_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    return {"status": "ok"}

@router.get("/permissions")
async def get_permissions(user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("SELECT EntityId, GroupId, AccessLevel FROM EntityPermissions")
    rows = await c.fetchall()
    return [{"entity_id": r[0], "group_id": r[1], "access_level": r[2]} for r in rows]

@router.post("/permissions")
async def set_permission(perm: PermissionSetReq, request: Request, user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("SELECT AccessLevel FROM EntityPermissions WHERE EntityId = ? AND GroupId = ?", (perm.entity_id, perm.group_id))
    current_perm = await c.fetchone()
    if current_perm and current_perm[0] == perm.access_level:
        return {"status": "ok"}
        
    await c.execute("INSERT OR REPLACE INTO EntityPermissions (EntityId, GroupId, AccessLevel) VALUES (?, ?, ?)", (perm.entity_id, perm.group_id, perm.access_level))
    
    await c.execute("UPDATE DbVersion SET Revision = Revision + 1")
    await c.execute("SELECT Revision FROM DbVersion LIMIT 1")
    new_rev_row = await c.fetchone()
    new_rev = new_rev_row[0]
    await c.execute("""
        UPDATE Entities SET Revision = ? WHERE Id IN (
            WITH RECURSIVE children AS (
                SELECT Id FROM Entities WHERE Id = ?
                UNION ALL
                SELECT e.Id FROM Entities e JOIN children c ON e.FolderId = c.Id
            )
            SELECT Id FROM children
        )
    """, (new_rev, perm.entity_id))
    
    await db.commit()
    
    groups_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    return {"status": "ok"}

@router.post("/invite")
async def invite_user(req: InviteReq, request: Request, user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("INSERT OR IGNORE INTO UserGroups (UserId, GroupId) VALUES (?, ?)", (req.user_id, req.group_id))
    await db.commit()
    await c.execute("SELECT Name FROM Groups WHERE Id = ?", (req.group_id,))
    row = await c.fetchone()
    group_name = row[0] if row else "Unknown"
    await log_event(db, "Изменение прав", user, request.client.host, f"Отправлено приглашение пользователю {req.user_id} (Группа: {group_name})")
    
    groups_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    return {"status": "ok"}

@router.get("/groups/{group_id}/users")
async def get_group_users(group_id: str, user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("SELECT UserId FROM UserGroups WHERE GroupId = ?", (group_id,))
    rows = await c.fetchall()
    return [r[0] for r in rows]

@router.post("/groups/{group_id}/users")
async def set_group_users(group_id: str, req: GroupUsersReq, request: Request, user = Depends(require_manage_roles), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("DELETE FROM UserGroups WHERE GroupId = ?", (group_id,))
    for uid in req.user_ids: 
        await c.execute("INSERT INTO UserGroups (UserId, GroupId) VALUES (?, ?)", (uid, group_id))
    await db.commit()
    await log_event(db, "Изменение прав", user, request.client.host, f"Обновлен состав пользователей (Кол-во: {len(req.user_ids)}) для группы ID: {group_id}")
    
    groups_cache.clear()
    rights_cache.clear()
    accessible_ids_cache.clear()
    return {"status": "ok"}