from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import get_db
from auth import (
    verify_password, create_access_token,
    require_monitor, hash_password
)


def log_operation(db, admin_id: int, action: str, target_type: str = None,
                   target_id: int = None, detail: str = "", reason: str = ""):
    """写入操作日志"""
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO operation_logs (admin_id, action, target_type, target_id, detail, reason) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (admin_id, action, target_type, target_id, detail, reason)
    )

router = APIRouter(prefix="/api/monitor", tags=["监察员"])


# ========== 监察员登录 ==========

class MonitorLoginRequest(BaseModel):
    username: str
    password: str


class SuperAdminPasswordRequest(BaseModel):
    new_password: str


@router.post("/login")
def monitor_login(req: MonitorLoginRequest):
    """监察员专用登录入口（与用户登录独立）"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM users WHERE username = %s AND role = 'monitor'",
                (req.username,)
            )
            user = cursor.fetchone()

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user["status"] == "frozen":
        raise HTTPException(status_code=403, detail="账号已被冻结")
    if user["status"] == "disabled":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_access_token({"sub": str(user["id"]), "role": user["role"]})
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "must_change_pwd": bool(user.get("must_change_pwd", 0)),
        }
    }


# ========== 监察员：查看超管列表 ==========

@router.get("/super-admins")
def list_super_admins(monitor=Depends(require_monitor)):
    """监察员查看所有超管账号"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, username, status, created_at, must_change_pwd
                FROM users
                WHERE role = 'admin' AND is_super_admin = 1
                ORDER BY id
            """)
            admins = cursor.fetchall()
    return {"super_admins": admins}


# ========== 监察员：冻结/解冻/禁用超管 ==========

@router.put("/super-admins/{user_id}/status")
def update_super_admin_status(user_id: int, status: str, monitor=Depends(require_monitor)):
    """监察员冻结、禁用或恢复超管账号"""
    if status not in ("active", "frozen", "disabled"):
        raise HTTPException(status_code=400, detail="状态只能是 active, frozen 或 disabled")

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            target = cursor.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="用户不存在")
            if target["role"] != "admin" or not target.get("is_super_admin", 0):
                raise HTTPException(status_code=403, detail="只能操作超管账号")

            cursor.execute("UPDATE users SET status = %s WHERE id = %s", (status, user_id))
            log_operation(
                conn, monitor["id"], "monitor_update_status",
                "user", user_id,
                detail=f"监察员将超管 {target['username']} 状态改为 {status}"
            )
    status_text = {"active": "已恢复正常", "frozen": "已冻结", "disabled": "已禁用"}
    return {"message": f"超管账号{status_text.get(status, status)}"}


# ========== 监察员：重置超管密码 ==========

@router.put("/super-admins/{user_id}/password")
def update_super_admin_password(
    user_id: int,
    req: SuperAdminPasswordRequest,
    monitor=Depends(require_monitor),
):
    """监察员修改超管密码"""
    new_password = req.new_password.strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少需要6位")

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            target = cursor.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="用户不存在")
            if target["role"] != "admin" or not target.get("is_super_admin", False):
                raise HTTPException(status_code=403, detail="只能操作超管账号")

            new_hash = hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = %s, plain_password = %s, must_change_pwd = TRUE WHERE id = %s",
                (new_hash, new_password, user_id)
            )
            log_operation(
                conn, monitor["id"], "monitor_reset_password",
                "user", user_id,
                detail=f"监察员修改超管 {target['username']} 的密码"
            )
    return {"message": "超管密码已修改，请通知超管使用新密码登录后修改密码"}


# ========== 监察员：删除超管账号 ==========

@router.delete("/super-admins/{user_id}")
def delete_super_admin(user_id: int, monitor=Depends(require_monitor)):
    """监察员删除超管账号（谨慎操作）"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            target = cursor.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="用户不存在")
            if target["role"] != "admin" or not target.get("is_super_admin", 0):
                raise HTTPException(status_code=403, detail="只能操作超管账号")

            if target["id"] == monitor["id"]:
                raise HTTPException(status_code=400, detail="不能删除自己的账号")

            cursor.execute("DELETE FROM operation_logs WHERE admin_id = %s", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            log_operation(
                conn, monitor["id"], "monitor_delete_user",
                "user", user_id,
                detail=f"监察员删除超管账号 {target['username']}"
            )
    return {"message": "超管账号已删除"}


# ========== 监察员：修改自己的密码 ==========

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
def monitor_change_password(req: ChangePasswordRequest, monitor=Depends(require_monitor)):
    """监察员修改自己的密码"""
    if not verify_password(req.old_password, monitor["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")

    new_hash = hash_password(req.new_password)
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = %s, plain_password = %s, must_change_pwd = 0 WHERE id = %s",
                (new_hash, req.new_password, monitor["id"])
            )
    return {"message": "密码修改成功"}
