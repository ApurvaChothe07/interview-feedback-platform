#!/usr/bin/env python3
"""
Rule-based post-interview feedback from a timestamped transcript.

Reads ONE session transcript, computes per-answer and per-session delivery
metrics (pace, fillers, pauses, response delay, answer detail), scores them
against editable target ranges, and writes a JSON report that a Spring Boot
backend can store and a React /summary page can render.

Needs extract_features.py in the same folder (it reuses its transcript code).

Accepted transcript formats
  1. DAIC-WOZ:  tab-separated  start_time, stop_time, speaker, value
                (speakers: Ellie / Participant)
  2. Your own:  CSV (or tab)   start_s, end_s, speaker, text
                optional columns: question_id, session_id
                (speakers: interviewer / candidate)

Usage
    python interview_feedback.py --transcript 300_TRANSCRIPT.csv --out feedback_300.json
    python interview_feedback.py --write_default_thresholds thresholds.json   # then edit it
    python interview_feedback.py --transcript my_session.csv --thresholds thresholds.json

IMPORTANT: scores are preliminary heuristics. Target ranges are starting
defaults, not validated norms; calibrate them on your own data before relying
on them. This report does NOT measure focus, confidence or interview quality.
"""
import argparse
import copy
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import extract_features as ef

DEFAULTS = {
    "min_words_for_rates": 10,                  # need this many words to judge pace/fillers in one answer
    "long_pause_s": 1.5,                        # gap between utterances counted as a long pause
    "pace_wpm": {"ideal": [120, 170], "ok": [100, 190]},
    "filler_rate": {"good": 0.03, "high": 0.07},                  # fillers per word, lower is better
    "long_pauses_per_min": {"good": 2.0, "high": 6.0},            # lower is better
    "response_latency_s": {"ideal": [0.0, 2.0], "ok": [0.0, 4.0]},
    "answer_words": {"ideal": 30, "ok": 12},                      # higher is better (median words per answer)
    "weights": {"pace": 0.30, "fillers": 0.25, "pauses": 0.15, "responsiveness": 0.15, "answer_detail": 0.15},
    "strength_min_score": 85,
    "improve_max_score": 75,
}

LABELS = {"pace": "Speaking pace", "fillers": "Filler words", "pauses": "Pauses",
          "responsiveness": "Response time", "answer_detail": "Answer detail"}

TIPS = {
    "pace_fast": "Practice an answer aloud with a timer and aim to finish each point with a short pause before the next.",
    "pace_slow": "Rehearse answers until the content is familiar; confident recall usually brings pace into range.",
    "fillers": "Record one answer and count fillers; replace each with a silent one-second pause.",
    "pauses": "Outline answers in 2-3 points before speaking so you are not searching for the next idea mid-answer.",
    "responsiveness": "Start by restating the question in a few words, then answer; this buys thinking time naturally.",
    "answer_detail": "Use a simple structure: situation, what you did, result. Aim for 30+ words per answer.",
}


# ------------------------------------------------------------- scoring
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


# --------------------------------------------------------------- input
def normalize_df(df, session_id=None, fallback_id="session"):
    """Accept a DataFrame in either supported format; return (clean_df, session_id)."""
    df = df.rename(columns={"start_s": "start_time", "end_s": "stop_time", "text": "value"})
    need = {"start_time", "stop_time", "speaker", "value"}
    if not need.issubset(df.columns):
        raise ValueError(f"Transcript needs columns {sorted(need)} (or start_s/end_s/speaker/text); found {list(df.columns)}")
    df = df.dropna(subset=["start_time", "stop_time", "speaker"]).copy()
    df["start_time"] = pd.to_numeric(df["start_time"])
    df["stop_time"] = pd.to_numeric(df["stop_time"])
    df["value"] = df["value"].fillna("").astype(str)
    cand = {"participant", "candidate", "interviewee", "user"}
    df["speaker"] = np.where(df["speaker"].astype(str).str.lower().isin(cand), "Participant", "Ellie")
    df = df.sort_values("start_time").reset_index(drop=True)
    sid = session_id or (str(df["session_id"].iloc[0]) if "session_id" in df.columns and len(df) else fallback_id)
    return df, sid


def load_any(path, session_id=None):
    p = Path(path)
    first = p.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    df = pd.read_csv(p, sep="\t" if "\t" in first else ",")
    return normalize_df(df, session_id, p.name.split("_")[0])


def build_units(tr):
    if "question_id" not in tr.columns:
        return ef.build_answers(tr)
    units = []
    for i, (qid, g) in enumerate(tr.groupby("question_id", sort=False)):
        cand = g[g.speaker == "Participant"]
        if cand.empty:
            continue
        intv = g[g.speaker != "Participant"]
        units.append({"unit_id": i, "question_id": qid, "t0": cand.start_time.min(), "t1": cand.stop_time.max(),
                      "rows": cand.sort_values("start_time"),
                      "prev_ellie_stop": intv.stop_time.max() if len(intv) else None,
                      "question": " ".join(intv.value)})
    return units


# ---------------------------------------------------------- per answer
def answer_feedback(f, cfg):
    flags = []
    n = f["word_count"]
    if n >= cfg["min_words_for_rates"] and f["wpm"] == f["wpm"]:
        lo, hi = cfg["pace_wpm"]["ok"]
        if f["wpm"] > hi:
            flags.append(("fast_pace", f"Fast pace ({f['wpm']:.0f} wpm); slow down slightly and pause between points."))
        elif f["wpm"] < lo:
            flags.append(("slow_pace", f"Slow pace ({f['wpm']:.0f} wpm); try linking ideas with fewer gaps."))
        if f["filler_rate"] == f["filler_rate"] and f["filler_rate"] > cfg["filler_rate"]["high"]:
            flags.append(("fillers", f"{f['filler_count']} filler words ({f['filler_rate']*100:.0f}% of words); pause silently instead."))
    if f["long_pause_count"] >= 2:
        flags.append(("pauses", f"{f['long_pause_count']} long pauses inside this answer; outline your points first."))
    if n < cfg["answer_words"]["ok"]:
        flags.append(("brief", f"Brief answer ({n} words); add a reason and an example."))
    if not flags:
        msg = ["No delivery issues detected in this answer."] if n >= cfg["min_words_for_rates"] \
            else ["Too short to assess pace and fillers."]
    else:
        msg = [m for _, m in flags]
    return [c for c, _ in flags], msg


# --------------------------------------------------------- per session
def analyze(tr, sid, cfg):
    ef.LONG_PAUSE = cfg["long_pause_s"]
    answers = []
    for u in build_units(tr):
        if u["t1"] - u["t0"] < 0.5:
            continue
        answers.append((u, ef.speech_features(u)))
    if not answers:
        raise ValueError("No candidate answers found in the transcript.")

    feats = pd.DataFrame([f for _, f in answers])
    words = int(feats.word_count.sum())
    speech_min = feats.speech_time_s.sum() / 60
    dur_min = feats.duration_s.sum() / 60
    lat = feats.response_latency_s.dropna().clip(lower=0)
    m = {
        "answers_analyzed": len(answers),
        "words_analyzed": words,
        "speaking_pace_wpm": words / speech_min if speech_min > 0 else None,
        "filler_rate": int(feats.filler_count.sum()) / words if words else None,
        "long_pauses_per_min": int(feats.long_pause_count.sum()) / dur_min if dur_min > 0 else None,
        "median_response_latency_s": float(lat.median()) if len(lat) else None,
        "median_words_per_answer": float(feats.word_count.median()),
    }

    comp = {}
    if m["speaking_pace_wpm"] is not None:
        comp["pace"] = score_band(m["speaking_pace_wpm"], cfg["pace_wpm"]["ideal"], cfg["pace_wpm"]["ok"])
    if m["filler_rate"] is not None:
        comp["fillers"] = score_lower(m["filler_rate"], cfg["filler_rate"]["good"], cfg["filler_rate"]["high"])
    if m["long_pauses_per_min"] is not None:
        comp["pauses"] = score_lower(m["long_pauses_per_min"], cfg["long_pauses_per_min"]["good"], cfg["long_pauses_per_min"]["high"])
    if m["median_response_latency_s"] is not None:
        comp["responsiveness"] = score_band(m["median_response_latency_s"], cfg["response_latency_s"]["ideal"], cfg["response_latency_s"]["ok"])
    comp["answer_detail"] = score_higher(m["median_words_per_answer"], cfg["answer_words"]["ideal"], cfg["answer_words"]["ok"])

    w = {k: cfg["weights"][k] for k in comp}
    overall = sum(comp[k] * w[k] for k in comp) / sum(w.values())

    # messages
    pace = m["speaking_pace_wpm"]
    p_lo, p_hi = cfg["pace_wpm"]["ideal"]
    good_msg = {
        "pace": f"Your overall speaking pace (about {pace:.0f} wpm) was comfortably within the target range." if pace else "",
        "fillers": f"You used few filler words ({(m['filler_rate'] or 0)*100:.1f}% of words).",
        "pauses": "Your answers flowed with few long pauses.",
        "responsiveness": "You began answering promptly after each question.",
        "answer_detail": f"Your answers had good detail (median {m['median_words_per_answer']:.0f} words).",
    }
    bad_msg, tip_key = {}, {}
    if pace:
        if pace > p_hi:
            bad_msg["pace"], tip_key["pace"] = f"You spoke faster than the target range ({pace:.0f} wpm vs {p_lo}-{p_hi}).", "pace_fast"
        else:
            bad_msg["pace"], tip_key["pace"] = f"You spoke slower than the target range ({pace:.0f} wpm vs {p_lo}-{p_hi}).", "pace_slow"
    bad_msg["fillers"] = f"Filler words made up {(m['filler_rate'] or 0)*100:.0f}% of your words."
    bad_msg["pauses"] = f"You had about {(m['long_pauses_per_min'] or 0):.1f} long pauses per minute."
    bad_msg["responsiveness"] = f"You took about {(m['median_response_latency_s'] or 0):.1f}s to start answering."
    bad_msg["answer_detail"] = f"Your answers were short (median {m['median_words_per_answer']:.0f} words)."
    for k in ("fillers", "pauses", "responsiveness", "answer_detail"):
        tip_key[k] = k

    strengths = [{"area": LABELS[k], "score": round(v), "message": good_msg[k]}
                 for k, v in sorted(comp.items(), key=lambda kv: -kv[1]) if v >= cfg["strength_min_score"]][:3]
    improve = [{"area": LABELS[k], "score": round(v), "message": bad_msg[k], "tip": TIPS[tip_key[k]]}
               for k, v in sorted(comp.items(), key=lambda kv: kv[1]) if v < cfg["improve_max_score"]][:3]
    plan = [i["tip"] for i in improve] or ["Keep practicing with new questions to maintain your current delivery."]

    questions = []
    for u, f in answers:
        flags, msgs = answer_feedback(f, cfg)
        questions.append({
            "question_id": u.get("question_id", u["unit_id"] + 1),
            "question_text": u["question"], "start_s": round(float(u["t0"]), 2), "end_s": round(float(u["t1"]), 2),
            "metrics": {k: f[k] for k in ("duration_s", "word_count", "wpm", "filler_count", "filler_rate",
                                           "long_pause_count", "response_latency_s")},
            "flags": flags, "feedback": msgs})

    notes = ["Scores are preliminary rule-based heuristics with unvalidated default targets.",
             "This report measures delivery (pace, fillers, pauses, response time, detail); it does not measure focus, confidence or interview quality."]
    if words < 100:
        notes.append("Very little speech was analyzed; treat these results cautiously.")

    return {
        "session_id": sid, "engine": "rule_based_v0", "status": "preliminary",
        "scores": {"delivery_overall": round(overall), **{k: round(v) for k, v in comp.items()}},
        "metrics": m,
        "targets": {"pace_wpm": cfg["pace_wpm"], "filler_rate": cfg["filler_rate"],
                    "long_pauses_per_min": cfg["long_pauses_per_min"],
                    "response_latency_s": cfg["response_latency_s"], "answer_words": cfg["answer_words"]},
        "strengths": strengths, "improvements": improve, "action_plan": plan,
        "questions": questions,
        "gaze": {"available": False, "note": "Add Tobii-based attention measures here when gaze data is connected."},
        "notes": notes,
    }


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else round(float(o), 3)
    return o


def merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transcript")
    ap.add_argument("--out", default="feedback.json")
    ap.add_argument("--thresholds", help="JSON file overriding any default thresholds")
    ap.add_argument("--write_default_thresholds", help="write the default thresholds to this file and exit")
    ap.add_argument("--session_id")
    a = ap.parse_args()

    if a.write_default_thresholds:
        Path(a.write_default_thresholds).write_text(json.dumps(DEFAULTS, indent=2))
        print(f"Wrote defaults to {a.write_default_thresholds}")
        return
    if not a.transcript:
        ap.error("--transcript is required")
    cfg = merge(DEFAULTS, json.loads(Path(a.thresholds).read_text())) if a.thresholds else DEFAULTS

    try:
        tr, sid = load_any(a.transcript, a.session_id)
        report = clean(analyze(tr, sid, cfg))
    except ValueError as e:
        sys.exit(str(e))
    Path(a.out).write_text(json.dumps(report, indent=2, ensure_ascii=False))

    s = report["scores"]
    print(f"Session {sid}: delivery {s['delivery_overall']}/100 "
          f"({', '.join(f'{k} {v}' for k, v in s.items() if k != 'delivery_overall')})")
    for title, key in (("Strengths", "strengths"), ("To improve", "improvements")):
        print(f"{title}:")
        for it in report[key] or [{"message": "-"}]:
            print("  -", it["message"])
    print(f"Full report -> {a.out}")


if __name__ == "__main__":
    main()
