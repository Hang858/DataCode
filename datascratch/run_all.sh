#!/bin/bash
# ============================================================
# 运行脚本：telegram / darknet 数据抓取
#
# 用法：
#   ./run_all.sh              # 先跑历史回溯，再跑增量（推荐）
#   ./run_all.sh old          # 只跑历史回溯（telegram_old + darknet_old）
#   ./run_all.sh inc          # 只跑增量（telegram + darknet）
#   ./run_all.sh telegram     # 只跑 telegram 相关
#   ./run_all.sh darknet      # 只跑 darknet 相关
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 日志目录
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Python 解释器
PYTHON="${PYTHON:-python3}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

run_bg() {
    local name="$1"
    local script="$2"
    local logfile="$LOG_DIR/${name}.log"
    log "启动 $name → 日志: $logfile"
    nohup "$PYTHON" "$SCRIPT_DIR/$script" >> "$logfile" 2>&1 &
    echo $! >> "$LOG_DIR/pids.txt"
    log "  PID: $!"
}

run_fg() {
    local name="$1"
    local script="$2"
    local logfile="$LOG_DIR/${name}.log"
    log "前台运行 $name → 日志: $logfile"
    "$PYTHON" "$SCRIPT_DIR/$script" 2>&1 | tee -a "$logfile"
}

stop_all() {
    if [ -f "$LOG_DIR/pids.txt" ]; then
        log "停止所有后台进程..."
        while read -r pid; do
            kill "$pid" 2>/dev/null && log "  已停止 PID: $pid"
        done < "$LOG_DIR/pids.txt"
        rm -f "$LOG_DIR/pids.txt"
    fi
}

# 捕获 Ctrl+C，清理后台进程
trap 'stop_all; exit 0' INT TERM

case "${1:-all}" in
    old)
        log "=== 历史数据回溯（多线程） ==="
        log "启动 telegram_old (16线程, 2022-11 ~ 2025-04)"
        run_bg "telegram_old" "telegram_old.py"
        log "启动 darknet_old (8线程, 全量历史)"
        run_bg "darknet_old" "darknet_old.py"
        log "两个历史回溯任务已在后台运行"
        log "查看进度: tail -f $LOG_DIR/telegram_old.log $LOG_DIR/darknet_old.log"
        wait
        ;;

    inc)
        log "=== 增量持续抓取 ==="
        log "启动 telegram (增量循环)"
        run_bg "telegram" "telegram.py"
        log "启动 darknet (增量循环)"
        run_bg "darknet" "darknet.py"
        log "两个增量任务已在后台运行"
        log "查看进度: tail -f $LOG_DIR/telegram.log $LOG_DIR/darknet.log"
        wait
        ;;

    telegram)
        log "=== 仅 Telegram ==="
        log "启动 telegram_old (历史回溯)"
        run_bg "telegram_old" "telegram_old.py"
        log "启动 telegram (增量循环)"
        run_bg "telegram" "telegram.py"
        wait
        ;;

    darknet)
        log "=== 仅 Darknet ==="
        log "启动 darknet_old (历史回溯)"
        run_bg "darknet_old" "darknet_old.py"
        log "启动 darknet (增量循环)"
        run_bg "darknet" "darknet.py"
        wait
        ;;

    all)
        log "=== 第一步：历史数据回溯 ==="
        log ""
        run_fg "telegram_old" "telegram_old.py"
        run_fg "darknet_old" "darknet_old.py"

        log ""
        log "=== 历史回溯完成，开始增量持续抓取 ==="
        log ""
        run_bg "telegram" "telegram.py"
        run_bg "darknet" "darknet.py"
        log "增量任务已在后台运行"
        log "查看日志: tail -f $LOG_DIR/telegram.log $LOG_DIR/darknet.log"
        wait
        ;;

    stop)
        stop_all
        ;;

    status)
        if [ -f "$LOG_DIR/pids.txt" ] && [ -s "$LOG_DIR/pids.txt" ]; then
            log "运行中的进程:"
            while read -r pid; do
                if kill -0 "$pid" 2>/dev/null; then
                    ps -p "$pid" -o pid,cmd --no-headers 2>/dev/null
                else
                    log "  PID $pid 已退出"
                fi
            done < "$LOG_DIR/pids.txt"
        else
            log "没有运行中的进程"
        fi
        ;;

    *)
        echo "用法: $0 {all|old|inc|telegram|darknet|stop|status}"
        exit 1
        ;;
esac
