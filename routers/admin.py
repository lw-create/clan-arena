import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
from database import get_db
from auth import require_admin, require_super_admin


def log_operation(db, admin_id: int, action: str, target_type: str = None,
                   target_id: int = None, detail: str = "", reason: str = ""):
    """写入操作日志"""
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO operation_logs (admin_id, action, target_type, target_id, detail, reason) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (admin_id, action, target_type, target_id, detail, reason)
    )

router = APIRouter(prefix="/api/admin", tags=["管理员"])


class RoundTimeRequest(BaseModel):
    match_start_time: Optional[str] = None
    match_end_time: Optional[str] = None
    next_round_time: Optional[str] = None
    config_required: Optional[bool] = None
    maintenance: Optional[bool] = None


@router.get("/clans")
def list_clans(admin=Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT c.id, c.name, c.code, c.contact, c.score, c.created_at,
                       (SELECT COUNT(*) FROM user_clan uc WHERE uc.clan_id = c.id) as member_count
                FROM clans c
                WHERE c.code NOT LIKE %s
                ORDER BY c.score DESC
            """, ('UNREG_%',))
            clans = cursor.fetchall()
    return {"clans": clans}


@router.post("/score/adjust")
def adjust_score(clan_id: int, delta: int, reason: str, admin=Depends(require_admin)):
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="请填写调整理由")

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, score FROM clans WHERE id = %s", (clan_id,))
            clan = cursor.fetchone()
            if not clan:
                raise HTTPException(status_code=404, detail="部落不存在")

            before_score = clan["score"]
            after_score = before_score + delta
            cursor.execute("UPDATE clans SET score = %s WHERE id = %s", (after_score, clan_id))
            log_operation(
                conn,
                admin["id"],
                "adjust_score",
                "clan",
                clan_id,
                f"调整部落 {clan['name']} 积分：{before_score} -> {after_score}（{delta:+d}）",
                reason,
            )

    return {
        "message": "积分调整成功",
        "clan_id": clan_id,
        "clan_name": clan["name"],
        "before": before_score,
        "after": after_score,
        "delta": delta,
    }


@router.get("/matches")
def list_matches(admin=Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, round_no, status, opened_at, closed_at FROM rounds ORDER BY opened_at ASC")
            all_rounds = cursor.fetchall()
            current_round_id = None
            for r in all_rounds:
                if r["status"] == "open":
                    current_round_id = r["id"]
                    break

            cursor.execute("""
                SELECT m.id, m.clan_a_id, m.clan_b_id, m.winner_id, m.loser_id,
                       m.score_before_a, m.score_before_b, m.is_registered, m.remark,
                       m.config_remark, m.matched_at, m.created_by, m.confirmed_by,
                       ca.name as clan_a_name, cb.name as clan_b_name,
                       cw.name as winner_name, cl.name as loser_name
                FROM matches m
                JOIN clans ca ON m.clan_a_id = ca.id
                JOIN clans cb ON m.clan_b_id = cb.id
                LEFT JOIN clans cw ON m.winner_id = cw.id
                LEFT JOIN clans cl ON m.loser_id = cl.id
                ORDER BY m.matched_at DESC
                LIMIT 100
            """)
            matches = cursor.fetchall()

            for m in matches:
                m["round_no"] = None
                m["is_current_round"] = False
                for r in all_rounds:
                    if m["matched_at"] >= r["opened_at"]:
                        if r["closed_at"] is None or m["matched_at"] < r["closed_at"]:
                            m["round_no"] = r["round_no"]
                            m["is_current_round"] = (r["id"] == current_round_id)
                            break

    return {"matches": matches}


@router.get("/match-stats")
def match_stats(admin=Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as total FROM clans WHERE code NOT LIKE %s", ('UNREG_%',))
            total_clans = cursor.fetchone()["total"]

            cursor.execute("""
                SELECT remark, COUNT(*) as cnt
                FROM matches
                WHERE is_registered = 0 AND remark IS NOT NULL AND remark != ''
                GROUP BY remark
                ORDER BY cnt DESC
                LIMIT 20
            """)
            unknown_stats = cursor.fetchall()

            stats = {
                "total_clans": total_clans,
                "unknown_clan_matches": unknown_stats,
            }
    return {"stats": stats}


ACTION_NAMES = {
    "delete_user": "删除用户",
    "update_status": "修改用户状态",
    "reset_password": "重置密码",
    "bind_clan": "绑定部落",
    "unbind_clan": "解绑部落",
    "set_super_admin": "设置超管权限",
    "adjust_score": "调整积分",
    "send_notification": "发送通知",
    "auto_freeze": "自动冻结",
    "update_score_guide": "更新积分指南",
}


@router.get("/operation-logs")
def operation_logs(admin=Depends(require_admin)):
    """查看所有操作日志（公示）"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT ol.id, ol.admin_id, ol.action, ol.target_type, ol.target_id,
                       ol.detail, ol.reason, ol.created_at, u.username,
                       (SELECT GROUP_CONCAT(c.name, ', ')
                        FROM user_clan uc JOIN clans c ON uc.clan_id = c.id
                        WHERE uc.user_id = ol.admin_id) as admin_clans
                FROM operation_logs ol
                LEFT JOIN users u ON ol.admin_id = u.id
                ORDER BY ol.created_at DESC
                LIMIT 100
            """)
            logs = cursor.fetchall()
            for log in logs:
                log["action_cn"] = ACTION_NAMES.get(log["action"], log["action"])
    return {"logs": logs}


@router.get("/unknown-clans")
def unknown_clans(admin=Depends(require_admin)):
    """查看陌生部落数据库"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, name, code, tags, encounter_count, last_seen, created_at
                FROM unknown_clans
                ORDER BY last_seen DESC
                LIMIT 200
            """)
            data = cursor.fetchall()
    return {"unknown_clans": data}


# ========== 轮次管理 ==========

@router.post("/round/open")
def open_round(req: RoundTimeRequest = None, admin=Depends(require_admin)):
    """开启新一轮，可同时设置匹配时间和配置必填"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="当前有未关闭的轮次，请先关闭")

            match_start = req.match_start_time if req else None
            match_end = req.match_end_time if req else None
            next_round = req.next_round_time if req else None
            config_req = req.config_required if req else False

            cursor.execute("""
                INSERT INTO rounds (round_no, status, opened_by, match_start_time, match_end_time, next_round_time, config_required)
                SELECT COALESCE(MAX(round_no), 0) + 1, 'open', %s, %s, %s, %s, %s
                FROM rounds
            """, (admin["id"], match_start, match_end, next_round, 1 if config_req else 0))
            round_id = cursor.lastrowid

    return {"message": "新一轮已开启", "round_id": round_id}


@router.put("/round/settings")
def update_round_settings(req: RoundTimeRequest, admin=Depends(require_admin)):
    """更新当前轮次的设置（时间、配置必填等）"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current = cursor.fetchone()
            if not current:
                raise HTTPException(status_code=400, detail="当前没有开启的轮次")

            updates = []
            params = []
            if req.match_start_time is not None:
                updates.append("match_start_time = %s")
                params.append(req.match_start_time)
            if req.match_end_time is not None:
                updates.append("match_end_time = %s")
                params.append(req.match_end_time)
            if req.next_round_time is not None:
                updates.append("next_round_time = %s")
                params.append(req.next_round_time)
            if req.config_required is not None:
                updates.append("config_required = %s")
                params.append(1 if req.config_required else 0)
            if req.maintenance is not None:
                updates.append("maintenance = %s")
                params.append(1 if req.maintenance else 0)

            if not updates:
                raise HTTPException(status_code=400, detail="没有需要更新的字段")

            params.append(current["id"])
            cursor.execute(f"UPDATE rounds SET {', '.join(updates)} WHERE id = %s", params)

    return {"message": "轮次设置已更新"}


@router.post("/round/close")
def close_round(admin=Depends(require_admin)):
    """关闭当前轮次，并冻结连续7轮未登记的用户"""
    frozen_count = 0
    to_freeze = []
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, round_no FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current = cursor.fetchone()
            if not current:
                raise HTTPException(status_code=400, detail="当前没有开启的轮次")

            # 关闭当前轮次
            cursor.execute("""
                UPDATE rounds SET status = 'closed', closed_by = %s, closed_at = NOW()
                WHERE id = %s
            """, (admin["id"], current["id"]))

            # 查找连续7轮未登记的用户
            cursor.execute("""
                SELECT id, round_no FROM rounds
                ORDER BY id DESC
                LIMIT 7
            """)
            recent_rounds = cursor.fetchall()
            if len(recent_rounds) < 7:
                return {"message": f"第{current['round_no']}轮已关闭，未冻结用户（不足7轮记录）"}

            round_ids = tuple(r["id"] for r in recent_rounds)
            in_placeholder = ",".join(["%s"] * len(round_ids))

            cursor.execute(f"""
                SELECT u.id, u.username
                FROM users u
                WHERE u.role = 'player'
                  AND u.status = 'active'
                  AND u.id NOT IN (
                    SELECT DISTINCT rr.user_id
                    FROM round_registrations rr
                    WHERE rr.round_id IN ({in_placeholder})
                )
            """, round_ids)
            to_freeze = cursor.fetchall()

            for u in to_freeze:
                cursor.execute("UPDATE users SET status = 'frozen' WHERE id = %s", (u["id"],))
                frozen_count += 1
                log_operation(conn, admin["id"], "auto_freeze", "user", u["id"],
                               detail=f"连续7轮未登记，自动冻结")

    return {
        "message": f"第{current['round_no']}轮已关闭",
        "frozen_count": frozen_count,
        "frozen_users": [u["username"] for u in to_freeze]
    }


@router.get("/round/list")
def list_rounds(admin=Depends(require_admin)):
    """查看轮次列表（含登记人数统计）"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT r.*, u.username as opened_by_name,
                       (SELECT COUNT(*) FROM round_registrations rr WHERE rr.round_id = r.id) as registrations_count
                FROM rounds r
                LEFT JOIN users u ON r.opened_by = u.id
                ORDER BY r.id DESC
                LIMIT 50
            """)
            rounds = cursor.fetchall()
    return {"rounds": rounds}


# ========== 管理员撤销本轮对战登记 ==========

@router.delete("/match/{match_id}/cancel")
def admin_cancel_match(match_id: int, admin=Depends(require_admin)):
    """
    管理员撤销本轮对战登记（仅当前进行中的轮次）
    - 恢复双方积分（已登记对战）
    - 删除匹配记录
    - 删除轮次登记记录
    """
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM matches WHERE id = %s", (match_id,))
            match = cursor.fetchone()
            if not match:
                raise HTTPException(status_code=404, detail="匹配记录不存在")

            # 获取当前进行中的轮次
            cursor.execute("SELECT id, round_no FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current_round = cursor.fetchone()

            if not current_round:
                raise HTTPException(status_code=403, detail="当前无进行中的轮次，无法撤销")

            # 验证该匹配属于本轮
            cursor.execute("SELECT opened_at FROM rounds WHERE id = %s", (current_round["id"],))
            round_info = cursor.fetchone()
            if round_info and match["matched_at"] < round_info["opened_at"]:
                raise HTTPException(status_code=403, detail="只能撤销当前轮次的对战记录")

            is_registered = bool(match["is_registered"])

            # 恢复积分（仅已登记对战）
            if is_registered and match["winner_id"] and match["loser_id"]:
                cursor.execute("UPDATE clans SET score = score - 1 WHERE id = %s", (match["winner_id"],))
                cursor.execute("UPDATE clans SET score = score + 1 WHERE id = %s", (match["loser_id"],))

                # 获取部落名称用于日志
                cursor.execute("SELECT name FROM clans WHERE id = %s", (match["winner_id"],))
                winner_name = cursor.fetchone()["name"]
                cursor.execute("SELECT name FROM clans WHERE id = %s", (match["loser_id"],))
                loser_name = cursor.fetchone()["name"]
            else:
                winner_name = loser_name = None

            # 清理临时部落（未登记对战）
            for cid in [match["clan_a_id"], match["clan_b_id"]]:
                if cid:
                    cursor.execute("SELECT code FROM clans WHERE id = %s", (cid,))
                    row = cursor.fetchone()
                    if row and row["code"].startswith("UNREG_"):
                        cursor.execute("DELETE FROM clans WHERE id = %s", (cid,))

            # 删除轮次登记记录
            cursor.execute(
                "DELETE FROM round_registrations WHERE round_id = %s AND clan_id IN (%s, %s)",
                (current_round["id"], match["clan_a_id"], match["clan_b_id"])
            )

            # 删除匹配记录
            cursor.execute("DELETE FROM matches WHERE id = %s", (match_id,))

            # 写日志
            clan_a_name = clan_b_name = ""
            cursor.execute("SELECT name FROM clans WHERE id = %s", (match["clan_a_id"],))
            r = cursor.fetchone()
            if r: clan_a_name = r["name"]
            cursor.execute("SELECT name FROM clans WHERE id = %s", (match["clan_b_id"],))
            r = cursor.fetchone()
            if r: clan_b_name = r["name"]

            score_info = ""
            if is_registered and winner_name:
                score_info = f"，积分已恢复（胜方 {winner_name} -1，负方 {loser_name} +1）"

            log_operation(conn, admin["id"], "cancel_match",
                          detail=f"第{current_round['round_no']}轮撤销对战 {clan_a_name} vs {clan_b_name}{score_info}")

    return {
        "message": f"第{current_round['round_no']}轮对战已撤销，积分已恢复",
        "round_no": current_round["round_no"],
        "is_registered": is_registered
    }


# ========== 轮次列表 ==========

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
    """将数据库行转为JSON可序列化格式"""
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
def export_data(admin=Depends(require_admin)):
    """导出所有数据为JSON"""
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
    return JSONResponse(
        content=export_info,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/backup/import")
async def import_data(file: UploadFile = File(...), admin=Depends(require_admin)):
    """从JSON文件导入数据（覆盖现有数据）"""
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

        except Exception as e:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")

    imported_counts = {t: len(import_data_dict.get(t, [])) for t in IMPORT_ORDER if t in import_data_dict}
    return {"message": "数据导入成功", "imported": imported_counts}


# ========== 积分操作指南 ==========

class ScoreGuideRequest(BaseModel):
    content: str


@router.get("/score-guide")
def get_score_guide(admin=Depends(require_admin)):
    """获取积分操作指南"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT content FROM score_guide ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
    return {"content": row["content"] if row else ""}


@router.put("/score-guide")
def update_score_guide(req: ScoreGuideRequest, admin=Depends(require_admin)):
    """更新积分操作指南"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM score_guide ORDER BY id DESC LIMIT 1")
            existing = cursor.fetchone()
            if existing:
                cursor.execute("UPDATE score_guide SET content = %s, updated_at = NOW() WHERE id = %s", (req.content, existing["id"]))
            else:
                cursor.execute("INSERT INTO score_guide (content) VALUES (%s)", (req.content,))
            log_operation(conn, admin["id"], "update_score_guide", detail="更新积分操作指南")
    return {"message": "积分操作指南已更新"}


# ========== 本轮部落统计 ==========

@router.get("/round/clan-status")
def round_clan_status(admin=Depends(require_admin)):
    """管理员查看本轮各部落的匹配状态 + 连续未登记统计"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, round_no, opened_at FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current_round = cursor.fetchone()
            if not current_round:
                return {"current_round": None, "clan_status": [], "inactive_clans": []}

            cursor.execute("SELECT id, name, code, contact, score FROM clans WHERE code NOT LIKE %s ORDER BY name", ('UNREG_%',))
            all_clans = cursor.fetchall()
            clan_ids = [c["id"] for c in all_clans]

            if clan_ids:
                in_placeholder = ",".join(["%s"] * len(clan_ids))
                cursor.execute(f"""
                    SELECT m.clan_a_id, m.clan_b_id, m.is_registered, m.matched_at
                    FROM matches m
                    WHERE m.matched_at >= %s
                      AND (m.clan_a_id IN ({in_placeholder}) OR m.clan_b_id IN ({in_placeholder}))
                """, [current_round["opened_at"]] + clan_ids + clan_ids)
                round_matches = cursor.fetchall()
            else:
                round_matches = []

            cursor.execute("""
                SELECT DISTINCT rr.clan_id FROM round_registrations rr
                WHERE rr.round_id = %s
            """, (current_round["id"],))
            registered_clan_ids = set(r["clan_id"] for r in cursor.fetchall())

            clan_status = []
            for c in all_clans:
                matched_registered = False
                matched_unknown = False
                for m in round_matches:
                    if m["clan_a_id"] == c["id"] or m["clan_b_id"] == c["id"]:
                        if m["is_registered"]:
                            matched_registered = True
                        else:
                            matched_unknown = True
                registered = c["id"] in registered_clan_ids

                if matched_registered:
                    status = "匹配成功"
                elif matched_unknown:
                    status = "匹配到陌生部落"
                elif registered:
                    status = "已登记未匹配"
                else:
                    status = "未登记"

                clan_status.append({
                    "id": c["id"],
                    "name": c["name"],
                    "code": c["code"],
                    "contact": c["contact"],
                    "score": c["score"],
                    "status": status
                })

            cursor.execute("SELECT id FROM rounds ORDER BY id DESC LIMIT 7")
            recent_round_ids = [r["id"] for r in cursor.fetchall()]

            inactive_clans = []
            if len(recent_round_ids) >= 3:
                in_placeholder_r = ",".join(["%s"] * len(recent_round_ids))
                cursor.execute(f"""
                    SELECT c.id, c.name, c.code,
                           (SELECT COUNT(DISTINCT rr.round_id)
                            FROM round_registrations rr WHERE rr.clan_id = c.id AND rr.round_id IN ({in_placeholder_r})) as active_rounds
                    FROM clans c
                    WHERE c.code NOT LIKE %s
                    ORDER BY active_rounds ASC, c.name
                """, recent_round_ids + ['UNREG_%'])
                clan_activity = cursor.fetchall()

                total_recent = len(recent_round_ids)
                for ca in clan_activity:
                    inactive_count = total_recent - ca["active_rounds"]
                    if inactive_count >= 7:
                        inactive_clans.append({
                            "id": ca["id"],
                            "name": ca["name"],
                            "code": ca["code"],
                            "inactive_rounds": inactive_count,
                            "total_rounds": total_recent
                        })

    return {
        "current_round": {"id": current_round["id"], "round_no": current_round["round_no"]},
        "clan_status": clan_status,
        "inactive_clans": inactive_clans
    }
