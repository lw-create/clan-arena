import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import init_db, get_db
from auth import hash_password
from routers import auth as auth_router, player, admin as admin_router, monitor

app = FastAPI(title="部落对战积分系统", version="4.0")

app.include_router(auth_router.router)
app.include_router(player.router)
app.include_router(admin_router.router)
app.include_router(monitor.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def startup():
    init_db()

    # 初始密码可由环境变量覆盖；首次部署后请尽快登录修改。
    admin_pwd = os.environ.get("ADMIN_PASSWORD", "admin123")
    monitor_pwd = os.environ.get("MONITOR_PASSWORD", "monitor123")

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE role = 'admin'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (username, password_hash, plain_password, role, must_change_pwd) "
                    "VALUES (%s, %s, %s, %s, FALSE)",
                    ("admin", hash_password(admin_pwd), admin_pwd, "admin"),
                )

            # 初始化监察员账号（如果不存在）
            cursor.execute("SELECT id FROM users WHERE role = 'monitor'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (username, password_hash, plain_password, role, must_change_pwd, status) "
                    "VALUES (%s, %s, %s, 'monitor', TRUE, 'active')",
                    ("monitor", hash_password(monitor_pwd), monitor_pwd),
                )


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/healthz")
def healthz():
    """供 Render / UptimeRobot 用的健康检查端点。"""
    return {"status": "ok"}
