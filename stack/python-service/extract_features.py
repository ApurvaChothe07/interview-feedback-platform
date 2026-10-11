#!/usr/bin/env python3
"""
Feature extraction for DAIC-WOZ style interview sessions.

Produces one row per participant ANSWER (default) or per sliding WINDOW,
combining speech/transcript, voice, face (AUs), gaze and head-pose features.
No labels are used. When you later have ratings, merge them onto the output
CSV using (session_id, unit_id) and train.

Usage:
    python extract_features.py --data_dir /path/to/sessions --out features.csv
    python extract_features.py --data_dir . --mode windows --window 20 --stride 5

Expected files per session (prefix = session id, e.g. 300):
    300_TRANSCRIPT.csv  300_COVAREP.csv  300_FORMANT.csv
    300_CLNF_AUs.txt    300_CLNF_gaze.txt  300_CLNF_pose.txt
    300_AUDIO.wav  (optional; used for loudness)
Sessions may sit in one flat folder or in sub-folders (e.g. 300_P/).
CLNF_hog / features / features3D are intentionally not used.
"""
import argparse
import re
import sys
import wave
from pathlib import Path

import numpy as np
import pandas as pd

COVAREP_STEP = 0.01   # 100 Hz
FORMANT_STEP = 0.01   # 100 Hz
FILLERS = {"um", "umm", "uh", "uhm", "er", "erm", "ah", "hmm", "mm", "mmm"}
LONG_PAUSE = 1.0      # seconds; gap between participant utterances

# COVAREP column layout (74 columns, no header in the file)
COVAREP_COLS = (
    ["F0", "VUV", "NAQ", "QOQ", "H1H2", "PSP", "MDQ", "peakSlope", "Rd", "Rd_conf", "creak"]
    + [f"MCEP_{i}" for i in range(25)]
    + [f"HMPDM_{i}" for i in range(25)]
    + [f"HMPDD_{i}" for i in range(13)]
)


# ----------------------------------------------------------------- loaders
def load_transcript(path):
    t = pd.read_csv(path, sep="\t")
    t = t.dropna(subset=["start_time", "stop_time", "speaker"]).copy()
    t["value"] = t["value"].fillna("").astype(str)
    return t.sort_values("start_time").reset_index(drop=True)


def load_covarep(path):
    c = pd.read_csv(path, header=None)
    if c.shape[1] == len(COVAREP_COLS):
        c.columns = COVAREP_COLS
    c["t"] = np.arange(len(c)) * COVAREP_STEP
    return c


def load_formant(path):
    f = pd.read_csv(path, header=None)
    f.columns = [f"F{i + 1}" for i in range(f.shape[1])]
    f["t"] = np.arange(len(f)) * FORMANT_STEP
    return f


def load_clnf(path):
    return pd.read_csv(path, skipinitialspace=True)


def load_wav_rms_db(path, frame=0.05):
    """Return DataFrame(t, rms_db) at `frame` second resolution."""
    with wave.open(str(path)) as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}[sw]
    x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    x /= float(np.iinfo(dtype).max)
    hop = int(sr * frame)
    m = len(x) // hop
    rms = np.sqrt((x[: m * hop].reshape(m, hop) ** 2).mean(axis=1) + 1e-12)
    return pd.DataFrame({"t": np.arange(m) * frame, "rms_db": 20 * np.log10(rms + 1e-9)})


# ------------------------------------------------------- unit definitions
def build_answers(tr):
    """An answer = consecutive participant rows between interviewer turns."""
    units, cur, last_ellie_stop, last_ellie_text = [], None, None, ""
    for _, r in tr.iterrows():
        if r.speaker == "Participant":
            if cur is None:
                cur = {"rows": [], "prev_ellie_stop": last_ellie_stop, "question": last_ellie_text}
            cur["rows"].append(r)
        else:  # interviewer
            if cur is not None:
                units.append(cur)
                cur = None
            last_ellie_stop, last_ellie_text = r.stop_time, r.value
    if cur is not None:
        units.append(cur)
    out = []
    for i, u in enumerate(units):
        rows = pd.DataFrame(u["rows"])
        out.append({"unit_id": i, "t0": rows.start_time.min(), "t1": rows.stop_time.max(),
                    "rows": rows, "prev_ellie_stop": u["prev_ellie_stop"], "question": u["question"]})
    return out


def build_windows(tr, total_dur, window, stride):
    out, t, i = [], 0.0, 0
    p = tr[tr.speaker == "Participant"]
    while t + window <= total_dur + 1e-6:
        rows = p[(p.start_time >= t) & (p.start_time < t + window)]
        out.append({"unit_id": i, "t0": t, "t1": t + window, "rows": rows,
                    "prev_ellie_stop": None, "question": ""})
        t += stride
        i += 1
    return out


# ---------------------------------------------------------------- features
def clean_words(text):
    text = re.sub(r"<[^>]*>", " ", text.lower())      # <laughter>, <synch> ...
    text = re.sub(r"[^a-z' ]", " ", text)
    return [w for w in text.split() if w and w != "xxx"]


def speech_features(u):
    rows, t0, t1 = u["rows"], u["t0"], u["t1"]
    dur = max(t1 - t0, 1e-6)
    f = {"duration_s": t1 - t0}
    if len(rows) == 0:
        return {**f, "n_utterances": 0, "word_count": 0, "wpm": np.nan, "filler_count": 0,
                "filler_rate": np.nan, "speech_time_s": 0.0, "speech_ratio": 0.0,
                "pause_count": 0, "long_pause_count": 0, "mean_pause_s": np.nan,
                "max_pause_s": np.nan, "response_latency_s": np.nan, "unique_word_ratio": np.nan}
    words = [w for v in rows.value for w in clean_words(v)]
    fillers = sum(w in FILLERS for w in words)
    speech_time = float((rows.stop_time - rows.start_time).sum())
    gaps = (rows.start_time.values[1:] - rows.stop_time.values[:-1]) if len(rows) > 1 else np.array([])
    gaps = gaps[gaps > 0]
    lat = (u["t0"] - u["prev_ellie_stop"]) if u["prev_ellie_stop"] is not None else np.nan
    content = [w for w in words if w not in FILLERS]
    return {
        **f,
        "n_utterances": int(len(rows)),
        "word_count": len(words),
        "wpm": len(words) / (speech_time / 60) if speech_time > 0 else np.nan,   # pace while speaking
        "filler_count": int(fillers),
        "filler_rate": fillers / len(words) if words else np.nan,
        "speech_time_s": speech_time,
        "speech_ratio": min(speech_time / dur, 1.0),
        "pause_count": int(len(gaps)),
        "long_pause_count": int((gaps >= LONG_PAUSE).sum()),
        "mean_pause_s": float(gaps.mean()) if len(gaps) else np.nan,
        "max_pause_s": float(gaps.max()) if len(gaps) else np.nan,
        "response_latency_s": lat,
        "unique_word_ratio": len(set(content)) / len(content) if content else np.nan,
    }


def sl(df, t0, t1, tcol="t"):
    return df[(df[tcol] >= t0) & (df[tcol] < t1)]


def voice_features(cov, form, rms, t0, t1):
    f = {}
    if cov is not None and "F0" in cov:
        c = sl(cov, t0, t1)
        voiced = c[(c.VUV == 1) & (c.F0 > 0)]
        f["voiced_ratio"] = len(voiced) / len(c) if len(c) else np.nan
        if len(voiced) > 5:
            f1 = voiced.F0
            f["f0_mean"], f["f0_std"] = f1.mean(), f1.std()
            f["f0_range"] = f1.quantile(0.95) - f1.quantile(0.05)
            f["h1h2_mean"], f["peakslope_mean"] = voiced.H1H2.mean(), voiced.peakSlope.mean()
            f["creak_mean"] = voiced.creak.mean()
        if form is not None and len(voiced):
            fm = sl(form, t0, t1)
            fm = fm[fm.t.isin(voiced.t.round(2))] if len(fm) else fm
            for k in ("F1", "F2"):
                if k in fm and len(fm):
                    f[f"{k.lower()}_mean"], f[f"{k.lower()}_std"] = fm[k].mean(), fm[k].std()
    if rms is not None:
        r = sl(rms, t0, t1)
        if len(r):
            act = r[r.rms_db > r.rms_db.quantile(0.3)]   # drop quiet frames
            f["loudness_db_mean"] = act.rms_db.mean() if len(act) else np.nan
            f["loudness_db_std"] = act.rms_db.std() if len(act) else np.nan
    return f


def face_features(aus, t0, t1):
    if aus is None:
        return {}
    a = sl(aus, t0, t1, "timestamp")
    a = a[a.success == 1]
    if len(a) < 5:
        return {"face_valid_ratio": 0.0}
    r_cols = [c for c in a.columns if c.endswith("_r")]
    f = {"face_valid_ratio": len(a) / max(1, len(sl(aus, t0, t1, "timestamp")))}
    for au in ("AU01", "AU04", "AU06", "AU12", "AU15", "AU25"):
        if f"{au}_r" in a:
            f[f"{au.lower()}_mean"] = a[f"{au}_r"].mean()
    f["au_expressiveness"] = a[r_cols].std().mean()      # how much AUs vary
    f["au_activation"] = a[r_cols].mean().mean()
    if "AU12_c" in a:
        f["smile_ratio"] = a["AU12_c"].mean()
    if "AU45_c" in a:
        f["blink_ratio"] = a["AU45_c"].mean()
    return f


def gaze_pose_features(gaze, pose, t0, t1):
    f = {}
    if gaze is not None:
        g = sl(gaze, t0, t1, "timestamp")
        g = g[g.success == 1]
        if len(g) >= 5:
            x = (g.x_0 + g.x_1) / 2
            y = (g.y_0 + g.y_1) / 2
            z = (g.z_0 + g.z_1) / 2
            yaw = np.degrees(np.arctan2(x, -z))
            pitch = np.degrees(np.arctan2(y, -z))
            f["gaze_yaw_std"], f["gaze_pitch_std"] = yaw.std(), pitch.std()
            dev = np.hypot(yaw - yaw.median(), pitch - pitch.median())
            # share of time the gaze stays near the person's own typical direction
            f["gaze_stability_ratio"] = float((dev < 10).mean())
    if pose is not None:
        p = sl(pose, t0, t1, "timestamp")
        p = p[p.success == 1]
        if len(p) >= 5:
            f["head_pitch_std"], f["head_yaw_std"], f["head_roll_std"] = (
                np.degrees(p.Rx.std()), np.degrees(p.Ry.std()), np.degrees(p.Rz.std()))
            dt = p.timestamp.diff().replace(0, np.nan)
            f["head_move_speed_mm_s"] = float((np.sqrt(p.Tx.diff() ** 2 + p.Ty.diff() ** 2 + p.Tz.diff() ** 2) / dt).mean())
            f["head_rot_speed_deg_s"] = float((np.degrees(np.sqrt(p.Rx.diff() ** 2 + p.Ry.diff() ** 2 + p.Rz.diff() ** 2)) / dt).mean())
    return f


# --------------------------------------------------------------- pipeline
def find_sessions(data_dir):
    return sorted(Path(data_dir).rglob("*_TRANSCRIPT.csv"))


def opt(loader, path):
    try:
        return loader(path) if path.exists() else None
    except Exception as e:                                  # keep going on a bad file
        print(f"  ! could not read {path.name}: {e}", file=sys.stderr)
        return None


def process_session(tpath, mode, window, stride):
    sid = tpath.name.split("_")[0]
    d = tpath.parent
    tr = load_transcript(tpath)
    cov = opt(load_covarep, d / f"{sid}_COVAREP.csv")
    form = opt(load_formant, d / f"{sid}_FORMANT.csv")
    aus = opt(load_clnf, d / f"{sid}_CLNF_AUs.txt")
    gaze = opt(load_clnf, d / f"{sid}_CLNF_gaze.txt")
    pose = opt(load_clnf, d / f"{sid}_CLNF_pose.txt")
    rms = opt(load_wav_rms_db, d / f"{sid}_AUDIO.wav")

    total = float(tr.stop_time.max())
    units = build_answers(tr) if mode == "answers" else build_windows(tr, total, window, stride)
    rows = []
    for u in units:
        if mode == "answers" and u["t1"] - u["t0"] < 0.5:
            continue
        rec = {"session_id": sid, "unit_id": u["unit_id"], "start_s": round(u["t0"], 3),
               "end_s": round(u["t1"], 3), "question_text": u["question"]}
        rec.update(speech_features(u))
        rec.update(voice_features(cov, form, rms, u["t0"], u["t1"]))
        rec.update(face_features(aus, u["t0"], u["t1"]))
        rec.update(gaze_pose_features(gaze, pose, u["t0"], u["t1"]))
        rows.append(rec)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data_dir", required=True)
    ap.add_argument("--out", default="features.csv")
    ap.add_argument("--mode", choices=["answers", "windows"], default="answers")
    ap.add_argument("--window", type=float, default=20.0, help="window length in s (windows mode)")
    ap.add_argument("--stride", type=float, default=5.0, help="window stride in s (windows mode)")
    args = ap.parse_args()

    paths = find_sessions(args.data_dir)
    if not paths:
        sys.exit(f"No *_TRANSCRIPT.csv found under {args.data_dir}")
    frames = []
    for p in paths:
        print(f"Session {p.name.split('_')[0]} ...")
        try:
            frames.append(process_session(p, args.mode, args.window, args.stride))
        except Exception as e:
            print(f"  ! skipped {p.name}: {e}", file=sys.stderr)
    df = pd.concat(frames, ignore_index=True)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} rows x {df.shape[1]} columns from {len(frames)} sessions -> {args.out}")


if __name__ == "__main__":
    main()
