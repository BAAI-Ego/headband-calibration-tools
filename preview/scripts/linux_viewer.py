#!/usr/bin/env python3
"""Linux-side four-preview viewer with independent, latest-frame Kalibr probes."""
import argparse
import base64
import json
import select
import signal
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import rospy
from sensor_msgs.msg import CompressedImage

TOPICS = {name: f"/calibration_preview/{name.lower()}/image_raw/compressed"
          for name in ("LEFT", "RIGHT", "BRIGHT", "BLEFT")}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Viewer:
    def __init__(self, output, target, session_seconds):
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.stream_stale_seconds = 3.0
        self.stream_missing_seconds = 5.0
        self.probe_target_period_seconds = 1.0
        self.probe_timeout_seconds = 5.0
        self.session_seconds = session_seconds
        self.started_monotonic = time.monotonic()
        self.started_utc = utc_now()
        self.frames = {name: {"data": None, "sequence": 0, "received": deque(maxlen=120), "total": 0,
                              "last_received_monotonic": None, "last_received_utc": None,
                              "max_interarrival_seconds": 0.0, "gaps_over_1_second": 0}
                       for name in TOPICS}
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.target = target
        self.probe = str(Path(__file__).with_name("kalibr_probe_worker.py"))
        self.workers = {name: None for name in TOPICS}
        self.native = {name: {"state": "NOT_OBSERVED_UNCERTAIN", "found_corners": 0,
                              "expected_corners": 144, "note": "等待独立 Kalibr 探针"}
                       for name in TOPICS}
        self.history = {name: {"best_corners": 0, "complete_grid_observations": 0,
                               "probe_attempts": 0, "last_probe_utc": None,
                               "last_target_observed_utc": None}
                        for name in TOPICS}
        self.probe_stats = {name: {"completed": 0, "timeouts": 0, "errors": 0,
                                   "last_outcome": "WAITING", "last_duration_seconds": None,
                                   "last_started_utc": None, "last_completed_utc": None,
                                   "last_source_sequence": None,
                                   "last_processed_sequence": None}
                            for name in TOPICS}
        self.inspections = {name: {"jpeg": None, "captured_utc": None, "source_sequence": None}
                            for name in TOPICS}
        self.coverage = {name: {"image_plane_cells": set(), "bbox_area_ratio_min": None,
                                "bbox_area_ratio_max": None, "last_complete_metrics": None}
                         for name in TOPICS}
        self.common_history = {"episodes": 0, "last_observed_utc": None}
        self.common_active = False
        self.final_snapshot = None
        self.subs = [rospy.Subscriber(topic, CompressedImage, self.receive, callback_args=name,
                                      queue_size=1, buff_size=2 * 1024 * 1024, tcp_nodelay=True)
                     for name, topic in TOPICS.items()]

    def receive(self, message, name):
        with self.lock:
            item = self.frames[name]
            now = time.monotonic()
            previous = item["last_received_monotonic"]
            if previous is not None:
                interval = now - previous
                item["max_interarrival_seconds"] = max(item["max_interarrival_seconds"], interval)
                item["gaps_over_1_second"] += int(interval > 1.0)
            item["data"] = bytes(message.data)
            item["sequence"] += 1
            item["received"].append(now)
            item["total"] += 1
            item["last_received_monotonic"] = now
            item["last_received_utc"] = utc_now()

    @staticmethod
    def fps(values):
        if len(values) < 2 or values[-1] <= values[0]:
            return 0.0
        return round((len(values) - 1) / (values[-1] - values[0]), 2)

    def stop_worker(self, name):
        worker = self.workers[name]
        if worker is not None:
            try:
                worker.kill()
                worker.wait(timeout=1)
            except Exception:
                pass
        self.workers[name] = None

    def start_worker_if_needed(self, name):
        worker = self.workers[name]
        if worker is None or worker.poll() is not None:
            self.stop_worker(name)
            self.workers[name] = subprocess.Popen(
                ["python3", self.probe, "--target", self.target],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1)
        return self.workers[name]

    def run_probe(self, name, data, sequence):
        worker = self.start_worker_if_needed(name)
        request = json.dumps({"camera": name, "source_sequence": sequence,
                              "jpeg": base64.b64encode(data).decode("ascii")}) + "\n"
        worker.stdin.write(request)
        worker.stdin.flush()
        ready, _, _ = select.select([worker.stdout], [], [], self.probe_timeout_seconds)
        if not ready:
            self.stop_worker(name)
            raise subprocess.TimeoutExpired("kalibr_probe_worker", self.probe_timeout_seconds)
        return json.loads(worker.stdout.readline())

    def apply_detection(self, name, result, source_sequence, duration_seconds):
        now = utc_now()
        inspection_b64 = result.pop("inspection_jpeg", None)
        if inspection_b64:
            try:
                self.inspections[name] = {"jpeg": base64.b64decode(inspection_b64),
                                          "captured_utc": now,
                                          "source_sequence": result.get("source_sequence")}
            except Exception:
                pass
        metrics = result.get("image_metrics")
        if result.get("complete") and isinstance(metrics, dict):
            coverage = self.coverage[name]
            cell = metrics.get("image_plane_cell_3x3")
            if isinstance(cell, list) and len(cell) == 2:
                coverage["image_plane_cells"].add((int(cell[0]), int(cell[1])))
            area = metrics.get("bbox_area_ratio")
            if isinstance(area, (float, int)):
                area = round(float(area), 5)
                previous_min = coverage["bbox_area_ratio_min"]
                previous_max = coverage["bbox_area_ratio_max"]
                coverage["bbox_area_ratio_min"] = area if previous_min is None else min(previous_min, area)
                coverage["bbox_area_ratio_max"] = area if previous_max is None else max(previous_max, area)
            coverage["last_complete_metrics"] = metrics
        history = self.history[name]
        history["best_corners"] = max(history["best_corners"], int(result.get("found_corners", 0)))
        history["complete_grid_observations"] += int(bool(result.get("complete", False)))
        history["last_probe_utc"] = now
        if int(result.get("found_corners", 0)):
            history["last_target_observed_utc"] = now
        result["note"] = "每路独立 Kalibr 探针只处理开始时的最新低清帧；超时即仅重启该路探针，连续预览不受影响。低清未观察到＝不确定。"
        self.native[name] = result
        stat = self.probe_stats[name]
        stat["completed"] += 1
        stat["last_outcome"] = "COMPLETED" if not result.get("error") else "WORKER_ERROR"
        stat["last_duration_seconds"] = round(duration_seconds, 3)
        stat["last_completed_utc"] = now
        stat["last_source_sequence"] = source_sequence
        if result.get("error"):
            stat["errors"] += 1

    def probe_loop(self, name):
        next_due = time.monotonic()
        while not self.stop.is_set():
            delay = max(0.0, next_due - time.monotonic())
            if self.stop.wait(delay):
                break
            with self.lock:
                data = self.frames[name]["data"]
                sequence = self.frames[name]["sequence"]
                stat = self.probe_stats[name]
            started = time.monotonic()
            if not data:
                with self.lock:
                    stat["last_outcome"] = "WAITING_FOR_FRAME"
                    stat["last_source_sequence"] = sequence
                next_due = started + self.probe_target_period_seconds
                continue
            with self.lock:
                if sequence == stat["last_processed_sequence"]:
                    stat["last_outcome"] = "WAITING_FOR_NEW_FRAME"
                    stat["last_source_sequence"] = sequence
                    next_due = started + self.probe_target_period_seconds
                    continue
                stat["last_started_utc"] = utc_now()
                stat["last_source_sequence"] = sequence
                stat["last_processed_sequence"] = sequence
                self.history[name]["probe_attempts"] += 1
            try:
                result = self.run_probe(name, data, sequence)
                elapsed = time.monotonic() - started
                with self.lock:
                    self.apply_detection(name, result, sequence, elapsed)
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started
                with self.lock:
                    stat = self.probe_stats[name]
                    stat["timeouts"] += 1
                    stat["last_outcome"] = "TIMEOUT"
                    stat["last_duration_seconds"] = round(elapsed, 3)
                    stat["last_completed_utc"] = utc_now()
                    self.native[name] = {"state": "NOT_OBSERVED_UNCERTAIN", "found_corners": 0,
                                         "expected_corners": 144,
                                         "note": "该路探针超时已终止；连续预览不受影响。"}
            except Exception as error:
                self.stop_worker(name)
                elapsed = time.monotonic() - started
                with self.lock:
                    stat = self.probe_stats[name]
                    stat["errors"] += 1
                    stat["last_outcome"] = "EXCEPTION:" + type(error).__name__
                    stat["last_duration_seconds"] = round(elapsed, 3)
                    stat["last_completed_utc"] = utc_now()
                    self.native[name] = {"state": "NOT_OBSERVED_UNCERTAIN", "found_corners": 0,
                                         "expected_corners": 144,
                                         "note": "该路探针异常：{}；连续预览不受影响。".format(type(error).__name__)}
            next_due = started + self.probe_target_period_seconds

    def state(self):
        with self.lock:
            now = datetime.now(timezone.utc)
            seen = []
            for name in TOPICS:
                stamp = self.history[name]["last_target_observed_utc"]
                seen.append(bool(stamp and (now - datetime.fromisoformat(stamp)).total_seconds() <= 5.0))
            observed = all(seen)
            if observed and not self.common_active:
                self.common_history["episodes"] += 1
                self.common_history["last_observed_utc"] = now.isoformat()
            self.common_active = observed
            monotonic_now = time.monotonic()
            cameras = {}
            for name, item in self.frames.items():
                last = item["last_received_monotonic"]
                age = None if last is None else round(monotonic_now - last, 2)
                if last is None:
                    stream_state = "STREAM_MISSING" if monotonic_now - self.started_monotonic > self.stream_missing_seconds else "WAITING_FOR_STREAM"
                else:
                    stream_state = "STREAM_STALE" if age > self.stream_stale_seconds else "STREAM_LIVE"
                cameras[name] = {
                    "preview_fps_window": self.fps(item["received"]), "received_frames": item["total"],
                    "has_frame": item["data"] is not None, "frame_age_seconds": age,
                    "stream_state": stream_state, "stream_stale_seconds": self.stream_stale_seconds,
                    "stream_missing_seconds": self.stream_missing_seconds,
                    "stream_delivery_summary": {"last_received_utc": item["last_received_utc"],
                        "max_interarrival_seconds": round(item["max_interarrival_seconds"], 3),
                        "gaps_over_1_second": item["gaps_over_1_second"],
                        "caveat": "这是 Linux 收到低清预览帧的传输记录；不能代表原始录制话题的每一帧。"},
                    "native_preview_observation": self.native[name],
                    "native_preview_history": self.history[name],
                    "native_probe_runtime": self.probe_stats[name],
                    "native_inspection": {"available": self.inspections[name]["jpeg"] is not None,
                        "captured_utc": self.inspections[name]["captured_utc"],
                        "source_sequence": self.inspections[name]["source_sequence"],
                        "caveat": "这是独立 Kalibr 探针处理的采样帧，不覆盖或冒充当前连续预览帧。"},
                    "native_complete_coverage": {"only_complete_grid_samples": True,
                        "image_plane_grid": [3, 3],
                        "observed_cells": [list(cell) for cell in sorted(self.coverage[name]["image_plane_cells"])],
                        "bbox_area_ratio_min": self.coverage[name]["bbox_area_ratio_min"],
                        "bbox_area_ratio_max": self.coverage[name]["bbox_area_ratio_max"],
                        "last_complete_metrics": self.coverage[name]["last_complete_metrics"],
                        "caveat": "仅描述已记录的完整网格画面位置和相对占画面面积；没有数量门槛或通过结论。"}}
            elapsed = monotonic_now - self.started_monotonic
            return {"cameras": cameras,
                    "probe_scheduler": {"mode": "FOUR_INDEPENDENT_LATEST_FRAME", "focus_camera": None,
                        "parallel_cameras": list(TOPICS), "target_period_seconds": self.probe_target_period_seconds,
                        "timeout_seconds": self.probe_timeout_seconds,
                        "caveat": "四路独立探针并行，只取每路开始时的最新低清帧；旧帧不排队。目标频率不等于保证频率，实际完成数、耗时、超时和异常均记录在报告。"},
                    "session": {"configured_seconds": self.session_seconds,
                        "elapsed_seconds": round(elapsed, 1),
                        "remaining_seconds": None if self.session_seconds <= 0 else max(0, round(self.session_seconds - elapsed, 1))},
                    "near_time_four_view": {"observed": observed, "window_seconds": 5,
                        "history": self.common_history,
                        "caveat": "低清探针的近时共同可见，不是严格时间同步或完整网格证据。"}}

    def save(self, reason="process_shutdown"):
        path = self.output / "relay_preview_report.json"
        with self.lock:
            if self.final_snapshot is None:
                self.final_snapshot = {"captured_utc": utc_now(), "capture_reason": reason, "state": self.state()}
            snapshot = self.final_snapshot
        path.write_text(json.dumps({"schema": "temporary-four-preview-relay-v1.10",
            "created_utc": utc_now(), "session_started_utc": self.started_utc,
            "final_snapshot": snapshot,
            "scope": "Temporary Linux viewer of a headband relay; no Kalibr acceptance claim."},
            ensure_ascii=False, indent=2), encoding="utf-8")
        return path


class Handler(BaseHTTPRequestHandler):
    viewer = None
    html = b""

    def log_message(self, *_):
        pass

    def do_GET(self):
        target = urlparse(self.path)
        if target.path == "/":
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers(); self.wfile.write(self.html); return
        if target.path == "/api/state":
            try:
                body = json.dumps(self.viewer.state(), ensure_ascii=False).encode()
                self.send_response(200)
            except Exception as error:
                body = json.dumps({"error": "state_failed", "detail": type(error).__name__}).encode()
                self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body); return
        if target.path == "/api/finish":
            body = json.dumps({"report": str(self.viewer.save("user_finish_button"))}).encode()
            self.viewer.stop.set(); self.send_response(200); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(body); return
        if target.path.startswith("/inspection/"):
            name = target.path.rsplit("/", 1)[-1]
            if name not in TOPICS:
                self.send_error(404); return
            with self.viewer.lock:
                data = self.viewer.inspections[name]["jpeg"]
            if data is None:
                self.send_error(404); return
            self.send_response(200); self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data); return
        if target.path.startswith("/stream/"):
            name = target.path.rsplit("/", 1)[-1]
            if name not in TOPICS:
                self.send_error(404); return
            self.send_response(200); self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers(); previous = -1
            try:
                while not self.viewer.stop.is_set():
                    with self.viewer.lock:
                        item = self.viewer.frames[name]
                        data, sequence = item["data"], item["sequence"]
                    if data is not None and sequence != previous:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                        self.wfile.flush(); previous = sequence
                    time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.send_error(404)


class StateHandler(BaseHTTPRequestHandler):
    """Keeps short state requests separate from four long-lived MJPEG streams."""
    viewer = None

    def log_message(self, *_):
        pass

    def json_response(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        target = urlparse(self.path)
        if target.path == "/api/state":
            try:
                self.json_response(200, self.viewer.state())
            except Exception as error:
                self.json_response(500, {"error": "state_failed", "detail": type(error).__name__})
            return
        if target.path == "/api/finish":
            self.json_response(200, {"report": str(self.viewer.save("user_finish_button"))})
            self.viewer.stop.set()
            return
        self.send_error(404)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--target", required=True); parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--session-seconds", type=int, default=0,
                        help="0 means run until interrupted")
    args = parser.parse_args()
    rospy.init_node("temporary_four_preview_viewer", anonymous=True, disable_signals=True)
    viewer = Viewer(args.output, args.target, args.session_seconds)
    Handler.viewer = viewer; Handler.html = Path(args.web).read_bytes(); StateHandler.viewer = viewer
    for name in TOPICS:
        threading.Thread(target=viewer.probe_loop, args=(name,), daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.daemon_threads = True; server.block_on_close = False
    api_server = ThreadingHTTPServer(("127.0.0.1", args.port + 1), StateHandler)
    api_server.daemon_threads = True; api_server.block_on_close = False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=api_server.serve_forever, daemon=True).start()
    def stop(*_):
        viewer.stop.set()
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    while not viewer.stop.wait(0.2):
        if viewer.session_seconds > 0 and time.monotonic() - viewer.started_monotonic >= viewer.session_seconds:
            viewer.save("relay_time_limit_reached")
            viewer.stop.set()
    for name in TOPICS:
        viewer.stop_worker(name)
    viewer.save(); rospy.signal_shutdown("viewer finished"); server.shutdown(); api_server.shutdown()
    print("report:", viewer.output / "relay_preview_report.json")


if __name__ == "__main__":
    main()
