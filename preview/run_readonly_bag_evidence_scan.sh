#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BAG="${1:?用法：$0 <容器内BAG路径> [输出目录名] [complete-only|all-detected]}"
RUN_NAME="${2:-readonly_scan_$(date +%Y%m%d_%H%M%S)}"
MODE="${3:-complete-only}"
OUT="/data/validation_runs/${RUN_NAME}"

case "$MODE" in
  complete-only)
    EXTRA_SCAN_ARG=""
    ARCHIVE_FILES="kalibr_native_evidence_summary.json complete_144_candidates.csv"
    ;;
  all-detected)
    EXTRA_SCAN_ARG="--emit-detected-observations"
    ARCHIVE_FILES="kalibr_native_evidence_summary.json complete_144_candidates.csv detected_aprilgrid_observations.csv"
    ;;
  *)
    echo "第 3 个参数只能是 complete-only 或 all-detected" >&2
    exit 2
    ;;
esac

docker run --rm -it --network=none --read-only --tmpfs /tmp:rw,nosuid,nodev,size=512m \
  -e HOME=/tmp -e ROS_HOME=/tmp/ros -e ROS_LOG_DIR=/tmp/roslog \
  -v "$ROOT:/tool:ro" \
  -v "/home/key/文档/kalibr/data:/data:rw" \
  --entrypoint /bin/bash kalibr:noetic -lc "
set -e
source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash
mkdir -p \"\$ROS_HOME\" \"\$ROS_LOG_DIR\"
test -r '$BAG'
test -r /data/april_6x6.yaml
mkdir -p '$OUT'
python3 /tool/scripts/kalibr_bag_native_evidence_scan.py \\
  --bag '$BAG' \\
  --target /data/april_6x6.yaml \\
  --output '$OUT' \\
  --bag-freq 20.0 \\
  $EXTRA_SCAN_ARG \\
  --camera LEFT=/fisheye/left/image_raw/compressed \\
  --camera RIGHT=/fisheye/right/image_raw/compressed \\
  --camera BRIGHT=/fisheye/bright/image_raw/compressed \\
  --camera BLEFT=/fisheye/bleft/image_raw/compressed

tar -czf \"/data/validation_runs/${RUN_NAME}.tar.gz\" \\
  -C \"$OUT\" $ARCHIVE_FILES
sha256sum \"/data/validation_runs/${RUN_NAME}.tar.gz\"
echo \"分析包：/data/validation_runs/${RUN_NAME}.tar.gz\"
"
