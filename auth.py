import os
import bcrypt
import jwt
import time
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_db

SECRET_KEY = os.environ.get("JWT_SECRET")
if not SECRET_KEY:
    raise RuntimeError("❌ JWT_SECRET environment variable is required")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer()

_login_attempts = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_DURATION = 300


def _get_client_ip(request: Request) -> str:
    """获取客户端IP地址"""
    if "X-Forwarded-For" in request.headers:
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    if "X-Real-IP" in request.headers:
        return request.headers["X-Real-IP"]
    host = request.client.host if request.client else ""
    return host or "unknown"


def _check_login_rate(request: Request, username: str) -> None:
    """检查登录频率限制"""
    ip = _get_client_ip(request)
    key = f"{ip}:{username}"
    
    now = time.time()
    attempts = _login_attempts.get(key, {"count": 0, "first_attempt": now})
    
    if attempts["count"] >= _MAX_LOGIN_ATTEMPTS:
        if now - attempts["first_attempt"] < _LOCKOUT_DURATION:
            remaining = int(_LOCKOUT_DURATION - (now - attempts["first_attempt"]))
            raise HTTPException(
                status_code=429,
                detail=f"登录失败次数过多，请 {remaining} 秒后再试"
            )
        else:
            attempts = {"count": 0, "first_attempt": now}
    
    _login_attempts[key] = attempts


def _record_failed_login(request: Request, username: str) -> None:
    """记录登录失败"""
    ip = _get_client_ip(request)
    key = f"{ip}:{username}"
    
    now = time.time()
    attempts = _login_attempts.get(key, {"count": 0, "first_attempt": now})
    attempts["count"] += 1
    _login_attempts[key] = attempts


def _clear_login_attempts(username: str) -> None:
    """登录成功后清除失败记录"""
    for key in list(_login_attempts.keys()):
        if key.endswith(f":{username}"):
            del _login_attempts[key]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="无效的认证凭据")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="无效的认证凭据")

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()

    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user["status"] == "frozen":
        raise HTTPException(status_code=403, detail="账号已被冻结，请联系管理员解冻")
    if user["status"] == "disabled":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 确保 id 是 int（JWT sub 是 string）
    user["id"] = int(user["id"])
    return user


def require_admin(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_super_admin(user=Depends(get_current_user)):
    """超管权限检查"""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if not user.get("is_super_admin", False):
        raise HTTPException(status_code=403, detail="需要超管权限")
    return user


def require_monitor(user=Depends(get_current_user)):
    """监察员权限检查：只能管理超管账号"""
    if user["role"] != "monitor":
        raise HTTPException(status_code=403, detail="需要监察员权限")
    return user
