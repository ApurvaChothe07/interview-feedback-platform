#!/usr/bin/env python3
"""
Feature extraction across all sessions in the DAIC-WOZ dataset (including subfolders).
Extracts:
1. Audio-to-text / Speech & timing features (pace, fillers, pauses, response latency, answer detail)
2. Eye gaze & visual attention (gaze stability ratio, gaze yaw/pitch variance)
3. Head pose & facial action units (head movement speed, AU expressiveness, smile ratio)
4. Audio acoustics (vocal loudness mean & dynamic range)
5. Calibrated multimodal Ground-Truth Delivery Score (0-100 rubric)
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import extract_features as ef
import interview_feedback as fb

# Delivery rubric scoring functions
def score_band(x, ideal, ok):
    lo, hi = ideal
    olo, ohi = ok
    if lo <= x <= hi:
        return 100.0
    if x < lo:
        gap, d = max(lo - olo, 1e-9), lo - x
    else:
        gap, d = max(ohi - hi, 1e-9), x - hi
    return max(0.0, 100.0 - 40.0 * d / gap)

def score_lower(x, good, high):
    return 100.0 if x <= good else max(0.0, 100.0 - 40.0 * (x - good) / max(high - good, 1e-9))

def score_higher(x, ideal, ok):
    return 100.0 if x >= ideal else max(0.0, 100.0 - 40.0 * (ideal - x) / max(ideal - ok, 1e-9))

def compute_ground_truth_score(rec):
    """
    Computes an established behavioral delivery score (0 to 100)
    combining speech fluency (55%), gaze stability / eye contact (25%),
    and facial warmth & vocal projection (20%).
    """
    # 1. Speech fluency components
    wpm = rec.get("speaking_pace_wpm")
    pace_score = score_band(wpm, [120, 170], [100, 190]) if (wpm is not None and not np.isnan(wpm)) else 70.0
    
    fr = rec.get("filler_rate")
    filler_score = score_lower(fr, 0.03, 0.07) if (fr is not None and not np.isnan(fr)) else 70.0
    
    lp = rec.get("long_pauses_per_min")
    pause_score = score_lower(lp, 2.0, 6.0) if (lp is not None and not np.isnan(lp)) else 70.0
    
    lat = rec.get("median_response_latency_s")
    lat_score = score_band(lat, [0.0, 2.0], [0.0, 4.0]) if (lat is not None and not np.isnan(lat)) else 70.0
    
    wpa = rec.get("median_words_per_answer")
    detail_score = score_higher(wpa, 30, 12) if (wpa is not None and not np.isnan(wpa)) else 70.0
    
    speech_delivery = (0.28 * pace_score + 0.24 * filler_score + 0.16 * pause_score + 0.16 * lat_score + 0.16 * detail_score)
    
    # 2. Gaze / Visual Eye Contact component (target >= 70% stability toward camera)
    g_stab = rec.get("gaze_stability_ratio")
    if g_stab is not None and not np.isnan(g_stab):
        gaze_score = score_higher(g_stab, 0.75, 0.45)
    else:
        gaze_score = speech_delivery  # fallback if missing

    # 3. Facial warmth & vocal projection component
    smile = rec.get("smile_ratio", 0.0)
    au_exp = rec.get("au_expressiveness", 0.0)
    loud_std = rec.get("loudness_db_std", 0.0)
    
    # Warmth & expressiveness (penalizes flat affect / frozen expression)
    smile_val = smile if (smile is not None and not np.isnan(smile)) else 0.05
    exp_val = au_exp if (au_exp is not None and not np.isnan(exp_val if 'exp_val' in locals() else au_exp)) else 0.35
    warmth_score = min(100.0, 50.0 + min(smile_val * 400.0, 30.0) + min(exp_val * 50.0, 20.0))
    
    # Vocal projection variation (target healthy dynamics 6-12 dB)
    loud_std_val = loud_std if (loud_std is not None and not np.isnan(loud_std)) else 8.0
    vocal_score = score_band(loud_std_val, [6.0, 12.0], [3.0, 16.0])
    
    engagement_score = 0.5 * warmth_score + 0.5 * vocal_score
    
    # Composite calibrated score
    overall = 0.55 * speech_delivery + 0.25 * gaze_score + 0.20 * engagement_score
    return round(float(np.clip(overall, 10.0, 100.0)), 1)


def process_single_session(tpath):
    sid = tpath.name.split("_")[0]
    d = tpath.parent
    
    # 1. Transcript (Audio to text)
    tr = ef.load_transcript(tpath)
    total_dur = float(tr.stop_time.max()) if len(tr) else 0.0
    answers = ef.build_answers(tr)
    valid_answers = [u for u in answers if (u["t1"] - u["t0"]) >= 0.5]
    
    ans_feats = [ef.speech_features(u) for u in valid_answers]
    df_ans = pd.DataFrame(ans_feats) if ans_feats else pd.DataFrame()
    
    words = int(df_ans["word_count"].sum()) if not df_ans.empty else 0
    speech_min = float(df_ans["speech_time_s"].sum()) / 60.0 if not df_ans.empty else 0.0
    dur_min = float(df_ans["duration_s"].sum()) / 60.0 if not df_ans.empty else 0.0
    lat_series = df_ans["response_latency_s"].dropna().clip(lower=0) if not df_ans.empty else pd.Series(dtype=float)
    
    rec = {
        "session_id": sid,
        "total_duration_s": round(total_dur, 2),
        "answers_count": len(valid_answers),
        "word_count": words,
        "speaking_pace_wpm": round(words / speech_min, 2) if speech_min > 0 else np.nan,
        "filler_rate": round(float(df_ans["filler_count"].sum()) / words, 4) if words > 0 else np.nan,
        "filler_count": int(df_ans["filler_count"].sum()) if not df_ans.empty else 0,
        "long_pauses_per_min": round(float(df_ans["long_pause_count"].sum()) / dur_min, 2) if dur_min > 0 else np.nan,
        "long_pause_count": int(df_ans["long_pause_count"].sum()) if not df_ans.empty else 0,
        "mean_pause_s": round(float(df_ans["mean_pause_s"].dropna().mean()), 3) if not df_ans.empty and len(df_ans["mean_pause_s"].dropna()) else np.nan,
        "max_pause_s": round(float(df_ans["max_pause_s"].dropna().max()), 3) if not df_ans.empty and len(df_ans["max_pause_s"].dropna()) else np.nan,
        "median_response_latency_s": round(float(lat_series.median()), 2) if len(lat_series) else np.nan,
        "median_words_per_answer": round(float(df_ans["word_count"].median()), 1) if not df_ans.empty else np.nan,
        "speech_ratio": round(float(df_ans["speech_time_s"].sum() / total_dur), 3) if total_dur > 0 and not df_ans.empty else np.nan,
        "unique_word_ratio": round(float(df_ans["unique_word_ratio"].dropna().mean()), 3) if not df_ans.empty and len(df_ans["unique_word_ratio"].dropna()) else np.nan,
    }
    
    # 2. Eye Gaze & Attention
    gaze_file = d / f"{sid}_CLNF_gaze.txt"
    if not gaze_file.exists():
        # Check parent or other folders if distributed
        matches = list(d.parent.rglob(f"{sid}_CLNF_gaze.txt"))
        if matches:
            gaze_file = matches[0]
            
    if gaze_file.exists():
        try:
            gaze_df = ef.load_clnf(gaze_file)
            g_valid = gaze_df[gaze_df.success == 1]
            if len(g_valid) >= 10:
                x = (g_valid.x_0 + g_valid.x_1) / 2.0
                y = (g_valid.y_0 + g_valid.y_1) / 2.0
                z = (g_valid.z_0 + g_valid.z_1) / 2.0
                yaw = np.degrees(np.arctan2(x, -z))
                pitch = np.degrees(np.arctan2(y, -z))
                rec["gaze_yaw_std"] = round(float(yaw.std()), 3)
                rec["gaze_pitch_std"] = round(float(pitch.std()), 3)
                dev = np.hypot(yaw - yaw.median(), pitch - pitch.median())
                rec["gaze_stability_ratio"] = round(float((dev < 10.0).mean()), 3)
                rec["gaze_valid_ratio"] = round(float(len(g_valid) / len(gaze_df)), 3)
        except Exception as e:
            print(f"  Warning loading gaze for {sid}: {e}", file=sys.stderr)
            
    # 3. Facial dynamics & Head pose
    aus_file = d / f"{sid}_CLNF_AUs.txt"
    if aus_file.exists():
        try:
            aus_df = ef.load_clnf(aus_file)
            a_valid = aus_df[aus_df.success == 1]
            if len(a_valid) >= 10:
                r_cols = [c for c in a_valid.columns if c.endswith("_r")]
                rec["au_expressiveness"] = round(float(a_valid[r_cols].std().mean()), 4) if r_cols else np.nan
                rec["au_activation"] = round(float(a_valid[r_cols].mean().mean()), 4) if r_cols else np.nan
                if "AU12_c" in a_valid.columns:
                    rec["smile_ratio"] = round(float(a_valid["AU12_c"].mean()), 4)
                if "AU45_c" in a_valid.columns:
                    rec["blink_ratio"] = round(float(a_valid["AU45_c"].mean()), 4)
        except Exception as e:
            print(f"  Warning loading AUs for {sid}: {e}", file=sys.stderr)
            
    pose_file = d / f"{sid}_CLNF_pose.txt"
    if pose_file.exists():
        try:
            pose_df = ef.load_clnf(pose_file)
            p_valid = pose_df[pose_df.success == 1]
            if len(p_valid) >= 10:
                rec["head_pitch_std"] = round(float(np.degrees(p_valid.Rx.std())), 3)
                rec["head_yaw_std"] = round(float(np.degrees(p_valid.Ry.std())), 3)
                rec["head_roll_std"] = round(float(np.degrees(p_valid.Rz.std())), 3)
                dt = p_valid.timestamp.diff().replace(0, np.nan)
                speed = np.sqrt(p_valid.Tx.diff() ** 2 + p_valid.Ty.diff() ** 2 + p_valid.Tz.diff() ** 2) / dt
                rec["head_movement_speed"] = round(float(speed.dropna().median()), 2)
        except Exception as e:
            print(f"  Warning loading pose for {sid}: {e}", file=sys.stderr)

    # 4. Audio Acoustics
    wav_file = d / f"{sid}_AUDIO.wav"
    if wav_file.exists():
        try:
            rms_df = ef.load_wav_rms_db(wav_file)
            act = rms_df[rms_df.rms_db > rms_df.rms_db.quantile(0.3)]
            if len(act):
                rec["loudness_db_mean"] = round(float(act.rms_db.mean()), 2)
                rec["loudness_db_std"] = round(float(act.rms_db.std()), 2)
        except Exception as e:
            print(f"  Warning loading audio for {sid}: {e}", file=sys.stderr)

    # 5. Calibrated Ground Truth Delivery Score
    rec["delivery_overall"] = compute_ground_truth_score(rec)
    return rec


def main():
    parser = argparse.ArgumentParser(description="Extract multimodal features from DAIC-WOZ sessions.")
    parser.add_argument("--data_dir", default=r"E:\Cap_2303054", help="Path to dataset root")
    parser.add_argument("--out", default="dataset_features.csv", help="Output CSV path")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    print(f"Searching for transcript files under {data_dir}...")
    tpaths = sorted(data_dir.rglob("*_TRANSCRIPT.csv"))
    print(f"Found {len(tpaths)} sessions.")

    records = []
    for i, tp in enumerate(tpaths, 1):
        sid = tp.name.split("_")[0]
        print(f"[{i}/{len(tpaths)}] Extracting session {sid} ...")
        try:
            rec = process_single_session(tp)
            records.append(rec)
        except Exception as e:
            print(f"  ERROR processing {tp.name}: {e}", file=sys.stderr)

    df = pd.DataFrame(records)
    out_path = Path(args.out)
    df.to_csv(out_path, index=False)
    print(f"\nSuccessfully extracted {len(df)} sessions with {df.shape[1]} features.")
    print(f"Saved to: {out_path.resolve()}")
    print("\nSummary of extracted Delivery Overall scores:")
    print(df["delivery_overall"].describe())


if __name__ == "__main__":
    main()
