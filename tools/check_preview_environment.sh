#!/usr/bin/env bash
set -euo pipefail
for cmd in docker ssh tar sha256sum python3; do
  command -v "$cmd" >/dev/null || { echo "缺少命令：$cmd"; exit 1; }
done
docker image inspect kalibr:noetic --format '{{.Id}} {{.Os}}/{{.Architecture}}'
docker run --rm -i --network=none --entrypoint /bin/bash kalibr:noetic -lc '
set -e
source /opt/ros/noetic/setup.bash
source /catkin_ws/devel/setup.bash
export MPLBACKEND=Agg
unset DISPLAY
exec python3 -
' <<'PYCODE'
import rospy, rosbag, cv2, numpy
import aslam_cv, aslam_cv_backend, kalibr_common, kalibr_camera_calibration
from sensor_msgs.msg import CompressedImage
print("DEPENDENCIES_PASS")
print("OpenCV:", cv2.__version__)
print("NumPy:", numpy.__version__)
PYCODE
echo "本地依赖检查通过；未检查头环或网络。"
