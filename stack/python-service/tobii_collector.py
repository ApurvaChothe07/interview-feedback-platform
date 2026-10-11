#!/usr/bin/env python3
"""
Tobii Eye Tracker live stream collector.
Connects to hardware Tobii Eye Trackers using the official 'tobii-research' SDK.

Features extracted for XGBoost interview grading:
- gaze_stability_ratio: Fraction of interview candidate stayed focused on screen/camera.
- gaze_yaw_std: Horizontal gaze dispersion (degrees).
- gaze_pitch_std: Vertical gaze dispersion (degrees).
- gaze_valid_ratio: Eye-tracking tracking confidence / valid frame ratio.

Usage:
  1. Install SDK: pip install tobii-research
  2. Test connection: python tobii_collector.py --test
  3. Integrated in feedback_service.py via POST /gaze/start and POST /gaze/stop
"""
import sys
import threading
import time
import numpy as np

try:
    import tobii_research as tr
    HAS_TOBII_SDK = True
except ImportError:
    HAS_TOBII_SDK = False


class TobiiGazeCollector:
    def __init__(self):
        self.eyetracker = None
        self.is_tracking = False
        self.samples = []
        self.lock = threading.Lock()
        self._init_device()

    def _init_device(self):
        """Attempts to find and connect to a plugged-in Tobii Eye Tracker."""
        if not HAS_TOBII_SDK:
            print("[Tobii] Notice: 'tobii-research' package not installed. Run 'pip install tobii-research'.")
            return

        try:
            eyetrackers = tr.find_all_eyetrackers()
            if eyetrackers:
                self.eyetracker = eyetrackers[0]
                print(f"[Tobii] Connected to: {self.eyetracker.device_name} ({self.eyetracker.model})")
            else:
                print("[Tobii] No Tobii eye-tracker found on this machine. (Ensure USB is connected).")
        except Exception as e:
            print(f"[Tobii] Error finding eye tracker: {e}")

    def _gaze_data_callback(self, gaze_data):
        """Internal callback invoked by Tobii hardware stream for each gaze frame."""
        with self.lock:
            if not self.is_tracking:
                return

            # Read normalized gaze coordinates on display area (0.0 to 1.0)
            left_eye = gaze_data.get('left_gaze_point_on_display_area')
            right_eye = gaze_data.get('right_gaze_point_on_display_area')

            # Averaging both eyes if valid
            points = []
            if left_eye and not (np.isnan(left_eye[0]) or np.isnan(left_eye[1])):
                points.append(left_eye)
            if right_eye and not (np.isnan(right_eye[0]) or np.isnan(right_eye[1])):
                points.append(right_eye)

            if points:
                avg_x = sum(p[0] for p in points) / len(points)
                avg_y = sum(p[1] for p in points) / len(points)
                self.samples.append({
                    "t": time.time(),
                    "valid": True,
                    "x": avg_x,
                    "y": avg_y
                })
            else:
                self.samples.append({
                    "t": time.time(),
                    "valid": False,
                    "x": np.nan,
                    "y": np.nan
                })

    def start(self):
        """Start capturing live gaze frames."""
        with self.lock:
            self.samples = []
            self.is_tracking = True

        if self.eyetracker and HAS_TOBII_SDK:
            try:
                self.eyetracker.subscribe_to(
                    tr.EYETRACKER_GAZE_DATA,
                    self._gaze_data_callback,
                    as_dictionary=True
                )
                print("[Tobii] Live gaze tracking subscribed.")
            except Exception as e:
                print(f"[Tobii] Could not subscribe to eye tracker: {e}")
        else:
            print("[Tobii] Tracking started in simulation/no-hardware mode.")

    def stop(self):
        """Stop tracking and compute summary features for ML model."""
        with self.lock:
            self.is_recording = False
            self.is_tracking = False

        if self.eyetracker and HAS_TOBII_SDK:
            try:
                self.eyetracker.unsubscribe_from(
                    tr.EYETRACKER_GAZE_DATA,
                    self._gaze_data_callback
                )
                print("[Tobii] Live gaze tracking unsubscribed.")
            except Exception as e:
                print(f"[Tobii] Unsubscribe error: {e}")

        with self.lock:
            samples_copy = list(self.samples)

        if not samples_copy:
            return {
                "gaze_stability_ratio": None,
                "gaze_yaw_std": None,
                "gaze_pitch_std": None,
                "gaze_valid_ratio": 0.0,
                "samples_count": 0,
                "source": "none"
            }

        valid_pts = [s for s in samples_copy if s["valid"]]
        valid_ratio = len(valid_pts) / len(samples_copy)

        if len(valid_pts) < 10:
            return {
                "gaze_stability_ratio": None,
                "gaze_yaw_std": None,
                "gaze_pitch_std": None,
                "gaze_valid_ratio": round(valid_ratio, 3),
                "samples_count": len(samples_copy),
                "source": "insufficient_valid_frames"
            }

        xs = np.array([p["x"] for p in valid_pts])
        ys = np.array([p["y"] for p in valid_pts])

        # Center is (0.5, 0.5) in normalized screen space
        dist_from_center = np.hypot(xs - 0.5, ys - 0.5)
        # Looking near the screen center (interviewer window) counts as stable eye contact
        stability_ratio = float((dist_from_center < 0.28).mean())

        # Approximate angular dispersion (assuming ~30 degree horizontal field of view)
        yaw_std = float(xs.std() * 32.0)
        pitch_std = float(ys.std() * 24.0)

        return {
            "gaze_stability_ratio": round(stability_ratio, 3),
            "gaze_yaw_std": round(yaw_std, 3),
            "gaze_pitch_std": round(pitch_std, 3),
            "gaze_valid_ratio": round(valid_ratio, 3),
            "samples_count": len(samples_copy),
            "source": "tobii_hardware"
        }


# Global instance
COLLECTOR = TobiiGazeCollector()


if __name__ == "__main__":
    print("Testing Tobii Collector...")
    if not HAS_TOBII_SDK:
        print("Install the SDK with: pip install tobii-research")
        sys.exit(0)

    eyetrackers = tr.find_all_eyetrackers()
    if not eyetrackers:
        print("No Tobii eye tracker connected to this machine.")
        sys.exit(0)

    tracker = eyetrackers[0]
    print(f"Found tracker: {tracker.device_name} (S/N: {tracker.serial_number})")
    print("Recording 5 seconds of gaze data to test...")
    COLLECTOR.start()
    time.sleep(5)
    summary = COLLECTOR.stop()
    print("Gaze Summary:", summary)
