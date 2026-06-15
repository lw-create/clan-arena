from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import init_db
from auth import hash_password
from database import get_db
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
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE role = 'admin'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (username, password_hash, plain_password, role, must_change_pwd) "
                    "VALUES (?, ?, ?, ?, 0)",
                    ("admin", hash_password("admin123"), "admin123", "admin")
                )

            # 初始化监察员账号（如果不存在）
            cursor.execute("SELECT id FROM users WHERE role = 'monitor'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (username, password_hash, plain_password, role, must_change_pwd, status) "
                    "VALUES (?, ?, ?, 'monitor', 1, 'active')",
                    ("monitor", hash_password("monitor123"), "monitor123")
                )


@app.get("/")
def index():
    return FileResponse("static/index.html")
