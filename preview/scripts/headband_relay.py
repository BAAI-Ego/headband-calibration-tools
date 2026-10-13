#!/usr/bin/env python3
"""Temporary in-memory four-camera preview relay for the Orange Pi.

This file is sent to `python3 -` through SSH.  It is never written to the
headband.  It only subscribes, downsizes and republishes preview JPEGs; it
does not set parameters, record a BAG, or modify the existing camera nodes.
"""
import argparse
import threading
import time

import cv2
import numpy as np
import rospy
from sensor_msgs.msg import CompressedImage

SOURCES = {
    "LEFT": "/fisheye/left/image_raw/compressed",
    "RIGHT": "/fisheye/right/image_raw/compressed",
    "BRIGHT": "/fisheye/bright/image_raw/compressed",
    "BLEFT": "/fisheye/bleft/image_raw/compressed",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--fps", type=float, default=3.0)
    parser.add_argument("--quality", type=int, default=60)
    parser.add_argument("--max-seconds", type=float, default=0.0,
                        help="0 means run until interrupted")
    args = parser.parse_args()
    rospy.init_node("temporary_four_preview_relay", anonymous=True)
    lock = threading.RLock()
    latest = {name: None for name in SOURCES}
    serial = {name: 0 for name in SOURCES}
    sent = {name: -1 for name in SOURCES}
    publishers = {
        name: rospy.Publisher(f"/calibration_preview/{name.lower()}/image_raw/compressed",
                              CompressedImage, queue_size=1)
        for name in SOURCES
    }

    def receive(message, name):
        with lock:
            latest[name] = message
            serial[name] += 1

    subscribers = [rospy.Subscriber(topic, CompressedImage, receive,
                                    callback_args=name, queue_size=1,
                                    buff_size=4 * 1024 * 1024,
                                    tcp_nodelay=True)
                   for name, topic in SOURCES.items()]
    rospy.loginfo("temporary relay: 4 cameras, width=%d, target=%.1f FPS", args.width, args.fps)
    rate = rospy.Rate(max(0.2, args.fps))
    deadline = None if args.max_seconds <= 0 else time.monotonic() + max(10.0, args.max_seconds)
    try:
        while not rospy.is_shutdown() and (deadline is None or time.monotonic() < deadline):
            with lock:
                jobs = [(name, latest[name], serial[name]) for name in SOURCES]
            for name, message, number in jobs:
                if message is None or number == sent[name]:
                    continue
                image = cv2.imdecode(np.frombuffer(message.data, dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    continue
                height, width = image.shape[:2]
                if width > args.width:
                    image = cv2.resize(image, (args.width, max(1, round(height * args.width / width))),
                                       interpolation=cv2.INTER_AREA)
                ok, encoded = cv2.imencode(".jpg", image,
                                           [int(cv2.IMWRITE_JPEG_QUALITY), int(args.quality)])
                if not ok:
                    continue
                preview = CompressedImage()
                preview.header = message.header
                preview.format = "jpeg"
                preview.data = encoded.tobytes()
                publishers[name].publish(preview)
                sent[name] = number
            rate.sleep()
    finally:
        for subscriber in subscribers:
            subscriber.unregister()
        for publisher in publishers.values():
            publisher.unregister()


if __name__ == "__main__":
    main()
