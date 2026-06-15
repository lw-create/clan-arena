import os
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_db

SECRET_KEY = os.environ.get("JWT_SECRET", "clan_arena_secret_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer()


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
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
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
    if user["role"] not in ("admin", "monitor"):
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
