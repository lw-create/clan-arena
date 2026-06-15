from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from datetime import datetime
from database import get_db
from auth import (
    verify_password, create_access_token, get_current_user,
    require_admin, require_super_admin, hash_password
)

router = APIRouter(prefix="/api", tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "player"


class AdminBindRequest(BaseModel):
    clan_name: str
    clan_code: str
    contact: str = ""


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class SendNotificationRequest(BaseModel):
    content: str


def log_operation(db, admin_id: int, action: str, target_type: str = None,
                   target_id: int = None, detail: str = "", reason: str = ""):
    """写入操作日志"""
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO operation_logs (admin_id, action, target_type, target_id, detail, reason) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (admin_id, action, target_type, target_id, detail, reason)
    )


@router.post("/login")
def login(req: LoginRequest):
    username = req.username.strip()
    password = req.password.strip()
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()

            # 维护模式检查：非管理员在维护期间无法登录
            if user and user["role"] != "admin":
                cursor.execute("SELECT maintenance FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
                current_round = cursor.fetchone()
                if current_round and current_round.get("maintenance"):
                    raise HTTPException(status_code=503, detail="系统维护中，请稍后登录")

    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user["role"] == "monitor":
        raise HTTPException(status_code=403, detail="监察员账号请使用监察员登录入口")

    if user["status"] == "frozen":
        raise HTTPException(status_code=403, detail="账号已被冻结，请联系管理员解冻")
    if user["status"] == "disabled":
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_access_token({"sub": str(user["id"]), "role": user["role"]})
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "is_super_admin": bool(user.get("is_super_admin", 0)),
            "must_change_pwd": bool(user.get("must_change_pwd", 0)),
        }
    }


@router.get("/me")
def get_me(user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            clans = []
            cursor.execute(
                "SELECT c.id as id, c.name, c.code, c.contact, c.score "
                "FROM user_clan uc "
                "JOIN clans c ON uc.clan_id = c.id "
                "WHERE uc.user_id = %s", (user["id"],))
            clans = cursor.fetchall()

            notifications = []
            cursor.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 10")
            notifications = cursor.fetchall()

            # 当前轮次信息
            cursor.execute("SELECT id, round_no, status, opened_at, match_start_time, match_end_time, next_round_time, config_required, maintenance FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current_round = cursor.fetchone()

            # 当前用户在本轮的登记状态
            my_registration = {"registered": False, "registered_at": None}
            has_active_match = False
            active_match_info = None
            if current_round:
                cursor.execute(
                    "SELECT registered_at FROM round_registrations WHERE round_id = %s AND user_id = %s LIMIT 1",
                    (current_round["id"], user["id"])
                )
                reg = cursor.fetchone()
                if reg:
                    my_registration = {"registered": True, "registered_at": reg["registered_at"]}

                # 检查本轮是否有已登记的活跃匹配
                clan_ids = [c["id"] for c in clans]
                if clan_ids:
                    in_placeholder = ",".join(["%s"] * len(clan_ids))
                    cursor.execute(f"""
                        SELECT m.clan_a_id, m.clan_b_id, ca.name as clan_a_name, cb.name as clan_b_name
                        FROM matches m
                        JOIN clans ca ON m.clan_a_id = ca.id
                        JOIN clans cb ON m.clan_b_id = cb.id
                        WHERE m.is_registered = 1
                          AND m.matched_at >= %s
                          AND (m.clan_a_id IN ({in_placeholder}) OR m.clan_b_id IN ({in_placeholder}))
                        ORDER BY m.matched_at DESC LIMIT 1
                    """, [current_round["opened_at"]] + clan_ids + clan_ids)
                    active_match = cursor.fetchone()
                    if active_match:
                        has_active_match = True
                        my_clan_id_set = set(clan_ids)
                        if active_match["clan_a_id"] in my_clan_id_set:
                            opponent_name = active_match["clan_b_name"]
                        else:
                            opponent_name = active_match["clan_a_name"]
                        active_match_info = {"opponent_name": opponent_name}

            # 积分操作指南
            cursor.execute("SELECT content FROM score_guide ORDER BY id DESC LIMIT 1")
            guide_row = cursor.fetchone()
            score_guide = guide_row["content"] if guide_row else ""

    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "status": user["status"],
        "is_super_admin": bool(user.get("is_super_admin", 0)),
        "must_change_pwd": bool(user.get("must_change_pwd", 0)),
        "current_round": current_round,
        "my_registration": my_registration,
        "has_active_match": has_active_match,
        "active_match_info": active_match_info,
        "clans": clans,
        "notifications": notifications,
        "score_guide": score_guide,
    }


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, user=Depends(get_current_user)):
    if not verify_password(req.old_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")

    password_hash = hash_password(req.new_password)
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = %s, plain_password = %s, must_change_pwd = 0 WHERE id = %s",
                (password_hash, req.new_password, user["id"])
            )
    return {"message": "密码修改成功"}


@router.post("/skip-change-pwd")
def skip_change_pwd(user=Depends(get_current_user)):
    """用户选择跳过修改密码"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET must_change_pwd = 0 WHERE id = %s",
                (user["id"],)
            )
    return {"message": "已跳过密码修改"}


@router.put("/clan/{clan_id}/contact")
def update_clan_contact(clan_id: int, contact: str, user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM user_clan WHERE user_id = %s AND clan_id = %s", (user["id"], clan_id))
            if not cursor.fetchone():
                raise HTTPException(status_code=403, detail="您未绑定该部落")
            cursor.execute("UPDATE clans SET contact = %s WHERE id = %s", (contact, clan_id))
    return {"message": "联系人已更新"}


# ========== 管理员：用户管理 ==========

@router.post("/admin/users")
def create_user(req: CreateUserRequest, admin=Depends(require_admin)):
    if req.role not in ("player", "admin"):
        raise HTTPException(status_code=400, detail="角色只能是 player 或 admin")

    # 只有超管可以创建管理员账号
    if req.role == "admin" and not admin.get("is_super_admin", 0):
        raise HTTPException(status_code=403, detail="只有超管可以创建管理员账号")

    password_hash = hash_password(req.password)
    try:
        with get_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, plain_password, role, must_change_pwd) VALUES (%s, %s, %s, %s, 1)",
                    (req.username, password_hash, req.password, req.role)
                )
                user_id = cursor.lastrowid
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(status_code=400, detail="用户名已存在")
        raise

    return {"id": user_id, "username": req.username, "role": req.role}


@router.get("/admin/users")
def list_users(admin=Depends(require_admin)):
    """管理员查看用户列表（monitor账号不可见）"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT u.id, u.username, u.plain_password, u.role, u.status, u.must_change_pwd,
                       u.is_super_admin, u.created_at
                FROM users u
                WHERE u.role != 'monitor'
                ORDER BY u.id
            """)
            users = cursor.fetchall()
            for u in users:
                cursor.execute("""
                    SELECT c.id, c.name, c.code
                    FROM user_clan uc
                    JOIN clans c ON uc.clan_id = c.id
                    WHERE uc.user_id = %s
                """, (u["id"],))
                u["clans"] = cursor.fetchall()
                u["is_super_admin"] = bool(u.get("is_super_admin", 0))
                u["must_change_pwd"] = bool(u.get("must_change_pwd", 0))

    return {"users": users}


@router.delete("/admin/users/{user_id}")
def delete_user(user_id: int, admin=Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT is_super_admin, role FROM users WHERE id = %s", (user_id,))
            target = cursor.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="用户不存在")
            if target["is_super_admin"]:
                raise HTTPException(status_code=403, detail="不能删除超管账号，请联系监察员")
            if target["role"] == "monitor":
                raise HTTPException(status_code=403, detail="不能删除监察员账号")
            # 普通管理员之间不能互相删除
            if target["role"] == "admin" and not admin.get("is_super_admin", 0):
                raise HTTPException(status_code=403, detail="管理员之间不能互相操作")

            # 频率限制：每天最多删3个用户
            today = datetime.utcnow().date()
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM operation_logs "
                "WHERE admin_id = %s AND action = 'delete_user' AND DATE(created_at) = %s",
                (admin["id"], today)
            )
            if cursor.fetchone()["cnt"] >= 3:
                raise HTTPException(status_code=429, detail="今日删除用户已达上限（最多3个），请明天再试")

            # 先删除外键关联的记录
            cursor.execute("DELETE FROM operation_logs WHERE admin_id = %s", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            log_operation(conn, admin["id"], "delete_user", "user", user_id,
                           detail=f"删除用户ID {user_id}")

    return {"message": "用户已删除"}


@router.put("/admin/users/{user_id}/status")
def update_user_status(user_id: int, status: str, admin=Depends(require_admin)):
    if status not in ("active", "frozen", "disabled"):
        raise HTTPException(status_code=400, detail="状态只能是 active, frozen 或 disabled")

    with get_db() as conn:
        with conn.cursor() as cursor:
            # 不能禁用或冻结自己
            if user_id == admin["id"] and status in ("frozen", "disabled"):
                raise HTTPException(status_code=400, detail="不能禁用或冻结自己的账号")
            cursor.execute("SELECT is_super_admin, role FROM users WHERE id = %s", (user_id,))
            target = cursor.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="用户不存在")
            # 超管之间不能互相操作
            if target["is_super_admin"] and admin.get("is_super_admin", 0):
                raise HTTPException(status_code=403, detail="超管之间不能互相操作，请联系监察员")
            if target["is_super_admin"] and not admin.get("is_super_admin", 0):
                raise HTTPException(status_code=403, detail="无法操作超管账号，请联系监察员")
            if target["role"] == "admin" and not admin.get("is_super_admin", 0) and not target["is_super_admin"]:
                raise HTTPException(status_code=403, detail="管理员之间不能互相操作")

            cursor.execute("UPDATE users SET status = %s WHERE id = %s", (status, user_id))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="用户不存在")
            log_operation(conn, admin["id"], "update_status", "user", user_id,
                           detail=f"状态改为 {status}")

    status_text = {"active": "已启用/解冻", "frozen": "已冻结", "disabled": "已禁用"}
    return {"message": f"用户{status_text.get(status, status)}"}


@router.put("/admin/users/{user_id}/password")
def reset_user_password(user_id: int, admin=Depends(require_admin)):
    """管理员重置用户密码为000000"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT is_super_admin FROM users WHERE id = %s", (user_id,))
            target = cursor.fetchone()
            if target and target["is_super_admin"] and not admin.get("is_super_admin", 0):
                raise HTTPException(status_code=403, detail="只有超管可以修改超管账号密码")

            new_password = "000000"
            password_hash = hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = %s, plain_password = %s, must_change_pwd = 1 WHERE id = %s",
                (password_hash, new_password, user_id)
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="用户不存在")
            log_operation(conn, admin["id"], "reset_password", "user", user_id,
                           detail="重置密码为默认密码")
    return {"message": "密码已重置为000000，请通知用户登录后修改密码"}


@router.post("/admin/users/{user_id}/bind")
def admin_bind_clan(req: AdminBindRequest, user_id: int, admin=Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM clans WHERE code = %s", (req.clan_code,))
            existing_clan = cursor.fetchone()
            if not existing_clan:
                cursor.execute(
                    "INSERT INTO clans (name, code, contact) VALUES (%s, %s, %s)",
                    (req.clan_name, req.clan_code, req.contact)
                )
                clan_id = cursor.lastrowid
            else:
                clan_id = existing_clan["id"]

            cursor.execute("SELECT id FROM user_clan WHERE user_id = %s AND clan_id = %s", (user_id, clan_id))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="该用户已绑定此部落")

            cursor.execute(
                "INSERT INTO user_clan (user_id, clan_id) VALUES (%s, %s)",
                (user_id, clan_id)
            )
            log_operation(conn, admin["id"], "bind_clan", "user", user_id,
                           detail=f"绑定部落 {req.clan_name}({req.clan_code})")

    return {"message": "部落绑定成功", "clan_id": clan_id}


@router.delete("/admin/users/{user_id}/unbind/{clan_id}")
def admin_unbind_clan(user_id: int, clan_id: int, admin=Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM user_clan WHERE user_id = %s AND clan_id = %s", (user_id, clan_id))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=400, detail="该用户未绑定此部落")
            log_operation(conn, admin["id"], "unbind_clan", "user", user_id,
                           detail=f"解绑部落ID {clan_id}")
    return {"message": "部落解绑成功"}


# ========== 通知 ==========

@router.post("/admin/notifications")
def send_notification(req: SendNotificationRequest, admin=Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO notifications (content) VALUES (%s)", (req.content,))
            log_operation(conn, admin["id"], "send_notification", detail=req.content[:50])
    return {"message": "通知已发送"}


# ========== 超管权限管理 ==========

@router.put("/admin/users/{user_id}/super-admin")
def set_super_admin(user_id: int, is_super: bool, admin=Depends(require_super_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET is_super_admin = %s WHERE id = %s", (1 if is_super else 0, user_id))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="用户不存在")
            log_operation(conn, admin["id"], "set_super_admin", "user", user_id,
                           detail=f"超管权限 {'开启' if is_super else '关闭'}")
    return {"message": f"超管权限已{'开启' if is_super else '关闭'}"}


# ========== 管理员：积分调整 ==========

@router.put("/admin/clans/{clan_id}/score")
def adjust_score(clan_id: int, delta: int, reason: str = "", admin=Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name, score FROM clans WHERE id = %s", (clan_id,))
            clan = cursor.fetchone()
            if not clan:
                raise HTTPException(status_code=404, detail="部落不存在")
            new_score = clan["score"] + delta
            cursor.execute("UPDATE clans SET score = %s WHERE id = %s", (new_score, clan_id))
            log_operation(conn, admin["id"], "adjust_score", "clan", clan_id,
                           detail=f"{clan['name']} 积分 {clan['score']} -> {new_score} (delta={delta})", reason=reason)
    return {"message": f"积分已调整，当前积分: {new_score}"}


# ========== 操作日志 ==========

@router.get("/admin/operation-logs")
def admin_operation_logs(admin=Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT ol.*, u.username
                FROM operation_logs ol
                LEFT JOIN users u ON ol.admin_id = u.id
                ORDER BY ol.created_at DESC
                LIMIT 100
            """)
            logs = cursor.fetchall()
    return {"logs": logs}
