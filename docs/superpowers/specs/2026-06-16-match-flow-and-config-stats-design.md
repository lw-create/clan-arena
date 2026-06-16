# 匹配登记流程改造 & 配置统计 & 时间设置简化 设计文档

- 创建日期：2026-06-16
- 仓库：`lw-create/clan-arena`
- 影响范围：玩家端 UI、管理员端 UI、后端接口、数据库

---

## 1. 背景与目标

当前问题：

1. 玩家端「匹配成功」「未匹配成功」两个卡片**默认同时展示**，信息冗余，玩家不清楚先点哪一个。
2. 「配置登记」目前只是一个自由文本框，没有结构化数据，管理员无法做任何统计与分析。
3. 轮次时间设置中「本轮开始 / 本轮结束 / 下一轮时间」三项里，本轮时间对成员意义不大；下一轮的「时间」其实是一个时间段而不是单一时刻。

本次目标：

- 用一个**登记提醒弹窗**作为入口，引导玩家二选一，再展开对应卡片，避免两张卡片同时挤在页面上。
- 把「配置登记」升级为**结构化的配置统计**：分栏录入（大本营等级 + 人数），管理员可看到原始数据与跨部落聚合平均值。
- 简化轮次时间设置：删除本轮时间，只保留**下一轮匹配时间段**（`开始 ~ 结束`）。

---

## 2. 玩家端：登记提醒弹窗 + 卡片切换

### 2.1 触发条件

满足全部条件时，**登录后第一次进入玩家面板**自动弹出 `登记提醒弹窗`：

1. 当前存在状态为 `open` 的轮次（轮次开启中）。
2. 当前用户**至少绑定 1 个部落**。
3. 当前用户在该轮次的登记记录为空（`round_registrations` 中无该用户记录）。

弹出策略：**只弹一次**。同一次会话内（不刷新页面），关闭后不再自动弹。下次重新登录或刷新进入时再判断。

> 实现方式：用 `sessionStorage` 中 `match_prompt_shown_round_<round_id>` 标记是否已弹过，弹过即写入；每次进入玩家面板时检查该标记。

### 2.2 弹窗内容

```text
┌───────────────────────────────────────────────┐
│ 🔔 部落战登记提醒                              │
│                                               │
│ 当前轮次进行中，您还没有登记本轮匹配结果。     │
│ 请选择本轮的匹配情况：                         │
│                                               │
│ ┌──────────────┐   ┌──────────────────────┐  │
│ │ ✅ 匹配成功  │   │ ❌ 未匹配成功         │  │
│ │              │   │（含匹配到其他联盟）  │  │
│ └──────────────┘   └──────────────────────┘  │
│                                               │
│                        [稍后再说]              │
└───────────────────────────────────────────────┘
```

按钮行为：

- 点 `✅ 匹配成功` → 关闭弹窗，展开「匹配成功」卡片，自动滚动到该卡片，隐藏「未匹配成功」卡片。
- 点 `❌ 未匹配成功` → 关闭弹窗，展开「未匹配成功」卡片，自动滚动到该卡片，隐藏「匹配成功」卡片。
- 点 `稍后再说` 或点弹窗外部关闭 → 仅关闭弹窗，两张卡片都不显示，玩家可自行通过页面上其他入口触发。

### 2.3 卡片切换

页面初始状态：

- 默认两张卡片都**隐藏**。
- 玩家在弹窗里点击之后，对应卡片显示。
- 已登记成功的玩家（已有 `round_registrations` 记录），默认两张卡片都**隐藏**，仅显示「已登记」结果区。

卡片底部增加切换链接：

- 在 `匹配成功` 卡片底部增加：
  ```text
  其实没匹配上？→ 切换为未匹配成功
  ```
  点击后隐藏当前卡片，展开「未匹配成功」卡片。
- 在 `未匹配成功` 卡片底部增加：
  ```text
  其实匹配上了？→ 切换为匹配成功
  ```
  点击后隐藏当前卡片，展开「匹配成功」卡片。

> 切换链接样式：小字、灰色、靠右，避免抢主按钮焦点。

### 2.4 涉及的前端改动

文件：`static/index.html`、`static/app.js`、`static/style.css`

- `index.html`：
  - 新增 `<div id="match-prompt-modal" class="modal">…</div>` 弹窗结构。
  - `match-card`（匹配成功）和未匹配成功表单（目前混在一个卡片里）拆成**两个独立卡片**，两个 ID：
    - `match-success-card`
    - `match-failed-card`
  - 默认两个 `display:none`。
  - 各自卡片底部加切换链接。
- `app.js`：
  - 在玩家面板初始化逻辑里增加 `maybeShowMatchPrompt()`，根据条件控制弹窗显示。
  - 增加 `chooseMatchSuccess()` / `chooseMatchFailed()` 控制卡片显示。
  - 增加 `switchToFailed()` / `switchToSuccess()` 处理切换链接点击。

---

## 3. 配置统计（结构化重做）

### 3.1 全局开关

- 位置：管理员端 → `轮次管理` → `⏰ 设置本轮时间` 卡片中（与已有 `要求成员填写对战配置`、`维护模式` 并列），新增第三个 checkbox：
  ```text
  📊 启用配置统计（成员可填写本部落的大本营等级与人数分布）
  ```
- 这个开关**全局生效**，**不绑定轮次**。管理员手动开启/关闭。
- 关闭时：
  - 玩家端不显示「配置统计」入口与卡片。
  - 管理员后台仍能看到已收集的数据（保留），并提供 `🗑 清空全部配置数据` 按钮，手动清空。
- 重新开启时：旧数据仍在，玩家可继续修改自己部落的配置。

### 3.2 数据模型

#### 3.2.1 新增表 `clan_configs`

存储**每个部落最新一份**配置。每次提交以 `clan_id` 为主键覆盖。

```sql
CREATE TABLE IF NOT EXISTS clan_configs (
    clan_id INTEGER PRIMARY KEY,
    target_total INTEGER NOT NULL CHECK(target_total IN (40, 50)),
    updated_by INTEGER NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (clan_id) REFERENCES clans(id) ON DELETE CASCADE,
    FOREIGN KEY (updated_by) REFERENCES users(id)
);
```

#### 3.2.2 新增表 `clan_config_items`

每个部落的若干「分栏」明细，1 行 = 1 栏。

```sql
CREATE TABLE IF NOT EXISTS clan_config_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clan_id INTEGER NOT NULL,
    th_level INTEGER NOT NULL CHECK(th_level BETWEEN 0 AND 100),
    member_count INTEGER NOT NULL CHECK(member_count BETWEEN 0 AND 50),
    sort_order INTEGER DEFAULT 0,
    FOREIGN KEY (clan_id) REFERENCES clans(id) ON DELETE CASCADE,
    UNIQUE(clan_id, th_level)
);
```

唯一约束 `UNIQUE(clan_id, th_level)` 用于在数据库层强制「同一部落同一等级不重复」。

#### 3.2.3 新增 `system_settings` 表（用于全局开关）

```sql
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

记录键 `config_stats_enabled` = `'1'` / `'0'`。

> 同时为以后扩展其他全局开关预留空间。

### 3.3 玩家端录入界面

仅当 `config_stats_enabled = 1` 时显示。

界面初始结构：

```text
┌────────── 📊 配置统计 ──────────┐
│ 选择部落： [我的部落 ▾]         │
│ 总人数目标： ◯ 40 人  ◯ 50 人   │
│                                 │
│  ┌─ 第 1 栏 ────────────────┐   │
│  │ 大本营等级 [10 ▾]        │   │
│  │ 成员数量   [12 ▾]   [×]  │   │
│  └──────────────────────────┘   │
│                                 │
│  [+ 添加一栏]                   │
│                                 │
│ 当前合计：12 / 40              │
│                                 │
│  [💾 保存配置]                  │
└─────────────────────────────────┘
```

要点：

- 默认 1 栏。点 `+ 添加一栏` 追加。点每栏右上角 `×` 删除。
- `大本营等级`：下拉框，选项为 `0` 到 `100`。
- `成员数量`：下拉框，选项为 `0` 到 `40`。
- `总人数目标`：必填，二选一（40 / 50）。
- `当前合计` 实时计算所有栏 `member_count` 之和：
  - 等于 `target_total` → 绿色。
  - 不等于 → 红色，并禁用 `保存配置` 按钮。
- 提交前前端校验：
  - 等级值不能在多栏中重复（重复时给出红色提示「大本营等级 X 不能重复出现」）。
  - 合计必须等于 `target_total`。
- 保存后服务端再次校验，写入 `clan_configs`（覆盖）和 `clan_config_items`（先全删旧的，再批量插入新的，事务）。
- 多个绑定部落的玩家：通过部落选择下拉框切换，每个部落独立一份配置。

### 3.4 管理员端视图

新增 `tab-config-stats`（标签页 `📊 配置统计`，紧挨现有的 `匹配统计`）。仅当 `config_stats_enabled = 1` 时启用入口；关闭时入口隐藏，但管理员仍可在「轮次管理」卡片里看到 `🗑 清空全部配置数据` 按钮。

页面包含三块卡片：

#### 3.4.1 总览：按大本营等级聚合

| 大本营等级 | 已填部落数 | 总人数 | 平均每部落人数 |
| --- | --- | --- | --- |
| 17 本 | 8 | 64 | 8.0 |
| 16 本 | 8 | 96 | 12.0 |
| ... | ... | ... | ... |

聚合 SQL（示意）：

```sql
SELECT th_level,
       COUNT(DISTINCT clan_id) AS clan_count,
       SUM(member_count)       AS total_members,
       ROUND(SUM(member_count) * 1.0 / COUNT(DISTINCT clan_id), 2) AS avg_per_clan
FROM clan_config_items
GROUP BY th_level
ORDER BY th_level DESC;
```

#### 3.4.2 部落明细列表

| 部落 | 总人数 | 配置 | 更新时间 |
| --- | --- | --- | --- |
| 风暴 #ABC | 40 | 17×12, 16×18, 15×10 | 06-15 18:02 |
| 烈焰 #XYZ | 50 | 17×8, 16×20, 15×15, 14×7 | 06-15 19:33 |

#### 3.4.3 未填清单

列出所有数据库中存在但 `clan_configs` 没有记录的部落，便于管理员催。

#### 3.4.4 清空按钮

`🗑 清空全部配置数据`，确认后删除 `clan_config_items` 和 `clan_configs` 全部数据，写一条 `operation_logs`。

### 3.5 后端接口（新增）

放在 `routers/admin.py` 与 `routers/player.py` 中：

| 方法 | 路径 | 角色 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/settings/config-stats` | 任意已登录 | 读取 `config_stats_enabled` 开关值 |
| POST | `/api/admin/settings/config-stats` | admin | 设置 `config_stats_enabled`，body `{enabled: bool}` |
| GET | `/api/player/clan-config?clan_id=` | player | 读取本人某绑定部落当前配置 |
| POST | `/api/player/clan-config` | player | 保存某部落配置 |
| DELETE | `/api/admin/clan-configs` | admin | 清空全部配置统计数据 |
| GET | `/api/admin/config-stats/overview` | admin | 总览（按 TH 等级聚合） |
| GET | `/api/admin/config-stats/clans` | admin | 部落明细 + 未填清单 |

POST `/api/player/clan-config` 请求体示意：

```json
{
  "clan_id": 12,
  "target_total": 40,
  "items": [
    { "th_level": 17, "member_count": 12 },
    { "th_level": 16, "member_count": 18 },
    { "th_level": 15, "member_count": 10 }
  ]
}
```

服务端校验：

1. `target_total` ∈ {40, 50}。
2. `items` 非空。
3. `th_level` 范围 0–100，无重复。
4. `member_count` 范围 0–40。
5. `sum(member_count) == target_total`。
6. `clan_id` 必须是当前用户的绑定部落之一。

不通过即返回 400 + 中文错误。

事务：先 `DELETE FROM clan_config_items WHERE clan_id=?`，再批量 `INSERT`，再 `INSERT OR REPLACE INTO clan_configs`。

---

## 4. 时间设置简化

### 4.1 数据库变更

`rounds` 表：

- 删除字段：`match_start_time`、`match_end_time`、`next_round_time`
- 新增字段：`next_match_start_time`、`next_match_end_time`

> 由于 SQLite 删除列稍麻烦，可以选择保留旧字段不再使用，仅新增两个字段，等下次结构整理时一起清理。本设计采用「新增、不删除」做法，迁移更安全。

迁移步骤：

```sql
ALTER TABLE rounds ADD COLUMN next_match_start_time DATETIME DEFAULT NULL;
ALTER TABLE rounds ADD COLUMN next_match_end_time   DATETIME DEFAULT NULL;
```

旧的 `match_start_time` / `match_end_time` / `next_round_time` 字段保留但不再被代码使用，前后端不再读写。

### 4.2 管理员端

`轮次管理 → ⏰ 设置本轮时间` 卡片：

- ❌ 删除：`本轮匹配开始时间`、`本轮匹配结束时间`、`下一轮匹配时间` 三个 datetime 输入框。
- ✅ 新增：`下一轮匹配开始时间` + `下一轮匹配结束时间` 两个 datetime-local 输入框。
- ✅ 保留：`要求成员填写对战配置`、`维护模式` 开关。
- ✅ 新增：`📊 启用配置统计` 开关（详见 §3.1）。
- 标题可以从 `⏰ 设置本轮时间` 改为更准确的 `⏰ 轮次与时间设置`。

校验：保存时如果两个时间都填了，必须满足 `开始 < 结束`，否则返回错误。允许两个都为空（表示尚未公布）。

### 4.3 玩家端

「轮次时间卡片」改为只显示一行：

```text
🕐 下一轮匹配时间
2026-06-20 09:00 ~ 2026-06-20 21:00
```

如果未设置则显示「下一轮匹配时间未公布」。

### 4.4 后端接口

- `GET /api/round/current` 返回当前轮次时增加字段：`next_match_start_time`、`next_match_end_time`。
- `POST /api/admin/round/time` body 改为：
  ```json
  {
    "next_match_start_time": "2026-06-20T09:00",
    "next_match_end_time":   "2026-06-20T21:00",
    "config_required":       false,
    "maintenance":           false
  }
  ```

---

## 5. 操作日志

以下动作要写入 `operation_logs`：

- 启用 / 关闭 配置统计开关
- 清空全部配置数据
- 修改下一轮匹配时间段

---

## 6. 验收标准

### 6.1 玩家端

- [ ] 当前有进行中轮次、当前用户绑定了部落、且当前用户在该轮次未登记 → 登录进玩家页第一次自动弹出「登记提醒弹窗」。
- [ ] 弹窗里点「匹配成功」→ 弹窗关闭，匹配成功卡片显示，未匹配成功卡片隐藏。
- [ ] 弹窗里点「未匹配成功」→ 弹窗关闭，未匹配成功卡片显示，匹配成功卡片隐藏。
- [ ] 弹窗里点「稍后再说」或外部关闭 → 两个卡片都不显示。
- [ ] 同一会话内不再重复弹出。
- [ ] 已登记的玩家不再弹出。
- [ ] 匹配成功卡片底部点切换链接 → 切换为未匹配成功卡片。
- [ ] 反向切换同样可用。

### 6.2 配置统计

- [ ] 管理员开启全局开关后，玩家端出现「配置统计」录入卡片。
- [ ] 关闭后玩家端入口消失，但管理员后台仍可看到旧数据。
- [ ] 录入界面：1 栏起，可加可删；等级 0–100 下拉；人数 0–40 下拉；目标 40/50 二选一。
- [ ] 同部落同等级重复 → 提示并禁用保存。
- [ ] 合计 ≠ 目标 → 提示并禁用保存。
- [ ] 保存后再次进入显示上次保存的数据。
- [ ] 管理员后台总览按等级聚合显示已填部落数、总人数、平均人数（保留 2 位小数）。
- [ ] 管理员后台部落明细包含所有已填部落 + 未填清单。
- [ ] 「清空全部配置数据」点击后弹确认框，确认后清空，记录操作日志。

### 6.3 时间设置

- [ ] 管理员设置面板只剩「下一轮匹配开始 + 下一轮匹配结束」两个时间输入。
- [ ] 玩家端只显示「下一轮匹配时间」一行（开始 ~ 结束）。
- [ ] 设置时开始 ≥ 结束会报错。
- [ ] 字段可以留空，留空时玩家端显示「未公布」。

---

## 7. 不在本次范围内的事项（YAGNI）

- 配置数据的历史快照（每次提交都存一条带时间戳的记录）：本次只保留每个部落的「最新一份」。
- 管理员代填部落配置：本次只允许部落绑定成员自己填。
- 配置统计跟轮次绑定 / 自动归档：本次是全局开关。
- 「未公布的下一轮时间」推送通知：本次仅显示，不主动推送。

---

## 8. 实现拆分（后续 implementation plan 会按此展开）

1. **数据库迁移**：新增 `clan_configs`、`clan_config_items`、`system_settings`，给 `rounds` 加两个新字段。
2. **后端**：
   - 设置开关接口
   - 玩家端配置 CRUD
   - 管理员端聚合 / 明细 / 清空接口
   - 修改 `round/time` 接口字段
3. **前端 - 玩家端**：
   - 登记提醒弹窗
   - 拆分「匹配成功」「未匹配成功」为独立卡片，加切换链接
   - 配置统计录入卡片（受全局开关控制）
   - 轮次时间卡片改为「下一轮匹配时间」单行
4. **前端 - 管理员端**：
   - 轮次时间设置卡片字段调整 + 新增配置统计开关
   - 新增「📊 配置统计」标签页（总览 / 明细 / 未填 / 清空）
5. **联调与回归**：覆盖 §6 验收清单。
