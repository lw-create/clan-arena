"""
一次性数据模拟端点
访问 /api/simulate/run 触发，自动写入数据库
部署完成后建议删除此模块
"""
import os
import random

from fastapi import APIRouter, HTTPException

from database import get_db, init_db
from auth import hash_password  # 使用统一的密码哈希函数

router = APIRouter(prefix="/api/simulate", tags=["模拟"])


def _hash_pwd(pwd: str) -> str:
    """使用auth.py中的hash_password确保哈希方式一致"""
    return hash_password(pwd)


def _log(msg: str):
    print(f"[SIMULATE] {msg}")


@router.post("/run")
def run_simulation():
    """
    一键数据模拟：创建 admin/10 玩家 + 绑定部落 + 2 轮对战
    直接调用即可，无需 token
    """
    _log("开始执行数据模拟...")
    init_db()
    report = _do_simulate()
    _log("模拟完成")
    return report


@router.get("/run")
def run_simulation_get():
    """GET 方式（方便从浏览器地址栏触发）"""
    return run_simulation()


def _do_simulate() -> dict:
    """执行模拟并返回结构化报告"""
    # 1. 重置数据
    _clear_data()

    # 2. 创建用户
    admin_id, players = _create_users()

    # 3. 创建轮次 + 对战
    round1 = _do_round(admin_id, players, 1)
    round2 = _do_round(admin_id, players, 2)

    # 4. 生成报告
    return _build_report(admin_id, players, round1, round2)


def _clear_data():
    """清空模拟相关表（确保 admin/monitor 账号存在且密码正确）"""
    with get_db() as conn:
        with conn.cursor() as c:
            for table in ['operation_logs', 'round_registrations', 'matches',
                          'user_clan', 'clans', 'notifications', 'unknown_clans', 'rounds']:
                try:
                    c.execute(f"DELETE FROM {table}")
                except Exception:
                    pass

            # 确保 admin 和 monitor 用户存在且密码正确
            c.execute("SELECT id FROM users WHERE username='admin'")
            admin_row = c.fetchone()
            if admin_row:
                c.execute("UPDATE users SET password_hash=%s, plain_password=%s, role='admin', is_super_admin=1, status='active', must_change_pwd=0 WHERE username='admin'",
                          (_hash_pwd('admin123'), 'admin123'))
            else:
                c.execute("INSERT INTO users (username, password_hash, plain_password, role, is_super_admin, status, must_change_pwd) VALUES (%s,%s,%s,'admin',1,'active',0)",
                          ('admin', _hash_pwd('admin123'), 'admin123'))

            c.execute("SELECT id FROM users WHERE username='monitor'")
            monitor_row = c.fetchone()
            if monitor_row:
                c.execute("UPDATE users SET password_hash=%s, plain_password=%s, role='monitor', status='active', must_change_pwd=0 WHERE username='monitor'",
                          (_hash_pwd('monitor123'), 'monitor123'))
            else:
                c.execute("INSERT INTO users (username, password_hash, plain_password, role, status, must_change_pwd) VALUES (%s,%s,%s,'monitor','active',0)",
                          ('monitor', _hash_pwd('monitor123'), 'monitor123'))

            # 删除其他用户
            try:
                c.execute("DELETE FROM users WHERE username NOT IN ('admin', 'monitor')")
            except Exception:
                pass
    _log("🧹 数据库已重置（admin/monitor 密码已重置）")


def _create_users() -> tuple:
    """创建 10 玩家 + 绑定部落（admin 已在 _clear_data 中处理）"""
    with get_db() as conn:
        with conn.cursor() as c:
            # 获取 admin_id
            c.execute("SELECT id FROM users WHERE username='admin'")
            admin_id = c.fetchone()['id']

            # admin 的部落
            c.execute("SELECT id FROM clans WHERE code='ADMIN001'")
            row = c.fetchone()
            if row:
                admin_clan_id = row['id']
            else:
                c.execute("INSERT INTO clans (name, code, contact, score) VALUES (%s,%s,%s,0)",
                          ('管理部落', 'ADMIN001', 'system'))
                admin_clan_id = c.lastrowid
            try:
                c.execute("INSERT INTO user_clan (user_id, clan_id) VALUES (%s,%s)",
                          (admin_id, admin_clan_id))
            except Exception:
                pass

            # 10 个玩家
            player_names = ['阿强', '小美', '大勇', '小花', '阿龙',
                            '小倩', '小胖', '小芳', '阿伟', '小燕']
            players = []
            for i, name in enumerate(player_names):
                username = f"player{i+1:02d}"
                password = "123456"
                clan_name = f"部落{name}"
                clan_code = f"CL{i+1:03d}"
                initial_score = random.randint(10, 19)

                c.execute(
                    "INSERT INTO users (username, password_hash, plain_password, role, must_change_pwd) "
                    "VALUES (%s, %s, %s, 'player', 1)",
                    (username, _hash_pwd(password), password))
                user_id = c.lastrowid

                c.execute("INSERT INTO clans (name, code, contact, score) VALUES (%s,%s,%s,%s)",
                          (clan_name, clan_code, f"玩家{i+1}", initial_score))
                clan_id = c.lastrowid

                c.execute("INSERT INTO user_clan (user_id, clan_id) VALUES (%s,%s)",
                          (user_id, clan_id))

                players.append({
                    'user_id': user_id, 'username': username, 'password': password,
                    'name': name, 'clan_id': clan_id, 'clan_name': clan_name,
                    'clan_code': clan_code, 'initial_score': initial_score
                })
                _log(f"  🎮 {username} ({name}) → {clan_name} [{clan_code}] 初始积分={initial_score}")

    return admin_id, players


def _do_round(admin_id: int, players: list, round_no: int) -> dict:
    """进行一轮对战"""
    with get_db() as conn:
        with conn.cursor() as c:
            # 开启轮次
            c.execute("INSERT INTO rounds (round_no, status, opened_by) VALUES (%s, 'open', %s)",
                      (round_no, admin_id))
            round_id = c.lastrowid

            random.shuffle(players)
            summary = {"round_no": round_no, "matches": [], "registered_count": 0, "unregistered_count": 0}

            # 4 场已登记
            pairs = [(players[0], players[1]), (players[2], players[3]),
                     (players[4], players[5]), (players[6], players[7])]

            for idx, (pa, pb) in enumerate(pairs):
                c.execute("SELECT score FROM clans WHERE id=%s", (pa['clan_id'],))
                sa = c.fetchone()['score']
                c.execute("SELECT score FROM clans WHERE id=%s", (pb['clan_id'],))
                sb = c.fetchone()['score']

                if sa == sb:
                    win_id, lose_id = random.choice([(pa['clan_id'], pb['clan_id']),
                                                      (pb['clan_id'], pa['clan_id'])])
                elif sa < sb:
                    win_id, lose_id = pa['clan_id'], pb['clan_id']
                else:
                    win_id, lose_id = pb['clan_id'], pa['clan_id']

                c.execute("UPDATE clans SET score=score+1 WHERE id=%s", (win_id,))
                c.execute("UPDATE clans SET score=score-1 WHERE id=%s", (lose_id,))

                c.execute(
                    "INSERT INTO matches "
                    "(clan_a_id, clan_b_id, winner_id, loser_id, score_before_a, score_before_b, "
                    " is_registered, created_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,1,%s)",
                    (pa['clan_id'], pb['clan_id'], win_id, lose_id, sa, sb, pa['user_id']))

                for u in [pa, pb]:
                    try:
                        c.execute("INSERT INTO round_registrations (round_id, user_id, clan_id) VALUES (%s,%s,%s)",
                                  (round_id, u['user_id'], u['clan_id']))
                    except Exception:
                        pass

                win_name = pa['clan_name'] if win_id == pa['clan_id'] else pb['clan_name']
                lose_name = pa['clan_name'] if lose_id == pa['clan_id'] else pb['clan_name']
                summary["matches"].append({
                    "type": "registered", "winner": win_name, "loser": lose_name,
                    "before_a": sa, "before_b": sb
                })
                summary["registered_count"] += 1
                _log(f"    ✅ 第{round_no}轮已登记 [{idx+1}] {win_name}(+1) vs {lose_name}(-1)")

            # 1 场未登记 - 其他联盟
            p9 = players[8]
            c.execute("SELECT score FROM clans WHERE id=%s", (p9['clan_id'],))
            s9 = c.fetchone()['score']
            c.execute("INSERT INTO clans (name, code, contact) VALUES (%s,%s,%s)",
                      ('外部联盟部落A', f'UNREG_EXTRA{round_no}A', '未登记部落'))
            u1 = c.lastrowid
            try:
                c.execute("INSERT INTO unknown_clans (name, code, tags) VALUES (%s,%s,%s)",
                          ('外部联盟部落A', f'EXTRA{round_no}01', '其他联盟'))
            except Exception:
                pass
            c.execute(
                "INSERT INTO matches "
                "(clan_a_id, clan_b_id, winner_id, loser_id, score_before_a, score_before_b, "
                " is_registered, remark, created_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,0,%s,%s)",
                (p9['clan_id'], u1, u1, p9['clan_id'], s9, 0, '匹配到其他联盟', p9['user_id']))
            try:
                c.execute("INSERT INTO round_registrations (round_id, user_id, clan_id) VALUES (%s,%s,%s)",
                          (round_id, p9['user_id'], p9['clan_id']))
            except Exception:
                pass
            summary["matches"].append({
                "type": "unregistered", "clan": p9['clan_name'],
                "remark": "匹配到其他联盟", "result": "⏳ 待定"
            })
            summary["unregistered_count"] += 1
            _log(f"    ⏳ 第{round_no}轮未登记-待定 [{p9['clan_name']}]")

            # 1 场未登记 - 实战营
            p10 = players[9]
            c.execute("SELECT score FROM clans WHERE id=%s", (p10['clan_id'],))
            s10 = c.fetchone()['score']
            c.execute("INSERT INTO clans (name, code, contact) VALUES (%s,%s,%s)",
                      ('实战营X', f'UNREG_TRAIN{round_no}B', '未登记部落'))
            u2 = c.lastrowid
            try:
                c.execute("INSERT INTO unknown_clans (name, code, tags) VALUES (%s,%s,%s)",
                          ('实战营X', f'TRAIN{round_no}01', '实战营'))
            except Exception:
                pass
            c.execute(
                "INSERT INTO matches "
                "(clan_a_id, clan_b_id, winner_id, loser_id, score_before_a, score_before_b, "
                " is_registered, remark, created_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,0,%s,%s)",
                (p10['clan_id'], u2, u2, p10['clan_id'], s10, 0, '匹配到实战营', p10['user_id']))
            try:
                c.execute("INSERT INTO round_registrations (round_id, user_id, clan_id) VALUES (%s,%s,%s)",
                          (round_id, p10['user_id'], p10['clan_id']))
            except Exception:
                pass
            summary["matches"].append({
                "type": "unregistered", "clan": p10['clan_name'],
                "remark": "匹配到实战营", "result": "📢 以部落管理通知为准"
            })
            summary["unregistered_count"] += 1
            _log(f"    📢 第{round_no}轮未登记-管理通知 [{p10['clan_name']}]")

            # 只关闭第1轮，第2轮保持 open 状态让用户能看到当前轮次
            if round_no == 1:
                c.execute("UPDATE rounds SET status='closed', closed_by=%s, closed_at=NOW() WHERE id=%s",
                          (admin_id, round_id))
                _log(f"    🏁 第{round_no}轮已关闭")
            else:
                _log(f"    🔄 第{round_no}轮保持开启状态（用户可继续登记）")

    return summary


def _build_report(admin_id, players, round1, round2) -> dict:
    """构建报告"""
    with get_db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) as cnt FROM matches")
            total = c.fetchone()['cnt']
            c.execute("SELECT COUNT(*) as cnt FROM matches WHERE is_registered=1")
            reg = c.fetchone()['cnt']
            c.execute("SELECT COUNT(*) as cnt FROM matches WHERE is_registered=0")
            unreg = c.fetchone()['cnt']

            c.execute("SELECT id, name, code, score FROM clans WHERE code NOT LIKE 'UNREG_%' ORDER BY score DESC")
            clans = c.fetchall()

            c.execute("SELECT role, COUNT(*) as cnt FROM users GROUP BY role")
            roles = c.fetchall()

            clan_changes = []
            for p in players:
                c.execute("SELECT score FROM clans WHERE id=%s", (p['clan_id'],))
                cur = c.fetchone()['score']
                delta = cur - p['initial_score']
                clan_changes.append({
                    "clan_name": p['clan_name'],
                    "username": p['username'],
                    "initial": p['initial_score'],
                    "current": cur,
                    "delta": delta
                })

    return {
        "ok": True,
        "summary": {
            "users": {"admin": 1, "players": len(players), "monitor": 1, "total": 2 + len(players)},
            "clans": len(clans),
            "rounds": 2,
            "matches": {"total": total, "registered": reg, "unregistered": unreg}
        },
        "round1": round1,
        "round2": round2,
        "leaderboard": [
            {"rank": i+1, "name": cl['name'], "code": cl['code'], "score": cl['score']}
            for i, cl in enumerate(clans)
        ],
        "clan_changes": clan_changes,
        "test_accounts": {
            "admin": "admin / admin123 (超管)",
            "players": [f"{p['username']} / 123456" for p in players]
        },
        "message": "✅ 模拟数据已写入数据库，登录后即可查看"
    }
