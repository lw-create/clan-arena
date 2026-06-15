#!/bin/bash
# CloudStudio 启动脚本
cd "$(dirname "$0")"

# 安装依赖
pip install -q fastapi==0.104.1 uvicorn==0.24.0 bcrypt==4.1.2 PyJWT==2.8.0 python-multipart==0.0.6 2>/dev/null

# 启动应用
echo "Starting 部落对战积分系统..."
export CLAN_ARENA_DB="clan_arena.db"
export PORT=${PORT:-3000}
python -m uvicorn main:app --host 0.0.0.0 --port $PORT
