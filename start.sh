#!/usr/bin/env bash
# Chạy phần mềm quảng cáo Fanpage trên Mac/Linux
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -r requirements.txt
( sleep 2; (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8787) || (command -v open >/dev/null && open http://127.0.0.1:8787) ) >/dev/null 2>&1 &
python -m app.server
