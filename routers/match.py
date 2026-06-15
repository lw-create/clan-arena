import random
from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from auth import get_current_user

router = APIRouter(prefix="/api/match", tags=["对战匹配"])


@router.post("/queue")
def join_queue(user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            # 检查是否绑定部落
            cursor.execute("SELECT clan_id FROM user_clan WHERE user_id = ?", (user["id"],))
            uc = cursor.fetchone()
            if not uc:
                raise HTTPException(status_code=400, detail="请先绑定部落")

            clan_id = uc["clan_id"]

            # 检查是否已在队列中
            cursor.execute("SELECT id FROM match_queue WHERE user_id = ?", (user["id"],))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="已在匹配队列中")

            # 加入队列
            cursor.execute(
                "INSERT INTO match_queue (user_id, clan_id) VALUES (?, ?)",
                (user["id"], clan_id)
            )

            # 尝试匹配
            cursor.execute("""
                SELECT mq.user_id, mq.clan_id
                FROM match_queue mq
                WHERE mq.clan_id != ? AND mq.user_id != ?
                ORDER BY mq.joined_at ASC
                LIMIT 1
            """, (clan_id, user["id"]))
            opponent = cursor.fetchone()

    if opponent:
        return execute_match(user["id"], clan_id, opponent["user_id"], opponent["clan_id"])

    return {"message": "已加入匹配队列，等待对手...", "matched": False}


def execute_match(user_a_id: int, clan_a_id: int, user_b_id: int, clan_b_id: int):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, score FROM clans WHERE id = ?", (clan_a_id,))
            clan_a = cursor.fetchone()
            cursor.execute("SELECT id, name, score FROM clans WHERE id = ?", (clan_b_id,))
            clan_b = cursor.fetchone()

            score_a = clan_a["score"]
            score_b = clan_b["score"]

            if score_a == score_b:
                winner_id, loser_id = random.choice([
                    (clan_a_id, clan_b_id),
                    (clan_b_id, clan_a_id),
                ])
            elif score_a < score_b:
                winner_id = clan_a_id
                loser_id = clan_b_id
            else:
                winner_id = clan_b_id
                loser_id = clan_a_id

            cursor.execute("UPDATE clans SET score = score + 1 WHERE id = ?", (winner_id,))
            cursor.execute("UPDATE clans SET score = score - 1 WHERE id = ?", (loser_id,))

            cursor.execute("""
                INSERT INTO matches (clan_a_id, clan_b_id, winner_id, loser_id,
                                     score_before_a, score_before_b)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (clan_a_id, clan_b_id, winner_id, loser_id, score_a, score_b))

            match_id = cursor.lastrowid

            cursor.execute("DELETE FROM match_queue WHERE user_id IN (?, ?)", (user_a_id, user_b_id))

            cursor.execute("SELECT score FROM clans WHERE id = ?", (winner_id,))
            winner_score = cursor.fetchone()["score"]
            cursor.execute("SELECT score FROM clans WHERE id = ?", (loser_id,))
            loser_score = cursor.fetchone()["score"]

            winner_name = clan_a["name"] if winner_id == clan_a_id else clan_b["name"]
            loser_name = clan_a["name"] if loser_id == clan_a_id else clan_b["name"]

    return {
        "matched": True,
        "match_id": match_id,
        "winner": {"id": winner_id, "name": winner_name, "score": winner_score},
        "loser": {"id": loser_id, "name": loser_name, "score": loser_score},
        "score_before": {"clan_a": score_a, "clan_b": score_b},
    }


@router.get("/status")
def match_status(user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, clan_id FROM match_queue WHERE user_id = ?", (user["id"],))
            in_queue = cursor.fetchone()

    if in_queue:
        return {"in_queue": True, "message": "正在匹配中..."}
    return {"in_queue": False, "message": "未在匹配队列中"}


@router.post("/cancel")
def cancel_queue(user=Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM match_queue WHERE user_id = ?", (user["id"],))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=400, detail="未在匹配队列中")

    return {"message": "已退出匹配队列"}
