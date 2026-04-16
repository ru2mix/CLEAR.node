import os
import aiosqlite
import secrets
import shutil
from pathlib import Path
from config import DB_PATH

async def get_db():
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as conn:
        yield conn

async def init_db():
    
    old_db = Path("database.db")
    new_db = Path(DB_PATH)
    new_db.parent.mkdir(parents=True, exist_ok=True)
    if old_db.exists() and not new_db.exists():
        print("\n" + "="*50)
        print("🔄 OLD DATABASE DETECTED. STARTING MIGRATION...")
        
        new_db.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            for ext in ["", "-wal", "-shm"]:
                old_file = Path(f"database.db{ext}")
                new_file = Path(f"{DB_PATH}{ext}")
                if old_file.exists():
                    shutil.copy2(old_file, new_file)
                    bak_file = old_file.with_name(old_file.name + ".bak")
                    if bak_file.exists():
                        bak_file.unlink()
                    old_file.rename(bak_file)
                    
                    print(f"  -> {old_file.name} copied to data/ and renamed to {bak_file.name}")
                    
            print("✅ MIGRATION COMPLETED SUCCESSFULLY")
        except Exception as e:
            print(f"❌ MIGRATION ERROR: {e}")
        print("="*50 + "\n")
    async with aiosqlite.connect(DB_PATH, timeout=15.0) as conn:
        c = await conn.cursor()
        
        await c.execute("PRAGMA journal_mode=WAL;")
        
        await c.execute("CREATE TABLE IF NOT EXISTS DbVersion (Revision INTEGER)")
        await c.execute("CREATE TABLE IF NOT EXISTS Entities (Id TEXT PRIMARY KEY, FolderId TEXT DEFAULT '', EncryptedData TEXT, Deleted INTEGER, Revision INTEGER)")
        await c.execute("CREATE TABLE IF NOT EXISTS Users (Id TEXT PRIMARY KEY, Username TEXT, Email TEXT, FirstConnect DATETIME DEFAULT (datetime('now', 'localtime')), LastConnect DATETIME DEFAULT (datetime('now', 'localtime')), IsApproved INTEGER DEFAULT 0)")
        await c.execute("CREATE TABLE IF NOT EXISTS LocalTokens (Id TEXT PRIMARY KEY, TokenHash TEXT, Description TEXT, ExpiresAt DATETIME, CreatedAt DATETIME DEFAULT (datetime('now', 'localtime')))")
        await c.execute("""CREATE TABLE IF NOT EXISTS Groups (Id TEXT PRIMARY KEY, Name TEXT, IsSuperAdmin INTEGER DEFAULT 0, CanManageUsers INTEGER DEFAULT 0, CanSaveLocal INTEGER DEFAULT 0, CanAdd INTEGER DEFAULT 0, CanEdit INTEGER DEFAULT 0, CanDelete INTEGER DEFAULT 0, CanReadLog INTEGER DEFAULT 0, CanManageRoles INTEGER DEFAULT 0, CanManageSettings INTEGER DEFAULT 0, IsHidden INTEGER DEFAULT 0, IsDeleted INTEGER DEFAULT 0)""")
        await c.execute("CREATE TABLE IF NOT EXISTS UserGroups (UserId TEXT, GroupId TEXT, PRIMARY KEY(UserId, GroupId))")
        await c.execute("CREATE TABLE IF NOT EXISTS EntityPermissions (EntityId TEXT, GroupId TEXT, AccessLevel TEXT, PRIMARY KEY(EntityId, GroupId))")
        await c.execute("CREATE TABLE IF NOT EXISTS ServerSettings (Key TEXT PRIMARY KEY, Value TEXT)")

        await c.execute("SELECT Revision FROM DbVersion LIMIT 1")
        if not await c.fetchone():
            await c.execute("INSERT INTO DbVersion (Revision) VALUES (0)")

        await c.execute("SELECT 1 FROM Groups WHERE Id = 'admin_group'")
        if not await c.fetchone():
            await c.execute("INSERT INTO Groups (Id, Name, IsSuperAdmin) VALUES ('admin_group', 'Администратор', 1)")
            await c.execute("INSERT INTO Groups (Id, Name, CanAdd, CanEdit, CanDelete, CanManageUsers) VALUES ('moder_group', 'Модератор', 1, 1, 1, 1)")
            await c.execute("INSERT INTO Groups (Id, Name, CanAdd, CanEdit) VALUES ('user_group', 'Пользователь', 1, 1)")
            await c.execute("INSERT INTO Groups (Id, Name) VALUES ('new_user_group', 'Новый пользователь')")
            await c.execute("INSERT INTO Groups (Id, Name, IsHidden) VALUES ('no_rights_group', 'Без прав', 1)")
            await c.execute("INSERT OR REPLACE INTO ServerSettings (Key, Value) VALUES ('AuditRetentionDays', '90')")
            await c.execute("INSERT OR REPLACE INTO ServerSettings (Key, Value) VALUES ('DeletedRetentionDays', '30')")
            await c.execute("INSERT OR REPLACE INTO ServerSettings (Key, Value) VALUES ('DefaultGroupId', 'new_user_group')")

        await c.execute("""CREATE TABLE IF NOT EXISTS AuditLog (Id INTEGER PRIMARY KEY AUTOINCREMENT, Timestamp DATETIME DEFAULT (datetime('now', 'localtime')), EventType TEXT, Username TEXT, Email TEXT, IpAddress TEXT, Details TEXT)""")
        
        try: await c.execute("ALTER TABLE Users ADD COLUMN IsActive INTEGER DEFAULT 1")
        except: pass
        try: await c.execute("ALTER TABLE LocalTokens ADD COLUMN IsActive INTEGER DEFAULT 1")
        except: pass
        try: await c.execute("ALTER TABLE DbVersion ADD COLUMN AdminRevision INTEGER DEFAULT 0")
        except: pass
        await c.execute("SELECT Value FROM ServerSettings WHERE Key = 'MasterKey'")
        if not await c.fetchone():
            master_key = secrets.token_urlsafe(32)
            await c.execute("INSERT INTO ServerSettings (Key, Value) VALUES ('MasterKey', ?)", (master_key,))
        
        # ---------------------------------------------------
        try:
            await c.execute("UPDATE EntityPermissions SET AccessLevel = 'none' WHERE AccessLevel = 'Нет доступа'")
            await c.execute("UPDATE EntityPermissions SET AccessLevel = 'read' WHERE AccessLevel = 'Чтение'")
            await c.execute("UPDATE EntityPermissions SET AccessLevel = 'write' WHERE AccessLevel = 'Чтение / Запись'")
        except Exception as e:
            print(f"Migration error: {e}")
        # ---------------------------------------------------
        await c.execute("CREATE TABLE IF NOT EXISTS DeletedEntities (Id TEXT PRIMARY KEY, Revision INTEGER)")
        # ---------------------------------------------------
        try:
            await c.execute("ALTER TABLE Entities ADD COLUMN DeletedAt DATETIME")
        except:
            pass
        # ---------------------------------------------------
        await conn.commit()