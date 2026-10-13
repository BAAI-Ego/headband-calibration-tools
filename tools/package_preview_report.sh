#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$ROOT/preview/output" <<'INNER'
from pathlib import Path
from datetime import datetime, timezone
import sys, tarfile, hashlib
root=Path(sys.argv[1])
reports=list(root.rglob('relay_preview_report.json'))
if not reports:
    raise SystemExit('未找到报告JSON，请先确认预览已保存报告。')
latest=max(reports,key=lambda p:p.stat().st_mtime)
out=root/('report_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.tar.gz')
with tarfile.open(out,'x:gz') as t:
    t.add(latest.parent,arcname=latest.parent.name)
digest=hashlib.sha256(out.read_bytes()).hexdigest()
out.with_suffix(out.suffix+'.sha256').write_text(digest+'  '+out.name+'\n')
print(out)
print(digest)
INNER
