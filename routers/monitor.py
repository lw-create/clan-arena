from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from database import get_db
from auth import (
    verify_password, create_access_token,
    require_monitor, hash_password
)
from datetime import datetime
import json
from fastapi.responses import JSONResponse


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


class CreateSuperAdminRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def monitor_login(req: MonitorLoginRequest):
    """监察员专用登录入口（仅允许 monitor 账号可登录）"""
    username = req.username.strip()
    password = req.password.strip()
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM users WHERE username = %s",
                (username,)
            )
            user = cursor.fetchone()

    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 关键：只允许 role == monitor 登录
    if user["role"] != "monitor":
        raise HTTPException(status_code=403, detail="仅允许 monitor 账号使用监察员登录入口")

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
                SELECT id, username, role, status, created_at, must_change_pwd
                FROM users
                WHERE role = 'admin' AND is_super_admin = 1
                ORDER BY id
            """)
            admins = cursor.fetchall()

            # 统计总数
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE role = 'admin' AND is_super_admin = 1")
            count = cursor.fetchone()["cnt"]

    return {"super_admins": admins, "total": count}


# ========== 监察员：新增超管账号 ==========

@router.post("/super-admins")
def create_super_admin(req: CreateSuperAdminRequest, monitor=Depends(require_monitor)):
    """监察员创建超管账号（最多2个）"""
    username = req.username.strip()
    password = req.password.strip()

    if len(username) == 0:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少需要6位")

    with get_db() as conn:
        with conn.cursor() as cursor:
            # 检查超管数量
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM users WHERE role = 'admin' AND is_super_admin = 1")
            count = cursor.fetchone()["cnt"]
            if count >= 2:
                raise HTTPException(status_code=400, detail="超管最多只能有2个")

            # 检查用户名是否存在
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="用户名已存在")

            password_hash = hash_password(password)
            cursor.execute(
                "INSERT INTO users (username, password_hash, plain_password, role, is_super_admin, status, must_change_pwd) "
                "VALUES (%s, %s, %s, 'admin', 1, 'active', 0)",
                (username, password_hash, password)
            )
            new_id = cursor.lastrowid
            log_operation(conn, monitor["id"], "monitor_create_super_admin",
                         "user", new_id,
                         detail=f"监察员创建超管账号: {username}")

    return {"id": new_id, "username": username}


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
                # 监察员只能操作超管
                pass
            if not (target["role"] == "admin" and target.get("is_super_admin", 0)):
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
            if not (target["role"] == "admin" and target.get("is_super_admin", 0)):
                raise HTTPException(status_code=403, detail="只能操作超管账号")

            new_hash = hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = %s, plain_password = %s, must_change_pwd = 1 WHERE id = %s",
                (new_hash, new_password, user_id))
            log_operation(
                conn, monitor["id"], "monitor_reset_password",
                "user", user_id,
                detail=f"监察员修改超管 {target['username']} 的密码"
            )
    return {"message": "超管密码已修改，请通知超管使用新密码登录后修改密码"}


# ========== 监察员：删除超管账号 ==========

@router.delete("/super-admins/{user_id}")
def delete_super_admin(user_id: int, monitor=Depends(require_monitor)):
    """监察员删除超管账号"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            target = cursor.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="用户不存在")
            if not (target["role"] == "admin" and target.get("is_super_admin", 0)):
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
            log_operation(conn, monitor["id"], "monitor_change_own_password",
                           detail="监察员修改自身密码")
    return {"message": "密码修改成功"}


# ========== 监察员：数据导出 ==========

BACKUP_TABLES = [
    "users", "clans", "user_clan", "matches",
    "notifications", "operation_logs", "unknown_clans",
    "rounds", "round_registrations"
]

IMPORT_ORDER = [
    "users", "clans", "rounds", "notifications",
    "user_clan", "matches", "round_registrations",
    "operation_logs", "unknown_clans"
]


def _serialize_row(row):
    """将数据库行转为 JSON 可序列化格式"""
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, bytes):
            result[k] = v.decode('utf-8', errors='replace')
        else:
            result[k] = v
    return result


@router.get("/backup/export")
def export_data(monitor=Depends(require_monitor)):
    """监察员导出所有数据为 JSON"""
    data = {}
    with get_db() as conn:
        with conn.cursor() as cursor:
            for table in BACKUP_TABLES:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                data[table] = [_serialize_row(r) for r in rows]

    export_info = {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "tables": list(data.keys()),
        "row_counts": {t: len(data[t]) for t in data},
        "data": data
    }

    filename = f"clan_arena_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_operation(conn, monitor["id"], "monitor_export_data", detail="监察员导出所有数据")
    return JSONResponse(
        content=export_info,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ========== 监察员：数据导入 ==========

@router.post("/backup/import")
async def import_data(file: UploadFile = File(...), monitor=Depends(require_monitor)):
    """监察员从 JSON 文件导入数据（覆盖现有数据）"""
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="仅支持 .json 文件")

    try:
        content = await file.read()
        backup = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="文件格式错误，无法解析JSON")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件读取失败: {str(e)}")

    if "data" not in backup or not isinstance(backup["data"], dict):
        raise HTTPException(status_code=400, detail="无效的备份文件格式，缺少 data 字段")

    import_data_dict = backup["data"]

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

        try:
            for table in IMPORT_ORDER:
                if table not in import_data_dict:
                    continue

                rows = import_data_dict[table]
                if not rows:
                    cursor.execute(f"DELETE FROM {table}")
                    continue

                columns = list(rows[0].keys())
                col_str = ", ".join(f'`{c}`' for c in columns)
                placeholders = ", ".join(["%s"] * len(columns))

                cursor.execute(f"DELETE FROM {table}")

                for row in rows:
                    values = [row.get(c) for c in columns]
                    cursor.execute(
                        f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})",
                        values
                    )

            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            log_operation(conn, monitor["id"], "monitor_import_data",
                           detail="监察员导入全部数据，覆盖现有数据")

        except Exception as e:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")

    imported_counts = {t: len(import_data_dict.get(t, [])) for t in IMPORT_ORDER if t in import_data_dict}
    return {"message": "数据导入成功", "imported": imported_counts}


# ========== 监察员：操作日志 ==========

@router.get("/operation-logs")
def monitor_operation_logs(monitor=Depends(require_monitor)):
    """监察员查看所有操作日志"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT ol.id, ol.admin_id, ol.action, ol.target_type, ol.target_id,
                       ol.detail, ol.reason, ol.created_at, u.username
                FROM operation_logs ol
                LEFT JOIN users u ON ol.admin_id = u.id
                ORDER BY ol.created_at DESC
                LIMIT 200
            """)
            logs = cursor.fetchall()
    return {"logs": logs}
