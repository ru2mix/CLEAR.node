import asyncio
import aiosqlite
from config import DB_PATH
from ws_router import manager

async def background_cleanup_task():
    while True:
        try:
            async with aiosqlite.connect(DB_PATH, timeout=15.0) as db:
                c = await db.cursor()
                
                await c.execute("SELECT Value FROM ServerSettings WHERE Key = 'DeletedRetentionDays'")
                row = await c.fetchone()
                retention_days = int(row[0]) if row else 30

                cleanup_query = f"""
                    SELECT Id FROM Entities 
                    WHERE Deleted = 1 
                    AND DeletedAt IS NOT NULL 
                    AND DeletedAt < datetime('now', '-{retention_days} days')
                """
                await c.execute(cleanup_query)
                to_delete = [r[0] for r in await c.fetchall()]

                if to_delete:
                    await c.execute("BEGIN IMMEDIATE")
                    
                    await c.execute("UPDATE DbVersion SET Revision = Revision + 1")
                    await c.execute("SELECT Revision FROM DbVersion LIMIT 1")
                    new_rev = (await c.fetchone())[0]

                    for entity_id in to_delete:
                        await c.execute("INSERT OR REPLACE INTO DeletedEntities (Id, Revision) VALUES (?, ?)", (entity_id, new_rev))
                        await c.execute("DELETE FROM Entities WHERE Id = ?", (entity_id,))
                        await c.execute("DELETE FROM EntityPermissions WHERE EntityId = ?", (entity_id,))

                    await db.commit()
                    await manager.broadcast({"event": "new_revision", "revision": new_rev})
                    print(f"[CLEANUP] Окончательно удалено старых записей: {len(to_delete)}.")

                await c.execute("SELECT Value FROM ServerSettings WHERE Key = 'AuditRetentionDays'")
                audit_row = await c.fetchone()
                audit_retention = int(audit_row[0]) if audit_row else 90

                await c.execute(f"DELETE FROM AuditLog WHERE Timestamp < datetime('now', '-{audit_retention} days')")
                if c.rowcount > 0:
                    print(f"[CLEANUP] Удалено старых записей из лога: {c.rowcount}")
                
                await db.commit()

        except Exception as e:
            print(f"[CLEANUP ERROR] Ошибка при очистке БД: {e}")

        await asyncio.sleep(3600)