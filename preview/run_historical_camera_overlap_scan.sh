#!/usr/bin/env bash
# Read-only batch scan for the five known historical camera-only bags.
# Usage:
#   ./run_historical_camera_overlap_scan.sh [historical_kalibr_root] [run_prefix]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="${1:-/media/key/A8D0F8ACD0F8823C/头环原件(温)/kalibr}"
RUN_PREFIX="${2:-historical_camera_overlap_$(date +%Y%m%d_%H%M%S)}"
HOST_DATA="/home/key/文档/kalibr/data"
HOST_RUNS="${HOST_DATA}/validation_runs"

test -d "$SOURCE_ROOT"
test -d "$HOST_DATA"
mkdir -p "$HOST_RUNS"

# CP-0001/0004/0007 auto focal passed; CP-0005/0006 needed manual focal init.
ENTRIES=(
  "cp0001|cp-0001/camera/camera_cp0001_0907_1558.bag"
  "cp0004|cp-0004/camera/camera_cp0004_0908_1322.bag"
  "cp0005|cp-0005/camera/camera_cp0005_0910_1643.bag"
  "cp0006|cp-0006/camera/camera_cp0006_0911_1837.bag"
  "cp0007|cp-0007/camera/camera_cp0007_0904_1340.bag"
)

echo "历史目录（只读）：$SOURCE_ROOT"
echo "输出目录：$HOST_RUNS"
echo "本批前缀：$RUN_PREFIX"

for ENTRY in "${ENTRIES[@]}"; do
  LABEL="${ENTRY%%|*}"
  RELATIVE_BAG="${ENTRY#*|}"
  RUN_NAME="${RUN_PREFIX}_${LABEL}"
  OUT="/data/validation_runs/${RUN_NAME}"

  echo
  echo "===== 开始 $LABEL：$RELATIVE_BAG ====="
  if [ -e "$HOST_RUNS/$RUN_NAME" ] || [ -e "$HOST_RUNS/${RUN_NAME}.tar.gz" ]; then
    echo "输出已存在，拒绝覆盖：$RUN_NAME" >&2
    exit 2
  fi

  docker run --rm --network=none --read-only --tmpfs /tmp:rw,nosuid,nodev,size=512m \
    -e HOME=/tmp -e ROS_HOME=/tmp/ros -e ROS_LOG_DIR=/tmp/roslog \
    -v "$ROOT:/tool:ro" \
    -v "$SOURCE_ROOT:/source:ro" \
    -v "$HOST_DATA:/data:rw" \
    --entrypoint /bin/bash kalibr:noetic -lc "
set -e
source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash
mkdir -p \"\$ROS_HOME\" \"\$ROS_LOG_DIR\"
test -r '/source/$RELATIVE_BAG'
test -r /data/april_6x6.yaml
mkdir -p '$OUT'
python3 /tool/scripts/kalibr_bag_native_evidence_scan.py \\
  --bag '/source/$RELATIVE_BAG' \\
  --target /data/april_6x6.yaml \\
  --output '$OUT' \\
  --bag-freq 20.0 \\
  --emit-detected-observations \\
  --camera LEFT=/fisheye/left/image_raw/compressed \\
  --camera RIGHT=/fisheye/right/image_raw/compressed \\
  --camera BRIGHT=/fisheye/bright/image_raw/compressed \\
  --camera BLEFT=/fisheye/bleft/image_raw/compressed

tar -czf \"/data/validation_runs/${RUN_NAME}.tar.gz\" \\
  -C '$OUT' kalibr_native_evidence_summary.json complete_144_candidates.csv detected_aprilgrid_observations.csv
sha256sum \"/data/validation_runs/${RUN_NAME}.tar.gz\"
"
  echo "===== 完成 $LABEL ====="
done

BATCH_ARCHIVE="$HOST_RUNS/${RUN_PREFIX}.tar.gz"
if [ -e "$BATCH_ARCHIVE" ]; then
  echo "汇总包已存在，拒绝覆盖：$BATCH_ARCHIVE" >&2
  exit 2
fi

tar -czf "$BATCH_ARCHIVE" -C "$HOST_RUNS" \
  "${RUN_PREFIX}_cp0001" \
  "${RUN_PREFIX}_cp0001.tar.gz" \
  "${RUN_PREFIX}_cp0004" \
  "${RUN_PREFIX}_cp0004.tar.gz" \
  "${RUN_PREFIX}_cp0005" \
  "${RUN_PREFIX}_cp0005.tar.gz" \
  "${RUN_PREFIX}_cp0006" \
  "${RUN_PREFIX}_cp0006.tar.gz" \
  "${RUN_PREFIX}_cp0007" \
  "${RUN_PREFIX}_cp0007.tar.gz"

echo
echo "===== 全部扫描结束 ====="
echo "汇总分析包：$BATCH_ARCHIVE"
sha256sum "$BATCH_ARCHIVE"
