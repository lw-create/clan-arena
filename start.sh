#!/bin/bash
cd "$(dirname "$0")"
export CLAN_ARENA_DB="clan_arena.db"
exec python -m uvicorn main:app --host 0.0.0.0 --port $PORT
