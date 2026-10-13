#!/usr/bin/env python3
"""One-shot Kalibr detector for one JPEG preview frame; no ROS subscription."""
import argparse, json, sys, time
from types import SimpleNamespace

import cv2
import numpy as np

def main():
    p = argparse.ArgumentParser(); p.add_argument('--target', required=True); p.add_argument('--camera', required=True)
    a = p.parse_args(); raw = sys.stdin.buffer.read()
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None: raise RuntimeError('JPEG decode failed')
    import aslam_cv as acv, aslam_cv_backend as acvb, kalibr_camera_calibration as kcc, kalibr_common as kc
    target = kc.CalibrationTargetParameters(a.target)
    geometry = kcc.CameraGeometry(acvb.EquidistantPinhole, target, dataset=None, verbose=False)
    now = time.time(); sec = int(now); nsec = int((now-sec)*1e9)
    ok, observation = geometry.ctarget.detector.findTargetNoTransformation(acv.Time(sec, nsec), np.ascontiguousarray(image))
    found = 0
    if ok == 1:
        grid = observation.target()
        for row in range(int(grid.rows())):
            for col in range(int(grid.cols())):
                hit, _ = observation.imageGridPoint(row, col); found += int(bool(hit))
        observation.clearImage()
    print(json.dumps({'state':'COMPLETE_GRID_OBSERVED' if found == 144 else ('PARTIAL_GRID_OBSERVED' if found else 'NOT_OBSERVED_UNCERTAIN'), 'found_corners':found, 'expected_corners':144, 'complete':found==144}))
if __name__ == '__main__':
    try: main()
    except Exception as error: print(json.dumps({'state':'NOT_OBSERVED_UNCERTAIN','found_corners':0,'expected_corners':144,'error':type(error).__name__}), flush=True)
