#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-/home/ritvik-sojen/miniconda3/envs/dsl-testing/bin/python3}"
WEIGHTS="${WEIGHTS:-/home/ritvik-sojen/code/RF-Detr-testing/checkpoint_best_total.pth}"
TEST_VIDEO="${TEST_VIDEO:-aerial_sheep.mp4}"
API_PORT="${API_PORT:-8000}"
SOURCE_PORT="${SOURCE_PORT:-8556}"
MACHINE_IP="${MACHINE_IP:-$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')}"
MACHINE_IP="${MACHINE_IP:-$(hostname -I | awk '{print $1}')}"

LOG_DIR="/tmp/sheep-counter-logs"
PID_FILE="$SCRIPT_DIR/.pids"

mkdir -p "$LOG_DIR"

# ── helpers ──────────────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }

wait_for_port() {
    local name="$1" port="$2" timeout="${3:-15}"
    log "Waiting for $name on port $port..."
    for _ in $(seq 1 "$timeout"); do
        if nc -z localhost "$port" 2>/dev/null; then
            log "$name is up."
            return 0
        fi
        sleep 1
    done
    log "ERROR: $name did not open port $port within ${timeout}s."
    stop_all
    exit 1
}

wait_for_stream() {
    local name="$1" path="$2" timeout="${3:-20}"
    log "Waiting for $name stream on MediaMTX path '$path'..."
    for _ in $(seq 1 "$timeout"); do
        if curl -sf "http://localhost:9997/v3/paths/list" 2>/dev/null | grep -q "\"$path\""; then
            log "$name stream is up."
            return 0
        fi
        sleep 1
    done
    log "ERROR: $name stream did not appear within ${timeout}s."
    stop_all
    exit 1
}

stop_all() {
    if [[ -f "$PID_FILE" ]]; then
        log "Stopping all components..."
        while IFS='=' read -r name pid; do
            if kill "$pid" 2>/dev/null; then
                log "  stopped $name (pid $pid)"
            fi
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi
}

already_running() {
    if [[ -f "$PID_FILE" ]]; then
        echo "Components appear to be running (found $PID_FILE)."
        echo "Run ./stop.sh first, or delete $PID_FILE manually."
        exit 1
    fi
}

kill_stale() {
    # Kill any pipeline_app.py process that survived a previous crashed run
    # and is not tracked by the current .pids file.
    local stale
    stale=$(pgrep -f "pipeline_app.py" 2>/dev/null || true)
    if [[ -n "$stale" ]]; then
        log "Killing stale pipeline process(es): $stale"
        kill -9 $stale 2>/dev/null || true
    fi
}

# ── main ─────────────────────────────────────────────────────────────────────

already_running
kill_stale
trap stop_all EXIT INT TERM

log "Starting Sheep Counter system..."
> "$PID_FILE"

# 1. MediaMTX — must be first so the pipeline can publish via WHIP and
#    GStreamer can push the source stream via RTMP.
log "Starting MediaMTX..."
./mediamtx mediamtx.yml > >(tee "$LOG_DIR/mediamtx.log") 2>&1 &
echo "mediamtx=$!" >> "$PID_FILE"
wait_for_port "MediaMTX" 8889 15

# 2. RTSP source — serve the video file directly via GstRtspServer on SOURCE_PORT.
log "Starting RTSP source ($TEST_VIDEO → rtsp://localhost:$SOURCE_PORT/stream)..."
"$PYTHON" serve_rtsp_gpu.py --video "$(realpath "$TEST_VIDEO")" --port "$SOURCE_PORT" \
    > >(tee "$LOG_DIR/rtsp.log") 2>&1 &
echo "rtsp=$!" >> "$PID_FILE"
wait_for_port "RTSP source" "$SOURCE_PORT" 20

# 3. API server
log "Starting API server..."
MEDIAMTX_HOST="$MACHINE_IP" "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port "$API_PORT" > >(tee "$LOG_DIR/api.log") 2>&1 &
echo "api=$!" >> "$PID_FILE"
wait_for_port "API" "$API_PORT" 15

# 4. Frontend
log "Starting frontend..."
(cd sheep-counter-frontend && npm run dev) > >(tee "$LOG_DIR/frontend.log") 2>&1 &
echo "frontend=$!" >> "$PID_FILE"
wait_for_port "Frontend" 5173 30

# 5. Pipeline — last, depends on GStreamer source and MediaMTX being up.
#    Reads from rtsp://localhost:8554/source, publishes annotated stream via WHIP.
log "Starting pipeline (weights: $WEIGHTS)..."
"$PYTHON" bin/pipeline_app.py --weights "$WEIGHTS" > >(tee "$LOG_DIR/pipeline.log") 2>&1 &
echo "pipeline=$!" >> "$PID_FILE"

log ""
log "All components started. Logs in $LOG_DIR/"
log "  mediamtx  → $LOG_DIR/mediamtx.log"
log "  rtsp      → $LOG_DIR/rtsp.log"
log "  api       → $LOG_DIR/api.log"
log "  frontend  → $LOG_DIR/frontend.log"
log "  pipeline  → $LOG_DIR/pipeline.log"
log ""
log "Frontend:  http://$(hostname -I | awk '{print $1}'):5173"
log "API:       http://$(hostname -I | awk '{print $1}'):$API_PORT"
log ""
log "Press Ctrl+C to stop everything."

# Keep script alive; EXIT trap handles cleanup on Ctrl+C
wait
