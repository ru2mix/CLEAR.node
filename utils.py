import aiosqlite
import asyncio

audit_lock = asyncio.Lock()

def get_user_id(user: dict):
    if user.get("is_local_token"): return user.get("email")
    uname = user.get("username", "").strip()
    if uname: return uname
    email = user.get("email", "").strip()
    if email: return email
    return "UnknownUser"

async def log_event(db: aiosqlite.Connection, event_type: str, user: dict, ip: str, details: str):
    async with audit_lock:
        c = await db.cursor()
        username = user.get("username", "Unknown")
        email = user.get("email", "")
    
        await c.execute("INSERT INTO AuditLog (EventType, Username, Email, IpAddress, Details) VALUES (?, ?, ?, ?, ?)", (event_type, username, email, ip, details))
        await c.execute("SELECT Value FROM ServerSettings WHERE Key = 'AuditRetentionDays'")
        row = await c.fetchone()
        retention_days = int(row[0]) if row else 90
        await c.execute(f"DELETE FROM AuditLog WHERE Timestamp < datetime('now', '-{retention_days} days')")
        await db.commit()