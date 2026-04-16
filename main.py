import os
import asyncio
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

import logger
from database import init_db
from routers import sync, admin_users, admin_groups, admin_system
from ws_router import router as ws_router
from tasks import background_cleanup_task

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    cleanup_task = asyncio.create_task(background_cleanup_task())

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="CLEAR.node", lifespan=lifespan)

#app = FastAPI(title="CLEAR.node", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


app.include_router(sync.router)
app.include_router(admin_users.router)
app.include_router(admin_groups.router)
app.include_router(admin_system.router)
app.include_router(ws_router)

if __name__ == "__main__":
    app_host = os.getenv("HOST", "0.0.0.0")
    app_port = int(os.getenv("PORT", 8001))
    
    uvicorn.run("main:app", host=app_host, port=app_port, reload=False)
