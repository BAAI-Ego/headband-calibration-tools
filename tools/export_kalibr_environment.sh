#!/usr/bin/env bash
set -euo pipefail
IMAGE="${1:-kalibr:noetic}"
DEST="${2:-./kalibr-environment-$(date -u +%Y%m%dT%H%M%SZ)}"
if [[ "$IMAGE" != "kalibr:noetic" ]]; then
  echo "本发布入口只导出预览实际使用的kalibr:noetic镜像。"; exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$ROOT/tools/check_preview_environment.sh"
mkdir -- "$DEST"
docker image inspect "$IMAGE" --format '{{.Id}} {{.Os}}/{{.Architecture}}' > "$DEST/image-id-platform.txt"
echo "开始导出到：$DEST"
docker save "$IMAGE" | gzip > "$DEST/kalibr-environment.tar.gz"
gzip -t "$DEST/kalibr-environment.tar.gz"
(cd "$DEST" && sha256sum kalibr-environment.tar.gz > SHA256SUMS && sha256sum -c SHA256SUMS)
echo "导出完成：$DEST"
ls -lh "$DEST"
