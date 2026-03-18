import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

import logger
from database import init_db
from routers import sync, admin_users, admin_groups, admin_system

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="CLEAR.node - Enterprise Edition", lifespan=lifespan)

app.include_router(sync.router)
app.include_router(admin_users.router)
app.include_router(admin_groups.router)
app.include_router(admin_system.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)