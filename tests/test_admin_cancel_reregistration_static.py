import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


class AdminCancelReregistrationStaticTests(unittest.TestCase):
    def test_database_defines_cancel_notice_table(self):
        database = read("database.py")
        self.assertIn("CREATE TABLE IF NOT EXISTS round_cancel_notices", database)
        self.assertIn("uk_round_cancel_notice", database)

    def test_admin_cancel_records_notice_before_deleting_registration(self):
        admin = read("routers/admin.py")
        self.assertIn("INSERT INTO round_cancel_notices", admin)
        self.assertIn("管理员已撤销您的本轮登记，请重新登记", admin)
        self.assertIn("SELECT DISTINCT user_id, clan_id", admin)
        self.assertIn("DELETE FROM round_registrations WHERE round_id = %s AND user_id IN", admin)
        self.assertLess(
            admin.index("INSERT INTO round_cancel_notices"),
            admin.index("DELETE FROM round_registrations WHERE round_id"),
        )

    def test_me_returns_cancel_notice(self):
        auth = read("routers/auth.py")
        self.assertIn("cancel_notice", auth)
        self.assertIn("FROM round_cancel_notices", auth)
        self.assertIn('my_registration = {"registered": False, "registered_at": None}', auth)
        self.assertIn('"cancel_notice": cancel_notice', auth)

    def test_player_registration_clears_cancel_notice(self):
        player = read("routers/player.py")
        self.assertGreaterEqual(player.count("DELETE FROM round_cancel_notices"), 2)
        self.assertIn("成员不能自行撤销登记，请联系管理员处理", player)

    def test_member_ui_does_not_render_cancel_button_and_shows_notice(self):
        app = read("static/app.js")
        self.assertNotIn('onclick="cancelMatch(', app)
        self.assertIn("renderAdminCancelNotice", app)
        self.assertIn("管理员已撤销您的本轮登记，请重新登记", app)

    def test_score_adjustment_creates_system_notification(self):
        admin = read("routers/admin.py")
        self.assertIn("INSERT INTO notifications", admin)
        self.assertIn("管理员调整了", admin)
        self.assertIn("积分：", admin)
        self.assertLess(
            admin.index("UPDATE clans SET score"),
            admin.index("INSERT INTO notifications"),
        )

    def test_unregistered_match_copy_says_score_unchanged(self):
        app = read("static/app.js")
        self.assertIn("积分保持不变", app)
        self.assertNotIn("默认判输（-1分）", app)

    def test_loss_copy_uses_lose_not_failure(self):
        app = read("static/app.js")
        self.assertIn('<div class="banner-big-text">✗ 输</div>', app)
        self.assertNotIn('<div class="banner-big-text">✗ 失败</div>', app)


if __name__ == "__main__":
    unittest.main()
