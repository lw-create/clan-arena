import random
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import get_db
from auth import get_current_user

router = APIRouter(prefix="/api", tags=["玩家"])


class BindClanRequest(BaseModel):
    clan_name: str
    clan_code: str
    contact: str = ""


class SearchClanRequest(BaseModel):
    keyword: str


class MatchRegisteredRequest(BaseModel):
    clan_id: int
    my_clan_id: int = None
    config_remark: str = ""


class MatchUnregisteredRequest(BaseModel):
    clan_name: str
    clan_code: str
    tags: str = ""
    remark: str = ""
    config_remark: str = ""


@router.post("/bind-clan")
def bind_clan(req: BindClanRequest, user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name FROM clans WHERE code = %s", (req.clan_code,))
            clan = cursor.fetchone()
            if clan:
                if clan["name"] != req.clan_name:
                    raise HTTPException(status_code=400, detail="部落代码与名称不匹配")
                clan_id = clan["id"]
                if req.contact:
                    cursor.execute("UPDATE clans SET contact = %s WHERE id = %s", (req.contact, clan_id))
            else:
                cursor.execute(
                    "INSERT INTO clans (name, code, contact) VALUES (%s, %s, %s)",
                    (req.clan_name, req.clan_code, req.contact)
                )
                clan_id = cursor.lastrowid

            cursor.execute("SELECT id FROM user_clan WHERE user_id = %s AND clan_id = %s", (user["id"], clan_id))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="已绑定该部落")

            cursor.execute(
                "INSERT INTO user_clan (user_id, clan_id) VALUES (%s, %s)",
                (user["id"], clan_id)
            )

    return {"message": "部落绑定成功", "clan_id": clan_id}


@router.post("/unbind-clan")
def unbind_clan(clan_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM user_clan WHERE user_id = %s AND clan_id = %s", (user["id"], clan_id))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=400, detail="未绑定该部落")
    return {"message": "部落解绑成功"}


@router.get("/my-clans")
def get_my_clans(user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT c.id, c.name, c.code, c.contact, c.score
                FROM user_clan uc
                JOIN clans c ON uc.clan_id = c.id
                WHERE uc.user_id = %s
            """, (user["id"],))
            clans = cursor.fetchall()
    return {"clans": clans}


@router.get("/leaderboard")
def leaderboard():
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, code, contact, score FROM clans WHERE code NOT LIKE %s ORDER BY score DESC",
                ('UNREG_%',)
            )
            clans = cursor.fetchall()
    return {"clans": clans}


@router.post("/search-clan")
def search_clan(req: SearchClanRequest, user=Depends(get_current_user)):
    kw = f"%{req.keyword}%"
    unreg = "UNREG_%"
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, code, contact, score FROM clans WHERE (name LIKE %s OR code LIKE %s) AND code NOT LIKE %s",
                (kw, kw, unreg)
            )
            results = cursor.fetchall()
    return {"clans": results}


@router.post("/match/registered")
def match_registered(req: MatchRegisteredRequest, user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            # 检查当前轮次是否开启
            cursor.execute("SELECT id, round_no, config_required FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current_round = cursor.fetchone()
            if not current_round:
                raise HTTPException(status_code=403, detail="当前轮次未开启或已关闭，无法登记，请联系管理员开启本轮")

            if current_round.get("config_required") and not req.config_remark:
                raise HTTPException(status_code=400, detail="本轮要求填写对战配置，请先填写配置信息")

            cursor.execute("SELECT clan_id FROM user_clan WHERE user_id = %s", (user["id"],))
            my_clans = cursor.fetchall()
            if not my_clans:
                raise HTTPException(status_code=400, detail="请先绑定部落")

            # 使用前端选择的出战部落，或默认第一个
            if req.my_clan_id:
                my_clan_ids = [c["clan_id"] for c in my_clans]
                if req.my_clan_id not in my_clan_ids:
                    raise HTTPException(status_code=400, detail="该部落不属于你")
                if req.my_clan_id == req.clan_id:
                    raise HTTPException(status_code=400, detail="不能与自己部落匹配")
                my_clan_id = req.my_clan_id
            else:
                my_clan_id = my_clans[0]["clan_id"]
                if my_clan_id == req.clan_id:
                    raise HTTPException(status_code=400, detail="不能与自己部落匹配")

            cursor.execute("SELECT id, name, score FROM clans WHERE id = %s", (my_clan_id,))
            my_clan = cursor.fetchone()
            cursor.execute("SELECT id, name, score FROM clans WHERE id = %s", (req.clan_id,))
            opp_clan = cursor.fetchone()
            if not opp_clan:
                raise HTTPException(status_code=404, detail="对方部落不存在")

            # 防重复匹配检查
            cursor.execute("SELECT id FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current_round = cursor.fetchone()
            if current_round:
                cursor.execute("""
                    SELECT id FROM matches
                    WHERE created_by = %s
                      AND ((clan_a_id = %s AND clan_b_id = %s) OR (clan_a_id = %s AND clan_b_id = %s))
                      AND matched_at >= (SELECT opened_at FROM rounds WHERE id = %s)
                      AND is_registered = 1
                    LIMIT 1
                """, (user["id"], my_clan_id, req.clan_id, req.clan_id, my_clan_id, current_round["id"]))
                dup = cursor.fetchone()
                if dup:
                    raise HTTPException(status_code=400, detail=f"本轮已与该部落登记过对战，请勿重复匹配 (match_id={dup['id']})")

            score_a = my_clan["score"]
            score_b = opp_clan["score"]

            if score_a == score_b:
                winner_id, loser_id = random.choice([
                    (my_clan_id, req.clan_id),
                    (req.clan_id, my_clan_id),
                ])
            elif score_a < score_b:
                winner_id = my_clan_id
                loser_id = req.clan_id
            else:
                winner_id = req.clan_id
                loser_id = my_clan_id

            cursor.execute("UPDATE clans SET score = score + 1 WHERE id = %s", (winner_id,))
            cursor.execute("UPDATE clans SET score = score - 1 WHERE id = %s", (loser_id,))

            cursor.execute("""
                INSERT INTO matches (clan_a_id, clan_b_id, winner_id, loser_id,
                                     score_before_a, score_before_b, is_registered, created_by, config_remark)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (my_clan_id, req.clan_id, winner_id, loser_id, score_a, score_b, 1, user["id"], req.config_remark or None))

            match_id = cursor.lastrowid

            # 记录本轮登记
            cursor.execute("SELECT id FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current_round = cursor.fetchone()
            if current_round:
                for uc in my_clans:
                    cursor.execute("""
                        INSERT IGNORE INTO round_registrations (round_id, user_id, clan_id)
                        VALUES (%s, %s, %s)
                    """, (current_round["id"], user["id"], uc["clan_id"]))

            cursor.execute("SELECT name, score FROM clans WHERE id = %s", (winner_id,))
            winner = cursor.fetchone()
            cursor.execute("SELECT name, score FROM clans WHERE id = %s", (loser_id,))
            loser = cursor.fetchone()

    return {
        "matched": True,
        "match_id": match_id,
        "winner": {"id": winner_id, "name": winner["name"], "score": winner["score"]},
        "loser": {"id": loser_id, "name": loser["name"], "score": loser["score"]},
        "score_before": {"clan_a": score_a, "clan_b": score_b},
        "is_registered": True,
    }


@router.post("/match/unregistered")
def match_unregistered(req: MatchUnregisteredRequest, user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            # 检查当前轮次是否开启
            cursor.execute("SELECT id, round_no, config_required FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current_round = cursor.fetchone()
            if not current_round:
                raise HTTPException(status_code=403, detail="当前轮次未开启或已关闭，无法登记，请联系管理员开启本轮")

            if current_round.get("config_required") and not req.config_remark:
                raise HTTPException(status_code=400, detail="本轮要求填写对战配置，请先填写配置信息")

            cursor.execute("SELECT clan_id FROM user_clan WHERE user_id = %s", (user["id"],))
            my_clans = cursor.fetchall()
            if not my_clans:
                raise HTTPException(status_code=400, detail="请先绑定部落")
            my_clan_id = my_clans[0]["clan_id"]
            cursor.execute("SELECT id, name, score FROM clans WHERE id = %s", (my_clan_id,))
            my_clan = cursor.fetchone()
            score_before = my_clan["score"]

            # 未登记的匹配不扣分，积分保持不变
            temp_code = f"UNREG_{req.clan_code[:8]}_{user['id']}_{int(time.time() * 1000) % 100000}"
            cursor.execute(
                "INSERT INTO clans (name, code, contact) VALUES (%s, %s, %s)",
                (req.clan_name, temp_code, "未登记部落")
            )
            temp_clan_id = cursor.lastrowid

            # 写入陌生部落数据库 - SQLite UPSERT
            cursor.execute("""
                INSERT INTO unknown_clans (name, code, tags, encounter_count, last_seen)
                VALUES (%s, %s, %s, 1, NOW())
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    tags = IF(VALUES(tags) != '', VALUES(tags), tags),
                    encounter_count = encounter_count + 1,
                    last_seen = NOW()
            """, (req.clan_name, req.clan_code, req.tags))

            cursor.execute("""
                INSERT INTO matches (clan_a_id, clan_b_id, winner_id, loser_id,
                                     score_before_a, score_before_b, is_registered, remark, created_by, config_remark)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (my_clan_id, temp_clan_id, temp_clan_id, my_clan_id,
                  score_before, 0, 0, req.remark, user["id"], req.config_remark or None))

            match_id = cursor.lastrowid

            # 未登记的对战不修改积分，保持原分数
            new_score = score_before

    return {
        "matched": True,
        "match_id": match_id,
        "winner": {"id": temp_clan_id, "name": req.clan_name, "score": 0},
        "loser": {"id": my_clan_id, "name": my_clan["name"], "score": new_score},
        "score_before": {"clan_a": score_before, "clan_b": 0},
        "is_registered": False,
        "remark": req.remark,
        "message": "对战已登记，积分保持不变",
    }


@router.delete("/match/{match_id}")
def cancel_match(match_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM matches WHERE id = %s AND created_by = %s", (match_id, user["id"]))
            match = cursor.fetchone()
            if not match:
                raise HTTPException(status_code=404, detail="匹配记录不存在或非您创建")

            # 检查该匹配是否属于当前轮次
            cursor.execute("SELECT id FROM rounds WHERE status = 'open' ORDER BY id DESC LIMIT 1")
            current_round = cursor.fetchone()
            if current_round:
                cursor.execute("SELECT opened_at FROM rounds WHERE id = %s", (current_round["id"],))
                round_info = cursor.fetchone()
                if round_info and match["matched_at"] < round_info["opened_at"]:
                    raise HTTPException(status_code=403, detail="不能撤销之前轮次的登记记录，只能撤销本轮的")

                # 每轮只能撤销一次
                cursor.execute(
                    "SELECT cancel_count_round_id, cancel_count FROM users WHERE id = %s",
                    (user["id"],)
                )
                cancel_info = cursor.fetchone()
                if cancel_info and cancel_info["cancel_count_round_id"] == current_round["id"] and cancel_info["cancel_count"] >= 1:
                    raise HTTPException(status_code=403, detail="本轮已使用过撤销机会，每轮仅允许撤销一次")
            else:
                raise HTTPException(status_code=403, detail="当前无进行中的轮次，不能撤销历史记录")

            # 检查是否为未登记对战
            is_unregistered = not match["is_registered"]

            # 只有已登记（is_registered=1）的对战才需要恢复积分
            if not is_unregistered and match["winner_id"] and match["loser_id"]:
                cursor.execute("UPDATE clans SET score = score - 1 WHERE id = %s", (match["winner_id"],))
                cursor.execute("UPDATE clans SET score = score + 1 WHERE id = %s", (match["loser_id"],))

            if is_unregistered:
                for cid in [match["clan_a_id"], match["clan_b_id"]]:
                    cursor.execute("SELECT code, name FROM clans WHERE id = %s", (cid,))
                    clan_row = cursor.fetchone()
                    if clan_row and clan_row["code"].startswith("UNREG_"):
                        cursor.execute("""
                            UPDATE unknown_clans SET encounter_count = GREATEST(0, encounter_count - 1)
                            WHERE name = %s
                        """, (clan_row["name"],))
                        cursor.execute("DELETE FROM clans WHERE id = %s", (cid,))

            cursor.execute("DELETE FROM matches WHERE id = %s", (match_id,))

            # 更新撤销计数
            if current_round:
                cursor.execute(
                    "UPDATE users SET cancel_count_round_id = %s, cancel_count = COALESCE(cancel_count, 0) + 1 WHERE id = %s",
                    (current_round["id"], user["id"])
                )

    return {"message": "匹配记录已撤销，积分已恢复（本轮撤销机会已用完）"}


@router.post("/match/{match_id}/confirm")
def confirm_match(match_id: int, user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM matches WHERE id = %s", (match_id,))
            match = cursor.fetchone()
            if not match:
                raise HTTPException(status_code=404, detail="匹配记录不存在")

            cursor.execute("UPDATE matches SET confirmed_by = %s WHERE id = %s", (user["id"], match_id))
    return {"message": "匹配已确认"}


@router.get("/match-history")
def match_history(clan_id: int = None, user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT clan_id FROM user_clan WHERE user_id = %s", (user["id"],))
            my_clans = cursor.fetchall()
            if not my_clans:
                return {"matches": []}

            cursor.execute("SELECT id, round_no, status, opened_at, closed_at FROM rounds ORDER BY opened_at ASC")
            all_rounds = cursor.fetchall()

            current_round_id = None
            for r in all_rounds:
                if r["status"] == "open":
                    current_round_id = r["id"]
                    break

            round_opened_at = None
            for r in all_rounds:
                if r["id"] == current_round_id:
                    round_opened_at = r["opened_at"]
                    break

            my_clan_ids = [c["clan_id"] for c in my_clans]
            if clan_id and clan_id in my_clan_ids:
                query_clan_ids = [clan_id]
            else:
                query_clan_ids = my_clan_ids

            in_placeholder = ",".join(["%s"] * len(query_clan_ids))
            cursor.execute(f"""
                SELECT m.id, m.clan_a_id, m.clan_b_id, m.winner_id, m.loser_id,
                       m.score_before_a, m.score_before_b, m.is_registered, m.remark,
                       m.matched_at, m.created_by, m.config_remark,
                       ca.name as clan_a_name, cb.name as clan_b_name
                FROM matches m
                JOIN clans ca ON m.clan_a_id = ca.id
                JOIN clans cb ON m.clan_b_id = cb.id
                WHERE m.clan_a_id IN ({in_placeholder}) OR m.clan_b_id IN ({in_placeholder})
                ORDER BY m.matched_at DESC
                LIMIT 50
            """, query_clan_ids + query_clan_ids)
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

                m["can_cancel"] = (
                    m["created_by"] == user["id"]
                    and round_opened_at is not None
                    and m["matched_at"] >= round_opened_at
                )
    return {"matches": matches}


@router.get("/unknown-clans")
def player_unknown_clans(user=Depends(get_current_user)):
    """玩家查看陌生部落列表"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT name, code, tags, encounter_count, last_seen
                FROM unknown_clans
                ORDER BY encounter_count DESC, last_seen DESC
                LIMIT 200
            """)
            data = cursor.fetchall()
    return {"unknown_clans": data}


# ========== 配置统计（玩家端） ==========

class ConfigItemReq(BaseModel):
    th_level: int
    member_count: int


class ClanConfigReq(BaseModel):
    clan_id: int
    target_total: int
    items: list[ConfigItemReq]


def _config_stats_enabled(cursor) -> bool:
    cursor.execute("SELECT value FROM system_settings WHERE `key` = %s", ("config_stats_enabled",))
    row = cursor.fetchone()
    return bool(row and row["value"] == "1")


@router.get("/clan-config")
def get_my_clan_config(clan_id: int, user=Depends(get_current_user)):
    """读取本人某绑定部落当前配置（玩家端）"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            if not _config_stats_enabled(cursor):
                raise HTTPException(status_code=403, detail="配置统计当前未开启")
            cursor.execute("SELECT id FROM user_clan WHERE user_id = %s AND clan_id = %s", (user["id"], clan_id))
            if not cursor.fetchone():
                raise HTTPException(status_code=403, detail="您未绑定该部落")

            cursor.execute("SELECT target_total, updated_at FROM clan_configs WHERE clan_id = %s", (clan_id,))
            cfg = cursor.fetchone()
            if not cfg:
                return {"clan_id": clan_id, "target_total": None, "items": [], "updated_at": None}

            cursor.execute("""
                SELECT th_level, member_count FROM clan_config_items
                WHERE clan_id = %s ORDER BY th_level DESC
            """, (clan_id,))
            items = cursor.fetchall()

    return {"clan_id": clan_id, "target_total": cfg["target_total"], "updated_at": cfg["updated_at"], "items": items}


@router.post("/clan-config")
def save_my_clan_config(req: ClanConfigReq, user=Depends(get_current_user)):
    """保存某绑定部落的配置（玩家端，覆盖式）"""
    # 校验：target_total
    if req.target_total not in (40, 50):
        raise HTTPException(status_code=400, detail="总人数目标必须为 40 或 50")
    # 校验：items 非空
    if not req.items:
        raise HTTPException(status_code=400, detail="请至少填写一栏配置")
    # 校验：等级与人数范围 + 等级唯一
    seen_levels = set()
    total = 0
    for it in req.items:
        if it.th_level < 0 or it.th_level > 100:
            raise HTTPException(status_code=400, detail=f"大本营等级必须在 0-100 之间（当前：{it.th_level}）")
        if it.member_count < 0 or it.member_count > 50:
            raise HTTPException(status_code=400, detail=f"成员数量必须在 0-50 之间（当前：{it.member_count}）")
        if it.th_level in seen_levels:
            raise HTTPException(status_code=400, detail=f"大本营等级 {it.th_level} 不能重复出现")
        seen_levels.add(it.th_level)
        total += it.member_count
    if total != req.target_total:
        raise HTTPException(status_code=400, detail=f"成员数量合计为 {total}，应等于目标 {req.target_total}")

    with get_db() as conn:
        with conn.cursor() as cursor:
            if not _config_stats_enabled(cursor):
                raise HTTPException(status_code=403, detail="配置统计当前未开启")
            cursor.execute("SELECT id FROM user_clan WHERE user_id = %s AND clan_id = %s", (user["id"], req.clan_id))
            if not cursor.fetchone():
                raise HTTPException(status_code=403, detail="您未绑定该部落")

            # 覆盖：先删旧明细，再插入新明细
            cursor.execute("DELETE FROM clan_config_items WHERE clan_id = %s", (req.clan_id,))
            for idx, it in enumerate(req.items):
                cursor.execute("""
                    INSERT INTO clan_config_items (clan_id, th_level, member_count, sort_order)
                    VALUES (%s, %s, %s, %s)
                """, (req.clan_id, it.th_level, it.member_count, idx))

            # 写入或更新主记录
            cursor.execute("""
                INSERT INTO clan_configs (clan_id, target_total, updated_by, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    target_total = VALUES(target_total),
                    updated_by = VALUES(updated_by),
                    updated_at = NOW()
            """, (req.clan_id, req.target_total, user["id"]))

    return {"message": "配置已保存"}
