
import aiosqlite
import secrets
import hashlib
from dependencies import increment_admin_revision
from ws_router import manager
from fastapi import APIRouter, Depends, Request
from cache import auth_cache, tokens_cache, settings_cache, accessible_ids_cache, rights_cache, users_cache
from database import get_db
from dependencies import require_manage_settings, require_read_log, require_superadmin
from utils import log_event
from models import LocalTokenReq, ServerSettingsReq

router = APIRouter(prefix="/admin", tags=["Admin System"])

@router.get("/tokens")
async def get_tokens(user = Depends(require_manage_settings), db: aiosqlite.Connection = Depends(get_db)):
    cached_tokens = tokens_cache.get("all")
    if cached_tokens: return cached_tokens

    c = await db.cursor()
    await c.execute("SELECT Id, Description, ExpiresAt, CreatedAt FROM LocalTokens")
    rows = await c.fetchall()
    result = [{"id": r[0], "description": r[1], "expires_at": r[2], "created_at": r[3]} for r in rows]
    
    tokens_cache.set("all", result)
    return result

@router.post("/tokens")
async def create_token(req: LocalTokenReq, request: Request, user = Depends(require_manage_settings), db: aiosqlite.Connection = Depends(get_db)):
    raw_token = "cl_" + secrets.token_urlsafe(40)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_id = secrets.token_hex(8)
    
    expires_at = None
    if req.days_valid: expires_at = f"datetime('now', 'localtime', '+{req.days_valid} days')"
    
    c = await db.cursor()
    if expires_at:
        await c.execute(f"INSERT INTO LocalTokens (Id, TokenHash, Description, ExpiresAt) VALUES (?, ?, ?, {expires_at})", (token_id, token_hash, req.description))
    else:
        await c.execute("INSERT INTO LocalTokens (Id, TokenHash, Description, ExpiresAt) VALUES (?, ?, ?, NULL)", (token_id, token_hash, req.description))
    
    token_user_id = f"local_token_{token_id}"
    await c.execute("INSERT INTO Users (Id, Username, Email, IsApproved) VALUES (?, ?, '', 1)", (token_user_id, f"Token: {req.description}"))
    
    await c.execute("SELECT Value FROM ServerSettings WHERE Key = 'DefaultGroupId'")
    def_grp = await c.fetchone()
    if def_grp and def_grp[0]:
        await c.execute("INSERT INTO UserGroups (UserId, GroupId) VALUES (?, ?)", (token_user_id, def_grp[0]))

    await db.commit()
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})
    tokens_cache.clear()
    users_cache.clear()
    await log_event(db, "Настройки", user, request.client.host, f"Создан новый локальный токен: {req.description}")
    return {"status": "ok", "token": raw_token}

@router.delete("/tokens/{token_id}")
async def revoke_token(request: Request, token_id: str, user = Depends(require_manage_settings), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE LocalTokens SET IsActive = 0 WHERE Id = ?", (token_id,))
    await c.execute("UPDATE Users SET IsActive = 0 WHERE Id = ?", (f"local_token_{token_id}",))

    await db.commit()
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})
    await log_event(db, "Настройки", user, request.client.host, f"Отключен локальный токен: {token_id}")
    
    auth_cache.clear()
    tokens_cache.clear()
    users_cache.clear()
    return {"status": "ok"}

@router.post("/tokens/{token_id}/restore")
async def restore_token(request: Request, token_id: str, user = Depends(require_manage_settings), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE LocalTokens SET IsActive = 1 WHERE Id = ?", (token_id,))
    await c.execute("UPDATE Users SET IsActive = 1 WHERE Id = ?", (f"local_token_{token_id}",))

    await db.commit()
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    auth_cache.clear()
    tokens_cache.clear()
    return {"status": "ok"}

@router.get("/settings")
async def get_settings(user = Depends(require_manage_settings), db: aiosqlite.Connection = Depends(get_db)):
    cached_settings = settings_cache.get("all")
    if cached_settings: return cached_settings

    c = await db.cursor()
    await c.execute("SELECT Key, Value FROM ServerSettings")
    rows = await c.fetchall()
    s = {r[0]: r[1] for r in rows}
    result = {"audit_retention_days": int(s.get("AuditRetentionDays", 90)), "deleted_retention_days": int(s.get("DeletedRetentionDays", 30)), "default_group_id": s.get("DefaultGroupId", "")}
    
    settings_cache.set("all", result)
    return result

@router.post("/settings")
async def save_settings(settings: ServerSettingsReq, request: Request, user = Depends(require_manage_settings), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("INSERT OR REPLACE INTO ServerSettings (Key, Value) VALUES ('AuditRetentionDays', ?)", (str(settings.audit_retention_days),))
    await c.execute("INSERT OR REPLACE INTO ServerSettings (Key, Value) VALUES ('DeletedRetentionDays', ?)", (str(settings.deleted_retention_days),))
    await c.execute("INSERT OR REPLACE INTO ServerSettings (Key, Value) VALUES ('DefaultGroupId', ?)", (settings.default_group_id,))

    await db.commit()
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    await log_event(db, "Настройки", user, request.client.host, "Изменены системные настройки.")
    settings_cache.clear()
    return {"status": "ok"}

@router.delete("/wipe")
async def wipe_database(request: Request, user = Depends(require_superadmin), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("UPDATE DbVersion SET Revision = Revision + 1")
    await c.execute("UPDATE Entities SET Deleted = 1, EncryptedData = '', Revision = (SELECT Revision FROM DbVersion LIMIT 1)")

    await db.commit()
    new_admin_rev = await increment_admin_revision(db)
    await manager.broadcast({"event": "admin_revision", "revision": new_admin_rev})

    await log_event(db, "Удаление", user, request.client.host, "ВНИМАНИЕ: ПРОИЗВЕДЕНА ПОЛНАЯ ОЧИСТКА ВСЕХ ДАННЫХ СЕРВЕРА!")
    accessible_ids_cache.clear()
    rights_cache.clear()
    return {"status": "ok"}

@router.get("/auditlog")
async def get_audit_log(user = Depends(require_read_log), db: aiosqlite.Connection = Depends(get_db)):
    c = await db.cursor()
    await c.execute("SELECT Timestamp, EventType, Username, Email, IpAddress, Details FROM AuditLog ORDER BY Id DESC LIMIT 3000")
    rows = await c.fetchall()
    return [{"timestamp": r[0], "event_type": r[1], "username": r[2], "email": r[3], "ip_address": r[4], "details": r[5]} for r in rows]