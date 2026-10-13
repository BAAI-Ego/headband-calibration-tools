#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HEADBAND_IP="${1:?用法：$0 <头环IP> [工作站IP] [safe|balanced|fluid] [60-900秒]}"; WORKSTATION_IP="${2:-192.168.10.10}"; PROFILE="${3:-safe}"; RUN_SECONDS="${4:-0}"
if ! [[ "$RUN_SECONDS" =~ ^[0-9]+$ ]] || { (( RUN_SECONDS != 0 )) && (( RUN_SECONDS < 60 || RUN_SECONDS > 900 )); }; then
  echo "运行时长省略或填 0 表示人工按 Ctrl+C 结束；如需自动结束可填 60–900 的整数秒。"; exit 2
fi
case "$PROFILE" in
  safe) WIDTH=480; FPS=3; QUALITY=60 ;;
  balanced) WIDTH=640; FPS=5; QUALITY=70 ;;
  fluid) WIDTH=640; FPS=8; QUALITY=65 ;;
  *) echo "未知档位：$PROFILE（可用 safe、balanced、fluid）"; exit 2 ;;
esac
mkdir -p "$ROOT/output"
echo "临时四路预览中继：远端代码只经 SSH 内存执行，不写头环文件/参数/BAG/YAML。"
if (( RUN_SECONDS == 0 )); then
  SESSION_TEXT="手动结束（在本终端按 Ctrl+C）"
else
  SESSION_TEXT="${RUN_SECONDS} 秒后自动结束"
fi
echo "临时档位：$PROFILE（4 路 × ${WIDTH} 宽 × ${FPS} FPS，JPEG quality ${QUALITY}，${SESSION_TEXT}）。页面：http://127.0.0.1:8766"
echo "UI 仅提示：蓝=当前动作，黄=证据不足/不确定，红=真实预览流异常；不构成 Kalibr 通过判定。"
echo "视频流使用 8766，状态与摆放指引使用独立本机端口，避免旧页面占用视频连接影响提示。"
SOCKET="/tmp/headband-preview-relay-$$.sock"
TOKEN="headband_preview_relay_$(date +%s)_$$"
echo "先验证一次 SSH（请输入头环密码）；验证成功后才启动临时中继。"
ssh -M -S "$SOCKET" -o ControlPersist=no -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -fN "orangepi@${HEADBAND_IP}"
RELAY_PID=""
cleanup() {
  [[ -n "$RELAY_PID" ]] && kill "$RELAY_PID" 2>/dev/null || true
  [[ -n "$RELAY_PID" ]] && wait "$RELAY_PID" 2>/dev/null || true
  ssh -S "$SOCKET" -o BatchMode=yes "orangepi@${HEADBAND_IP}" \
    "pids=\$(pgrep -f '^${TOKEN}( |$)' || true); [ -z \"\$pids\" ] || kill \$pids" >/dev/null 2>&1 || true
  ssh -S "$SOCKET" -O exit "orangepi@${HEADBAND_IP}" >/dev/null 2>&1 || true
  unlink "$SOCKET" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
ssh -S "$SOCKET" -o BatchMode=yes -o ServerAliveInterval=5 -o ServerAliveCountMax=2 "orangepi@${HEADBAND_IP}" \
  "source /opt/ros/noetic/setup.bash; export ROS_MASTER_URI=http://localhost:11311 ROS_IP=${HEADBAND_IP}; exec -a ${TOKEN} python3 - --width ${WIDTH} --fps ${FPS} --quality ${QUALITY} --max-seconds ${RUN_SECONDS}" \
  < "$ROOT/scripts/headband_relay.py" &
RELAY_PID=$!
docker run --rm -it --network=host --read-only --tmpfs /tmp:rw,nosuid,nodev,size=512m,mode=1777 \
  -e ROS_MASTER_URI="http://${HEADBAND_IP}:11311" -e ROS_IP="$WORKSTATION_IP" -e ROS_HOME=/tmp/ros -e ROS_LOG_DIR=/tmp/roslog \
  -v "$ROOT:/tool:ro" -v "$ROOT/output:/output:rw" --entrypoint /bin/bash kalibr:noetic -lc \
  "source /opt/ros/noetic/setup.bash; source /catkin_ws/devel/setup.bash; mkdir -p \"\$ROS_HOME\" \"\$ROS_LOG_DIR\"; exec python3 /tool/scripts/linux_viewer.py --web /tool/web/index.html --target /tool/config/april_6x6.yaml --output /output --port 8766 --session-seconds ${RUN_SECONDS}"
LATEST="$(find "$ROOT/output" -name relay_preview_report.json -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
if [[ -n "$LATEST" ]]; then ARCHIVE="${LATEST%/*}.tar.gz"; tar -czf "$ARCHIVE" -C "${LATEST%/*}" "$(basename "$LATEST")"; sha256sum "$ARCHIVE"; echo "报告包：$ARCHIVE"; fi
