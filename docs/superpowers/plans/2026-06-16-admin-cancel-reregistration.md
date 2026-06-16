# 管理员撤销后重新登记 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理员撤销本轮对战后，成员端解除登记状态、隐藏输赢结果、显示“管理员已撤销您的登记，请重新登记”，并允许重新登记。

**Architecture:** 用一张轻量通知表记录管理员撤销事件；`/me` 在成员未登记且无活跃匹配时返回撤销通知；成员重新登记时清掉通知。成员端撤销入口从 UI 和后端同时关闭，管理员端撤销流程保留。

**Tech Stack:** FastAPI, PyMySQL/MySQL, vanilla JavaScript, unittest 静态回归测试。

---

### Task 1: 数据库与后端状态

**Files:**
- Modify: `database.py`
- Modify: `routers/admin.py`
- Modify: `routers/auth.py`
- Modify: `routers/player.py`
- Test: `tests/test_admin_cancel_reregistration_static.py`

- [ ] **Step 1: 写失败测试**

检查源码必须包含撤销通知表、管理员撤销通知写入、`/me` 返回 `cancel_notice`、成员重新登记清理通知、成员撤销接口拒绝。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests/test_admin_cancel_reregistration_static.py -v`

- [ ] **Step 3: 实现后端最小改动**

新增 `round_cancel_notices` 表；管理员撤销时记录双方用户通知；`/me` 返回通知；成员重新登记时删除通知；成员撤销接口直接返回 403。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests/test_admin_cancel_reregistration_static.py -v`

### Task 2: 成员端展示

**Files:**
- Modify: `static/app.js`
- Test: `tests/test_admin_cancel_reregistration_static.py`

- [ ] **Step 1: 写失败测试**

检查成员端历史记录不再渲染撤销按钮，并存在管理员撤销提示渲染文案。

- [ ] **Step 2: 实现前端最小改动**

删除成员端撤销按钮渲染；`loadPlayerData` 遇到 `cancel_notice` 时隐藏输赢横幅，显示提示，并允许用户通过登记弹窗或卡片重新登记。

- [ ] **Step 3: 验证**

Run: `python -m unittest tests/test_admin_cancel_reregistration_static.py -v`
Run: `python -m py_compile database.py routers/admin.py routers/auth.py routers/player.py`
Run: `node --check static/app.js`
