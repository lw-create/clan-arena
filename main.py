import os
import logging
import traceback
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from database import init_db, get_db
from auth import hash_password
from routers import auth as auth_router, player, admin as admin_router, monitor, simulate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="部落对战积分系统", version="4.0")

app.include_router(auth_router.router)
app.include_router(player.router)
app.include_router(admin_router.router)
app.include_router(monitor.router)
app.include_router(simulate.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局异常: {request.method} {request.url}")
    logger.error(f"异常类型: {type(exc).__name__}")
    logger.error(f"异常信息: {str(exc)}")
    logger.error(f"堆栈跟踪:\n{traceback.format_exc()}")
    return {"error": "系统内部错误，请稍后重试", "timestamp": datetime.now().isoformat()}, 500


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning(f"HTTP异常: {request.method} {request.url} - {exc.status_code} {exc.detail}")
    return {"error": exc.detail, "timestamp": datetime.now().isoformat()}, exc.status_code


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"参数校验失败: {request.method} {request.url} - {exc.errors()}")
    return {"error": "参数校验失败", "details": exc.errors(), "timestamp": datetime.now().isoformat()}, 422


@app.on_event("startup")
def startup():
    init_db()

    # 初始密码可由环境变量覆盖；首次部署后请尽快登录修改。
    admin_pwd = os.environ.get("ADMIN_PASSWORD", "admin123456").strip()
    monitor_pwd = os.environ.get("MONITOR_PASSWORD", "monitor123456").strip()

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users
                    (username, password_hash, role, is_super_admin, status, must_change_pwd)
                VALUES
                    (%s, %s, 'admin', TRUE, 'active', FALSE)
                ON DUPLICATE KEY UPDATE
                    password_hash = VALUES(password_hash),
                    role = 'admin',
                    is_super_admin = TRUE,
                    status = 'active',
                    must_change_pwd = FALSE,
                    plain_password = ''
                """,
                ("admin", hash_password(admin_pwd)),
            )

            # 初始化监察员账号（如果不存在）
            cursor.execute(
                """
                INSERT INTO users
                    (username, password_hash, role, must_change_pwd, status)
                VALUES
                    (%s, %s, 'monitor', FALSE, 'active')
                ON DUPLICATE KEY UPDATE
                    password_hash = VALUES(password_hash),
                    role = 'monitor',
                    status = 'active',
                    must_change_pwd = FALSE,
                    plain_password = ''
                """,
                ("monitor", hash_password(monitor_pwd)),
            )


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/healthz")
def healthz():
    """供 Render / UptimeRobot 用的健康检查端点。"""
    return {"status": "ok"}
