"""
部落对战系统 - 数据模拟脚本 (SQLite版本)
=====================================
创建：管理员 + 10个玩家 + 绑定部落
进行：2轮对战匹配
输出：完整统计报告
数据保留在 clan_arena_sim.db
"""
import sys
import os
import sqlite3
import bcrypt
import random
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clan_arena_sim.db')


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                plain_password VARCHAR(100) DEFAULT '',
                role TEXT DEFAULT 'player',
                is_super_admin INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                must_change_pwd INTEGER DEFAULT 1,
                cancel_count_round_id INTEGER DEFAULT NULL,
                cancel_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                code VARCHAR(50) UNIQUE NOT NULL,
                contact VARCHAR(200) DEFAULT '',
                score INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_clan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                clan_id INTEGER NOT NULL,
                bound_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (user_id, clan_id)
            );

            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_a_id INTEGER NOT NULL,
                clan_b_id INTEGER NOT NULL,
                winner_id INTEGER,
                loser_id INTEGER,
                score_before_a INTEGER,
                score_before_b INTEGER,
                is_registered INTEGER DEFAULT 1,
                remark TEXT,
                config_remark VARCHAR(500) DEFAULT NULL,
                created_by INTEGER,
                confirmed_by INTEGER DEFAULT NULL,
                matched_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_no INTEGER NOT NULL,
                status TEXT DEFAULT 'open',
                opened_by INTEGER,
                closed_by INTEGER DEFAULT NULL,
                opened_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME DEFAULT NULL,
                match_start_time DATETIME DEFAULT NULL,
                match_end_time DATETIME DEFAULT NULL,
                next_round_time DATETIME DEFAULT NULL,
                config_required INTEGER DEFAULT 0,
                maintenance INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS round_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                clan_id INTEGER NOT NULL,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (round_id, user_id, clan_id)
            );

            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action VARCHAR(50) NOT NULL,
                target_type VARCHAR(50),
                target_id INTEGER,
                detail TEXT,
                reason VARCHAR(200),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS unknown_clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                code VARCHAR(50) NOT NULL,
                tags VARCHAR(200) DEFAULT '',
                encounter_count INTEGER DEFAULT 1,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (code)
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS score_guide (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        print("✅ 数据库表结构已就绪")
    finally:
        conn.close()


def hash_pwd(pwd):
    return bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def clear_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        for table in ['operation_logs', 'round_registrations', 'matches',
                      'user_clan', 'clans', 'notifications', 'unknown_clans', 'rounds']:
            c.execute(f"DELETE FROM {table}")
        c.execute("DELETE FROM users WHERE username NOT IN ('admin', 'monitor')")
        conn.commit()
        print("🔄 数据库已重置（保留admin/monitor账号）")
    finally:
        conn.close()


def create_users():
    conn = get_conn()
    try:
        c = conn.cursor()

        # 1. 确保超管admin存在
        c.execute("SELECT id FROM users WHERE username='admin'")
        row = c.fetchone()
        if row:
            admin_id = row['id']
            c.execute("UPDATE users SET is_super_admin=1, role='admin' WHERE id=?", (admin_id,))
        else:
            c.execute("INSERT INTO users (username, password_hash, plain_password, role, is_super_admin, must_change_pwd) "
                      "VALUES (?, ?, ?, 'admin', 1, 0)",
                      ('admin', hash_pwd('admin123'), 'admin123'))
            admin_id = c.lastrowid
        print(f"👑 超管 admin (ID={admin_id})")

        # 2. 为admin绑定一个部落
        c.execute("SELECT id FROM clans WHERE code='ADMIN001'")
        row = c.fetchone()
        if row:
            admin_clan_id = row['id']
        else:
            c.execute("INSERT INTO clans (name, code, contact, score) VALUES (?,?,?,0)",
                      ('管理部落', 'ADMIN001', 'system'))
            admin_clan_id = c.lastrowid
        c.execute("INSERT OR IGNORE INTO user_clan (user_id, clan_id) VALUES (?,?)",
                  (admin_id, admin_clan_id))

        # 3. 创建10个玩家 + 绑定部落
        player_names = ['阿强', '小美', '大勇', '小花', '阿龙',
                        '小倩', '小胖', '小芳', '阿伟', '小燕']
        players = []
        for i, name in enumerate(player_names):
            username = f"player{i+1:02d}"
            password = "123456"
            clan_name = f"部落{name}"
            clan_code = f"CL{i+1:03d}"
            initial_score = random.randint(10, 19)

            c.execute("INSERT INTO users (username, password_hash, plain_password, role, must_change_pwd) "
                      "VALUES (?, ?, ?, 'player', 1)",
                      (username, hash_pwd(password), password))
            user_id = c.lastrowid

            c.execute("INSERT INTO clans (name, code, contact, score) VALUES (?,?,?,?)",
                      (clan_name, clan_code, f"玩家{i+1}", initial_score))
            clan_id = c.lastrowid

            c.execute("INSERT INTO user_clan (user_id, clan_id) VALUES (?,?)",
                      (user_id, clan_id))

            players.append({
                'user_id': user_id, 'username': username, 'password': password,
                'name': name, 'clan_id': clan_id, 'clan_name': clan_name,
                'clan_code': clan_code, 'initial_score': initial_score
            })
            print(f"  🎮 {username} ({name}) → {clan_name} [{clan_code}] 初始积分={initial_score}")

        conn.commit()
        print(f"✅ 共创建 {len(players)} 个玩家")
        return admin_id, players
    finally:
        conn.close()


def open_round(admin_id, round_no):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO rounds (round_no, status, opened_by) VALUES (?, 'open', ?)",
                  (round_no, admin_id))
        round_id = c.lastrowid
        conn.commit()
        print(f"\n🎯 第 {round_no} 轮对战已开启 (Round ID={round_id})")
        return round_id
    finally:
        conn.close()


def close_round(admin_id, round_id, round_no):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("UPDATE rounds SET status='closed', closed_by=?, closed_at=DATETIME('now') WHERE id=?",
                  (admin_id, round_id))
        conn.commit()
        print(f"🏁 第 {round_no} 轮对战已结束")
    finally:
        conn.close()


def do_match_round(round_id, admin_id, players, round_no):
    """
    进行一轮对战：
    - 8人进行已登记对战（4场）
    - 1人进行未登记对战（匹配到其他联盟 → 待定）
    - 1人进行未登记对战（匹配到实战营 → 以管理通知为准）
    """
    print(f"\n── 第 {round_no} 轮对战开始 ──")
    conn = get_conn()

    try:
        c = conn.cursor()
        random.shuffle(players)

        # 已登记对战
        registered_pairs = [(players[0], players[1]),
                            (players[2], players[3]),
                            (players[4], players[5]),
                            (players[6], players[7])]

        for idx, (p_a, p_b) in enumerate(registered_pairs):
            c.execute("SELECT score FROM clans WHERE id=?", (p_a['clan_id'],))
            score_a = c.fetchone()['score']
            c.execute("SELECT score FROM clans WHERE id=?", (p_b['clan_id'],))
            score_b = c.fetchone()['score']

            if score_a == score_b:
                winner_clan_id, loser_clan_id = random.choice([
                    (p_a['clan_id'], p_b['clan_id']),
                    (p_b['clan_id'], p_a['clan_id'])
                ])
            elif score_a < score_b:
                winner_clan_id, loser_clan_id = p_a['clan_id'], p_b['clan_id']
            else:
                winner_clan_id, loser_clan_id = p_b['clan_id'], p_a['clan_id']

            c.execute("UPDATE clans SET score=score+1 WHERE id=?", (winner_clan_id,))
            c.execute("UPDATE clans SET score=score-1 WHERE id=?", (loser_clan_id,))

            c.execute("""INSERT INTO matches
                (clan_a_id, clan_b_id, winner_id, loser_id, score_before_a, score_before_b,
                 is_registered, created_by)
                VALUES (?,?,?,?,?,?,1,?)""",
                (p_a['clan_id'], p_b['clan_id'], winner_clan_id, loser_clan_id,
                 score_a, score_b, p_a['user_id']))

            # 登记
            c.execute("INSERT OR IGNORE INTO round_registrations (round_id, user_id, clan_id) VALUES (?,?,?)",
                      (round_id, p_a['user_id'], p_a['clan_id']))
            c.execute("INSERT OR IGNORE INTO round_registrations (round_id, user_id, clan_id) VALUES (?,?,?)",
                      (round_id, p_b['user_id'], p_b['clan_id']))

            winner_name = p_a['clan_name'] if winner_clan_id == p_a['clan_id'] else p_b['clan_name']
            loser_name = p_a['clan_name'] if loser_clan_id == p_a['clan_id'] else p_b['clan_name']
            print(f"  ✅ 已登记 [{idx+1}] {winner_name}(+1) vs {loser_name}(-1)")

        # 未登记对战1：玩家9 → 其他联盟（待定）
        p9 = players[8]
        c.execute("SELECT score FROM clans WHERE id=?", (p9['clan_id'],))
        p9_score = c.fetchone()['score']

        c.execute("INSERT INTO clans (name, code, contact) VALUES (?,?,?)",
                  ('外部联盟部落A', f'UNREG_EXTRA{round_no}A', '未登记部落'))
        unreg_clan1_id = c.lastrowid
        c.execute("INSERT OR IGNORE INTO unknown_clans (name, code, tags) VALUES (?,?,?)",
                  ('外部联盟部落A', f'EXTRA{round_no}01', '其他联盟'))

        c.execute("""INSERT INTO matches
            (clan_a_id, clan_b_id, winner_id, loser_id, score_before_a, score_before_b,
             is_registered, remark, created_by)
            VALUES (?,?,?,?,?,?,0,?,?)""",
            (p9['clan_id'], unreg_clan1_id, unreg_clan1_id, p9['clan_id'],
             p9_score, 0, '匹配到其他联盟', p9['user_id']))
        c.execute("INSERT OR IGNORE INTO round_registrations (round_id, user_id, clan_id) VALUES (?,?,?)",
                  (round_id, p9['user_id'], p9['clan_id']))
        print(f"  ⏳ 未登记-待定 [{p9['clan_name']}] 匹配到其他联盟（积分不变）")

        # 未登记对战2：玩家10 → 实战营（以管理通知为准）
        p10 = players[9]
        c.execute("SELECT score FROM clans WHERE id=?", (p10['clan_id'],))
        p10_score = c.fetchone()['score']

        c.execute("INSERT INTO clans (name, code, contact) VALUES (?,?,?)",
                  ('实战营X', f'UNREG_TRAIN{round_no}B', '未登记部落'))
        unreg_clan2_id = c.lastrowid
        c.execute("INSERT OR IGNORE INTO unknown_clans (name, code, tags) VALUES (?,?,?)",
                  ('实战营X', f'TRAIN{round_no}01', '实战营'))

        c.execute("""INSERT INTO matches
            (clan_a_id, clan_b_id, winner_id, loser_id, score_before_a, score_before_b,
             is_registered, remark, created_by)
            VALUES (?,?,?,?,?,?,0,?,?)""",
            (p10['clan_id'], unreg_clan2_id, unreg_clan2_id, p10['clan_id'],
             p10_score, 0, '匹配到实战营', p10['user_id']))
        c.execute("INSERT OR IGNORE INTO round_registrations (round_id, user_id, clan_id) VALUES (?,?,?)",
                  (round_id, p10['user_id'], p10['clan_id']))
        print(f"  📢 未登记-管理通知 [{p10['clan_name']}] 匹配到实战营（积分不变）")

        conn.commit()
        print(f"  ✔  本轮完成 6 场对战（4 已登记 + 2 未登记）")
    finally:
        conn.close()


def report(players):
    conn = get_conn()
    try:
        c = conn.cursor()
        print("\n" + "=" * 60)
        print("📊 部落对战系统 - 模拟数据报告")
        print("=" * 60)

        # 轮次
        c.execute("SELECT round_no, status, opened_at, closed_at FROM rounds ORDER BY round_no")
        rounds = c.fetchall()
        print(f"\n🎯 对战轮次：{len(rounds)} 轮")
        for r in rounds:
            icon = '🔄' if r['status'] == 'open' else '🏁'
            print(f"   {icon} 第{r['round_no']}轮 [{r['status']}]  "
                  f"开始:{r['opened_at'][:19]}  结束:{r['closed_at'][:19] if r['closed_at'] else '-'}")

        # 对战统计
        c.execute("SELECT COUNT(*) as cnt FROM matches")
        total_matches = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM matches WHERE is_registered=1")
        reg_matches = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM matches WHERE is_registered=0")
        unreg_matches = c.fetchone()['cnt']

        print(f"\n⚔️  总对战数: {total_matches} 场")
        print(f"   ✅ 已登记对战: {reg_matches} 场")
        print(f"   ❓ 未登记对战: {unreg_matches} 场")

        # 部落积分排行榜
        c.execute("SELECT id, name, code, score FROM clans WHERE code NOT LIKE 'UNREG_%' ORDER BY score DESC")
        all_clans = c.fetchall()
        print(f"\n🏆 部落积分排行榜（共 {len(all_clans)} 个部落）:")
        print("   " + "-" * 55)
        for i, cl in enumerate(all_clans):
            medal = ['🥇', '🥈', '🥉'][i] if i < 3 else f"  {i+1:2d}."
            bar_len = min(50, max(0, cl['score'] * 2))
            bar = '█' * bar_len if bar_len > 0 else ''
            print(f"   {medal} {cl['name']:12s} [{cl['code']:8s}]  积分: {cl['score']:3d}  {bar}")

        # 未登记对战详情
        c.execute("""SELECT m.*, ca.name as clan_a_name, cb.name as clan_b_name
                     FROM matches m
                     JOIN clans ca ON m.clan_a_id = ca.id
                     JOIN clans cb ON m.clan_b_id = cb.id
                     WHERE m.is_registered=0
                     ORDER BY m.matched_at""")
        unreg = c.fetchall()
        if unreg:
            print(f"\n📝 未登记对战详情（共 {len(unreg)} 场，积分全部不变）:")
            print("   " + "-" * 55)
            for m in unreg:
                remark = m['remark'] or ''
                if '其他联盟' in remark or '其他' in remark:
                    result = '⏳ 待定（积分保持不变，等待外部确认）'
                else:
                    result = '📢 以部落管理员通知为准（积分不变）'
                print(f"   • {m['clan_a_name']} vs {m['clan_b_name']}")
                print(f"     类型: {remark}")
                print(f"     结果: {result}")

        # 每部落变化明细
        print(f"\n📈 部落积分变化（从初始到当前）:")
        print("   " + "-" * 55)
        for p in players:
            c.execute("SELECT score FROM clans WHERE id=?", (p['clan_id'],))
            cur_score = c.fetchone()['score']
            delta = cur_score - p['initial_score']
            delta_str = f"(+{delta})" if delta > 0 else f"({delta})" if delta < 0 else "(=)"
            print(f"   {p['clan_name']:12s} 初始:{p['initial_score']:3d} → 当前:{cur_score:3d}  {delta_str}")

        # 用户统计
        c.execute("SELECT role, COUNT(*) as cnt FROM users GROUP BY role")
        roles = c.fetchall()
        print(f"\n👥 用户统计:")
        for r in roles:
            icon = {'admin': '👑', 'player': '🎮', 'monitor': '🛡️ '}.get(r['role'], '👤')
            print(f"   {icon} {r['role']:8s}: {r['cnt']} 人")

        # 登记统计
        c.execute("SELECT COUNT(*) as cnt FROM round_registrations")
        reg_count = c.fetchone()['cnt']
        print(f"\n📝 累计轮次登记: {reg_count} 条")

        # 陌生部落
        c.execute("SELECT COUNT(*) as cnt FROM unknown_clans")
        unknown_count = c.fetchone()['cnt']
        print(f"🌍 陌生部落数据库: {unknown_count} 个部落")

        # 登录账号提示
        print(f"\n🔐 测试账号:")
        print(f"   👑 管理员: admin / admin123 (super admin)")
        print(f"   🎮 玩家: player01 ~ player10，密码均为: 123456")
        print(f"   例: player01 (阿强) / 123456")

        print(f"\n📁 数据库文件: {DB_FILE}")
        print(f"   （数据已全部保留，可随时查看/重复运行）")

        print("\n" + "=" * 60)
        print("✅ 模拟完成！")
        print("=" * 60 + "\n")

    finally:
        conn.close()


def main():
    print("🎮 部落对战系统 - 数据模拟 (SQLite)")
    print("=" * 60)

    init_db()
    clear_db()

    # Step 1
    print("\n── Step 1: 创建用户 ──")
    admin_id, players = create_users()

    # Step 2
    print("\n── Step 2: 第1轮对战 ──")
    round1_id = open_round(admin_id, 1)
    do_match_round(round1_id, admin_id, players, 1)
    close_round(admin_id, round1_id, 1)

    # Step 3
    print("\n── Step 3: 第2轮对战 ──")
    round2_id = open_round(admin_id, 2)
    do_match_round(round2_id, admin_id, players, 2)
    close_round(admin_id, round2_id, 2)

    # Report
    report(players)


if __name__ == "__main__":
    main()
