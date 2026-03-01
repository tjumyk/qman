#!/usr/bin/env bash
# Start full local dev stack in a tmux session: mock OAuth, 4 slaves, master, frontend.
# Each server runs in its own pane so you can see logs and restart individual services.
# Uses example mock configs: config.master_mock_example.json, config.slave_mock_example1..4.json.
#
# Requires: tmux, conda env qman, frontend deps installed.
# In oauth.config.json set enabled: true, server.url: http://localhost:8077, client.url: http://localhost:5173
# Note: host4 uses Docker quota + Celery; quota display works without Redis.
#
# Usage:
#   ./scripts/dev.sh          # Create session and attach
#   tmux attach -t qman-dev   # Reattach after detach (Ctrl+b d)
#   tmux kill-session -t qman-dev   # Stop all servers

set -e
cd "$(dirname "$0")/.."
ROOT=$(pwd)

MASTER_CONFIG=config.master_mock_example.json
SLAVE_CONFIGS=(config.slave_mock_example1.json config.slave_mock_example2.json config.slave_mock_example3.json config.slave_mock_example4.json)

if ! command -v tmux &>/dev/null; then
  echo "Error: tmux is required. Install with: apt install tmux  # or brew install tmux"
  exit 1
fi
if [[ ! -f "$MASTER_CONFIG" ]]; then
  echo "Error: $MASTER_CONFIG not found."
  exit 1
fi
for c in "${SLAVE_CONFIGS[@]}"; do
  if [[ ! -f "$c" ]]; then
    echo "Error: slave config not found: $c"
    exit 1
  fi
done

SESSION=qman-dev
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session $SESSION already exists. Attaching (use Ctrl+b d to detach)."
  exec tmux attach -t "$SESSION"
fi

echo "Creating tmux session $SESSION..."
# Window 0: API (OAuth + Master)
tmux new-session -d -s "$SESSION" -n api -c "$ROOT"
tmux send-keys -t "$SESSION:api" "python auth_connect/mock_oauth_server.py" Enter
tmux split-window -h -t "$SESSION:api" -c "$ROOT"
tmux send-keys -t "$SESSION:api.1" "CONFIG_PATH=$MASTER_CONFIG python run.py" Enter

# Windows 1–4: One window per slave (avoids tmux pane index quirks with split)
for i in 0 1 2 3; do
  tmux new-window -t "$SESSION" -n "host$((i+1))" -c "$ROOT"
  tmux send-keys -t "$SESSION:host$((i+1))" "CONFIG_PATH=${SLAVE_CONFIGS[i]} python run.py   # host$((i+1)) :843$((7+i))" Enter
done

# Window 5: Frontend
tmux new-window -t "$SESSION" -n frontend -c "$ROOT"
tmux send-keys -t "$SESSION:frontend" "cd frontend && npm run dev" Enter

tmux select-window -t "$SESSION:api"
echo ""
echo "Dev stack started in tmux session: $SESSION"
echo "  Windows: 0=api  1=host1  2=host2  3=host3  4=host4  5=frontend"
echo "  Switch: Ctrl+b 0..5   Detach: Ctrl+b d   Stop all: tmux kill-session -t $SESSION"
echo "  App: http://localhost:5173   Log in as alice or charlie"
echo ""
exec tmux attach -t "$SESSION"
