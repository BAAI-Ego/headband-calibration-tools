#!/usr/bin/env python3
"""Read-only native Kalibr evidence scan for a four-camera rosbag.

The selected frame indices come directly from Kalibr's BagImageDatasetReader,
including its --bag-freq timestamp rule. This script never writes the bag or
target YAML. By default it writes CSV rows only for complete 144/144
candidates. The optional detected-observation CSV is for offline overlap
analysis; it has no image pixels and never changes input data.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


EXPECTED_CORNERS = 144


def parse_camera(value):
    try:
        name, topic = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("camera must be NAME=/topic") from exc
    if not name or not topic.startswith("/"):
        raise argparse.ArgumentTypeError("camera must be NAME=/topic")
    return name.upper(), topic


def pixel_xy(point):
    try:
        return float(point[0]), float(point[1])
    except Exception:
        pass
    try:
        return float(point.x()), float(point.y())
    except Exception:
        return None


def metrics(pixels, width, height):
    if not pixels or width <= 0 or height <= 0:
        return None
    xs, ys = zip(*pixels)
    x0, x1 = max(0.0, min(xs)), min(float(width), max(xs))
    y0, y1 = max(0.0, min(ys)), min(float(height), max(ys))
    cx, cy = (x0 + x1) / (2.0 * width), (y0 + y1) / (2.0 * height)
    area = max(0.0, (x1 - x0) * (y1 - y0) / (width * height))
    return {
        "bbox_area_ratio": round(area, 6),
        "center_normalized": [round(cx, 6), round(cy, 6)],
        "image_plane_cell_3x3": [min(2, max(0, int(cy * 3))), min(2, max(0, int(cx * 3)))],
    }


def utc_string(seconds):
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def scan_camera(name, topic, args, deps, complete_csv_writer, detected_csv_writer):
    acv, acvb, kcc, kc = deps
    reader = kc.BagImageDatasetReader(args.bag, topic, bag_freq=args.bag_freq)
    geometry = kcc.CameraGeometry(acvb.EquidistantPinhole,
                                  kc.CalibrationTargetParameters(args.target),
                                  dataset=None, verbose=False)
    result = {
        "camera": name,
        "topic": topic,
        "native_topic_frames": int(len(reader.index)),
        "kalibr_bag_freq_hz": args.bag_freq,
        "selected_frames": int(reader.numImages()),
        "detected_target_frames": 0,
        "detected_observation_rows": 0,
        "complete_144_frames": 0,
        "partial_target_frames": 0,
        "detector_errors": 0,
        "best_corners": 0,
        "complete_bbox_area_ratio": {"min": None, "max": None, "p10": None, "p50": None, "p90": None},
        "complete_cells_3x3": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
        "first_selected_utc": None,
        "last_selected_utc": None,
    }
    complete_areas = []

    try:
        for selected_ordinal, idx in enumerate(reader.indices):
            ros_topic, msg, _ = reader.bag._read_message(reader.index[idx].position)
            stamp = float(msg.header.stamp.secs) + float(msg.header.stamp.nsecs) / 1.0e9
            if result["first_selected_utc"] is None:
                result["first_selected_utc"] = utc_string(stamp)
            result["last_selected_utc"] = utc_string(stamp)
            image = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None:
                result["detector_errors"] += 1
                continue
            found, pixels = 0, []
            try:
                ok, observation = geometry.ctarget.detector.findTargetNoTransformation(
                    acv.Time(int(msg.header.stamp.secs), int(msg.header.stamp.nsecs)),
                    np.ascontiguousarray(image))
                if ok == 1:
                    result["detected_target_frames"] += 1
                    grid = observation.target()
                    for row in range(int(grid.rows())):
                        for col in range(int(grid.cols())):
                            hit, point = observation.imageGridPoint(row, col)
                            if hit:
                                found += 1
                                xy = pixel_xy(point)
                                if xy is not None:
                                    pixels.append(xy)
                    observation.clearImage()
            except Exception:
                result["detector_errors"] += 1
                continue

            result["best_corners"] = max(result["best_corners"], found)
            m = metrics(pixels, image.shape[1], image.shape[0]) if found else None
            if found and detected_csv_writer is not None:
                if m is None:
                    result["detector_errors"] += 1
                else:
                    row, col = m["image_plane_cell_3x3"]
                    detected_csv_writer.writerow([
                        name, topic, selected_ordinal, idx, f"{stamp:.9f}", utc_string(stamp),
                        found, m["bbox_area_ratio"], m["center_normalized"][0],
                        m["center_normalized"][1], row, col,
                    ])
                    result["detected_observation_rows"] += 1
            if found == EXPECTED_CORNERS:
                result["complete_144_frames"] += 1
                if m is None:
                    result["detector_errors"] += 1
                    continue
                complete_areas.append(m["bbox_area_ratio"])
                row, col = m["image_plane_cell_3x3"]
                result["complete_cells_3x3"][row][col] += 1
                complete_csv_writer.writerow([name, topic, selected_ordinal, idx, f"{stamp:.9f}", utc_string(stamp),
                                               found, m["bbox_area_ratio"], m["center_normalized"][0],
                                               m["center_normalized"][1], row, col])
            elif found:
                result["partial_target_frames"] += 1
    finally:
        reader.bag.close()

    if complete_areas:
        q = np.percentile(np.asarray(complete_areas), [0, 10, 50, 90, 100])
        result["complete_bbox_area_ratio"] = {
            "min": round(float(q[0]), 6), "p10": round(float(q[1]), 6),
            "p50": round(float(q[2]), 6), "p90": round(float(q[3]), 6),
            "max": round(float(q[4]), 6),
        }
    return result


def main():
    p = argparse.ArgumentParser(description="Read-only Kalibr-native evidence scan")
    p.add_argument("--bag", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--bag-freq", type=float, default=20.0)
    p.add_argument("--emit-detected-observations", action="store_true",
                   help="also write every selected frame with detected AprilGrid points")
    p.add_argument("--camera", action="append", type=parse_camera, required=True,
                   help="repeat as NAME=/topic")
    args = p.parse_args()
    if args.bag_freq <= 0:
        p.error("--bag-freq must be positive")
    if len(args.camera) != 4 or len({name for name, _ in args.camera}) != 4:
        p.error("exactly four unique --camera NAME=/topic values are required")
    if not Path(args.bag).is_file() or not Path(args.target).is_file():
        p.error("--bag and --target must be readable files")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "kalibr_native_evidence_summary.json"
    csv_path = output / "complete_144_candidates.csv"
    detected_path = output / "detected_aprilgrid_observations.csv"
    planned_paths = [summary_path, csv_path]
    if args.emit_detected_observations:
        planned_paths.append(detected_path)
    if any(path.exists() for path in planned_paths):
        p.error("output already contains scan files; choose a new directory")

    import aslam_cv as acv
    import aslam_cv_backend as acvb
    import kalibr_camera_calibration as kcc
    import kalibr_common as kc
    deps = (acv, acvb, kcc, kc)
    summary = {
        "schema": "kalibr-native-bag-evidence-v0.2",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bag": str(Path(args.bag).resolve()),
        "target": str(Path(args.target).resolve()),
        "selection_rule": "Direct BagImageDatasetReader(..., bag_freq=20.0): retain the first header timestamp, then retain each later frame only when timestamp - last_retained >= 1/frequency.",
        "caveat": "Complete 144/144 evidence and optional detected-observation rows are descriptive only; neither predicts a Kalibr pass. The scan never changes the bag, YAML, headband, or official calibration command.",
        "detected_observation_csv_emitted": bool(args.emit_detected_observations),
        "cameras": [],
    }
    header = ["camera", "topic", "selected_ordinal", "kalibr_index", "header_stamp_seconds", "header_stamp_utc", "corners", "bbox_area_ratio", "center_x_normalized", "center_y_normalized", "cell_row", "cell_col"]
    with csv_path.open("w", newline="", encoding="utf-8") as complete_file:
        complete_writer = csv.writer(complete_file)
        complete_writer.writerow(header)
        detected_file = detected_path.open("w", newline="", encoding="utf-8") if args.emit_detected_observations else None
        try:
            detected_writer = csv.writer(detected_file) if detected_file is not None else None
            if detected_writer is not None:
                detected_writer.writerow(header)
            for name, topic in args.camera:
                print(f"Scanning {name}: {topic}", flush=True)
                result = scan_camera(name, topic, args, deps, complete_writer, detected_writer)
                summary["cameras"].append(result)
                print(f"{name}: selected={result['selected_frames']} detected_rows={result['detected_observation_rows']} complete_144={result['complete_144_frames']} best={result['best_corners']} errors={result['detector_errors']}", flush=True)
        finally:
            if detected_file is not None:
                detected_file.close()
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Summary: {summary_path}")
    print(f"Complete candidates: {csv_path}")
    if args.emit_detected_observations:
        print(f"Detected observations: {detected_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted; the input bag was not modified.", file=sys.stderr)
        raise SystemExit(130)
