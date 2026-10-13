#!/usr/bin/env python3
"""Persistent stdin/stdout Kalibr detector worker; owns no ROS subscriptions."""
import argparse, base64, json, sys, time
import cv2, numpy as np


def pixel_xy(point):
    """Best-effort extraction from the Kalibr Python binding; never affects detection."""
    try:
        return [round(float(point[0]), 2), round(float(point[1]), 2)]
    except Exception:
        pass
    try:
        return [round(float(point.x()), 2), round(float(point.y()), 2)]
    except Exception:
        return None


def image_metrics(pixels, width, height):
    """Descriptive image-plane measurements, never a Kalibr acceptance criterion."""
    if not pixels or width <= 0 or height <= 0:
        return None
    xs, ys = [p[0] for p in pixels], [p[1] for p in pixels]
    x0, x1 = max(0.0, min(xs)), min(float(width), max(xs))
    y0, y1 = max(0.0, min(ys)), min(float(height), max(ys))
    cx, cy = (x0 + x1) / (2.0 * width), (y0 + y1) / (2.0 * height)
    return {"image_width": int(width), "image_height": int(height),
            "bbox_normalized": [round(x0/width,4), round(y0/height,4), round(x1/width,4), round(y1/height,4)],
            "center_normalized": [round(cx,4), round(cy,4)],
            "bbox_area_ratio": round(max(0.0, (x1-x0)*(y1-y0)/(width*height)), 5),
            "image_plane_cell_3x3": [min(2, max(0, int(cy*3))), min(2, max(0, int(cx*3)))]}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--target',required=True); a=p.parse_args()
    import aslam_cv as acv, aslam_cv_backend as acvb, kalibr_camera_calibration as kcc, kalibr_common as kc
    target=kc.CalibrationTargetParameters(a.target)
    cams={}
    for line in sys.stdin:
        try:
            req=json.loads(line); name=req['camera']; source_sequence=req.get('source_sequence')
            if name not in cams: cams[name]=kcc.CameraGeometry(acvb.EquidistantPinhole,target,dataset=None,verbose=False)
            encoded=base64.b64decode(req['jpeg'])
            image=cv2.imdecode(np.frombuffer(encoded,np.uint8),cv2.IMREAD_GRAYSCALE)
            if image is None: raise RuntimeError('JPEG decode failed')
            now=time.time(); sec=int(now); nsec=int((now-sec)*1e9)
            ok,obs=cams[name].ctarget.detector.findTargetNoTransformation(acv.Time(sec,nsec),np.ascontiguousarray(image)); found=0; cells=[]; pixels=[]; grid_rows=0; grid_cols=0
            if ok==1:
                grid=obs.target()
                grid_rows=int(grid.rows()); grid_cols=int(grid.cols())
                for row in range(grid_rows):
                    for col in range(grid_cols):
                        hit,point=obs.imageGridPoint(row,col)
                        if hit:
                            found+=1; cells.append([row,col])
                            xy=pixel_xy(point)
                            if xy is not None: pixels.append(xy)
                obs.clearImage()
            # This is a sampled inspection image, not an overlay on a newer live frame.
            inspection=cv2.imdecode(np.frombuffer(encoded,np.uint8),cv2.IMREAD_COLOR)
            metrics = image_metrics(pixels, inspection.shape[1], inspection.shape[0]) if inspection is not None else None
            if inspection is not None:
                for x,y in pixels: cv2.circle(inspection,(int(round(x)),int(round(y))),3,(70,220,90),-1,cv2.LINE_AA)
                cv2.putText(inspection, f'Kalibr sample: {found}/144 corners', (12,28), cv2.FONT_HERSHEY_SIMPLEX,0.62,(70,220,90),2,cv2.LINE_AA)
                ok_jpeg, inspection_encoded=cv2.imencode('.jpg',inspection,[int(cv2.IMWRITE_JPEG_QUALITY),85])
                inspection_jpeg=base64.b64encode(inspection_encoded.tobytes()).decode('ascii') if ok_jpeg else None
            else:
                inspection_jpeg=None
            print(json.dumps({'state':'COMPLETE_GRID_OBSERVED' if found==144 else ('PARTIAL_GRID_OBSERVED' if found else 'NOT_OBSERVED_UNCERTAIN'),'found_corners':found,'expected_corners':144,'complete':found==144,'grid_rows':grid_rows,'grid_cols':grid_cols,'observed_cells':cells,'image_metrics':metrics,'source_sequence':source_sequence,'inspection_jpeg':inspection_jpeg}),flush=True)
        except Exception as e: print(json.dumps({'state':'NOT_OBSERVED_UNCERTAIN','found_corners':0,'expected_corners':144,'error':type(e).__name__}),flush=True)
if __name__=='__main__': main()
