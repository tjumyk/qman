#!/usr/bin/env bash
# Start full local dev stack: mock OAuth, slave (mock quota), master, frontend.
# Run from project root. Requires: conda env qman, frontend deps installed.
# In oauth.config.json set enabled: true, server.url: http://localhost:8077, client.url: http://localhost:5173

set -e
cd "$(dirname "$0")/.."

echo "Starting mock OAuth server (8077)..."
python auth_connect/mock_oauth_server.py &
OAUTH_PID=$!

echo "Starting slave (8437)..."
CONFIG_PATH=config.slave.json python run.py &
SLAVE_PID=$!

sleep 2
echo "Starting master (8436)..."
python run.py &
MASTER_PID=$!

sleep 2
echo "Starting frontend dev server (5173)..."
cd frontend && npm run dev &
FRONTEND_PID=$!

echo ""
echo "Dev stack started. Open http://localhost:5173"
echo "Log in as alice (My usage) or charlie (admin)."
echo "To stop: kill $OAUTH_PID $SLAVE_PID $MASTER_PID $FRONTEND_PID"
wait
