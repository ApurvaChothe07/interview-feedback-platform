#!/usr/bin/env python3
"""
HTTP feedback service powered by a trained XGBoost multimodal model.
Spring Boot calls POST /analyze with a transcript (and optional gaze/audio data);
this returns the ML-evaluated feedback report.

Run:   python feedback_service.py            (listens on http://localhost:8000)
Check: curl http://localhost:8000/health
"""
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request

import extract_features as ef
import interview_feedback as fb
import tobii_collector as tc

app = Flask(__name__)

# Base configuration
cfg = fb.DEFAULTS
if os.environ.get("THRESHOLDS_FILE"):
    cfg = fb.merge(fb.DEFAULTS, json.loads(Path(os.environ["THRESHOLDS_FILE"]).read_text()))

# Load trained XGBoost model and feature column definitions
MODEL_DIR = Path(__file__).parent / "models"
MODEL_PATH = MODEL_DIR / "delivery_xgboost.joblib"
COLS_PATH = MODEL_DIR / "feature_columns.json"

MODEL = None
FEATURE_COLS = []

if MODEL_PATH.exists() and COLS_PATH.exists():
    try:
        MODEL = joblib.load(MODEL_PATH)
        FEATURE_COLS = json.loads(COLS_PATH.read_text())
        print(f"Loaded XGBoost model from {MODEL_PATH} with {len(FEATURE_COLS)} features.")
    except Exception as e:
        print(f"Warning: Failed to load XGBoost model: {e}")
else:
    print(f"Notice: Trained model not found at {MODEL_PATH}. Rule-based fallback active.")


def extract_live_features(df_transcript, gaze_data=None, audio_data=None, face_data=None):
    """
    Extracts multimodal features from incoming live interview data, aligning
    with the exact feature columns expected by the trained XGBoost model.
    """
    units = fb.build_units(df_transcript)
    valid_units = [u for u in units if (u["t1"] - u["t0"]) >= 0.5]
    ans_feats = [ef.speech_features(u) for u in valid_units]
    df_ans = pd.DataFrame(ans_feats) if ans_feats else pd.DataFrame()

    words = int(df_ans["word_count"].sum()) if not df_ans.empty else 0
    speech_min = float(df_ans["speech_time_s"].sum()) / 60.0 if not df_ans.empty else 0.0
    dur_min = float(df_ans["duration_s"].sum()) / 60.0 if not df_ans.empty else 0.0
    total_dur = float(df_transcript["stop_time"].max()) if len(df_transcript) else 0.0
    lat_series = df_ans["response_latency_s"].dropna().clip(lower=0) if not df_ans.empty else pd.Series(dtype=float)

    feat_dict = {
        "total_duration_s": total_dur,
        "answers_count": len(valid_units),
        "word_count": words,
        "speaking_pace_wpm": round(words / speech_min, 2) if speech_min > 0 else np.nan,
        "filler_rate": round(float(df_ans["filler_count"].sum()) / words, 4) if words > 0 else np.nan,
        "filler_count": int(df_ans["filler_count"].sum()) if not df_ans.empty else 0,
        "long_pauses_per_min": round(float(df_ans["long_pause_count"].sum()) / dur_min, 2) if dur_min > 0 else np.nan,
        "long_pause_count": int(df_ans["long_pause_count"].sum()) if not df_ans.empty else 0,
        "mean_pause_s": float(df_ans["mean_pause_s"].dropna().mean()) if not df_ans.empty and len(df_ans["mean_pause_s"].dropna()) else np.nan,
        "max_pause_s": float(df_ans["max_pause_s"].dropna().max()) if not df_ans.empty and len(df_ans["max_pause_s"].dropna()) else np.nan,
        "median_response_latency_s": float(lat_series.median()) if len(lat_series) else np.nan,
        "median_words_per_answer": float(df_ans["word_count"].median()) if not df_ans.empty else np.nan,
        "speech_ratio": float(df_ans["speech_time_s"].sum() / total_dur) if total_dur > 0 and not df_ans.empty else np.nan,
        "unique_word_ratio": float(df_ans["unique_word_ratio"].dropna().mean()) if not df_ans.empty and len(df_ans["unique_word_ratio"].dropna()) else np.nan,
    }

    # Gaze features (if sent from frontend)
    if isinstance(gaze_data, dict):
        feat_dict["gaze_stability_ratio"] = gaze_data.get("gaze_stability_ratio", gaze_data.get("stability_ratio", np.nan))
        feat_dict["gaze_yaw_std"] = gaze_data.get("gaze_yaw_std", gaze_data.get("yaw_std", np.nan))
        feat_dict["gaze_pitch_std"] = gaze_data.get("gaze_pitch_std", gaze_data.get("pitch_std", np.nan))
        feat_dict["gaze_valid_ratio"] = gaze_data.get("gaze_valid_ratio", 1.0)
    elif isinstance(gaze_data, list) and len(gaze_data) >= 5:
        # Array of frame coordinates: [{"x": ..., "y": ..., "timestamp": ...}]
        try:
            g_df = pd.DataFrame(gaze_data)
            if "x" in g_df.columns and "y" in g_df.columns:
                yaw = g_df["x"]
                pitch = g_df["y"]
                feat_dict["gaze_yaw_std"] = float(yaw.std())
                feat_dict["gaze_pitch_std"] = float(pitch.std())
                dev = np.hypot(yaw - yaw.median(), pitch - pitch.median())
                feat_dict["gaze_stability_ratio"] = float((dev < dev.quantile(0.85)).mean())
                feat_dict["gaze_valid_ratio"] = 1.0
        except Exception:
            pass

    # Audio acoustic features (if sent from frontend or audio worker)
    if isinstance(audio_data, dict):
        feat_dict["loudness_db_mean"] = audio_data.get("loudness_db_mean", audio_data.get("loudness_mean", np.nan))
        feat_dict["loudness_db_std"] = audio_data.get("loudness_db_std", audio_data.get("loudness_std", np.nan))

    # Facial dynamics (if sent from frontend)
    if isinstance(face_data, dict):
        feat_dict["smile_ratio"] = face_data.get("smile_ratio", np.nan)
        feat_dict["au_expressiveness"] = face_data.get("au_expressiveness", np.nan)
        feat_dict["head_movement_speed"] = face_data.get("head_movement_speed", np.nan)

    # Ensure all feature columns are present in exact order
    ordered_row = {}
    for col in FEATURE_COLS:
        ordered_row[col] = feat_dict.get(col, np.nan)

    return pd.DataFrame([ordered_row])[FEATURE_COLS]


@app.get("/health")
def health():
    engine_name = "xgboost_v1" if MODEL is not None else "rule_based_v0"
    return jsonify(
        status="ok",
        engine=engine_name,
        model_loaded=MODEL is not None,
        feature_count=len(FEATURE_COLS),
        tobii_device_connected=tc.COLLECTOR.eyetracker is not None
    )


@app.post("/gaze/start")
def gaze_start():
    tc.COLLECTOR.start()
    return jsonify(
        status="ok",
        message="Gaze tracking session started",
        device=tc.COLLECTOR.eyetracker.device_name if tc.COLLECTOR.eyetracker else "simulation"
    )


@app.post("/gaze/stop")
def gaze_stop():
    summary = tc.COLLECTOR.stop()
    return jsonify(status="ok", gaze_data=summary)


@app.post("/analyze")
def analyze():
    """
    Body payload:
    {
      "session_id": "42",
      "segments": [
        {"question_id": 1, "speaker": "candidate", "start_s": 12.4, "end_s": 18.9, "text": "..."}
      ],
      "gaze_data": optional dict or list,
      "audio_data": optional dict
    }
    """
    body = request.get_json(silent=True) or {}
    segments = body.get("segments")
    if not isinstance(segments, list) or not segments:
        return jsonify(error="'segments' must be a non-empty list"), 400

    try:
        session_id_str = str(body.get("session_id") or "session")
        df, sid = fb.normalize_df(pd.DataFrame(segments), session_id_str)
        report = fb.clean(fb.analyze(df, sid, cfg))

        # Apply XGBoost ML model prediction
        if MODEL is not None and FEATURE_COLS:
            live_features_df = extract_live_features(
                df_transcript=df,
                gaze_data=body.get("gaze_data"),
                audio_data=body.get("audio_data"),
                face_data=body.get("face_data"),
            )
            raw_pred = MODEL.predict(live_features_df)[0]
            ml_score = int(round(float(np.clip(raw_pred, 10.0, 100.0))))

            report["engine"] = "xgboost_v1"
            report["scores"]["delivery_overall"] = ml_score
            report["ml_metadata"] = {
                "engine": "xgboost_v1",
                "predicted_delivery_overall": ml_score,
                "features_used": len(FEATURE_COLS),
                "model_type": "XGBRegressor",
            }
        else:
            report["engine"] = "rule_based_v0"

    except (ValueError, KeyError) as e:
        return jsonify(error=str(e)), 422
    except Exception as e:
        return jsonify(error=f"Analysis error: {str(e)}"), 500

    return jsonify(report)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting feedback_service on port {port} (engine: {'xgboost_v1' if MODEL else 'rule_based_v0'})")
    app.run(host="0.0.0.0", port=port)
