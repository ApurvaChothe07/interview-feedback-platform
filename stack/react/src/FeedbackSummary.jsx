import { useEffect, useState } from "react";
import { generateFeedback, getFeedback } from "./feedbackApi";
import "./FeedbackSummary.css";

// Pass the interview session id: <FeedbackSummary sessionId={42} />
// The page loads the stored report; if none exists yet it asks the backend to create one.

const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const lower = (s) => s.charAt(0).toLowerCase() + s.slice(1);

function joinList(items) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

// Each row on the "Your measurements" ruler: where the candidate landed vs. the target band.
function buildRows(report) {
  const m = report.metrics || {};
  const t = report.targets || {};
  const s = report.scores || {};
  const rows = [];

  if (m.speaking_pace_wpm != null && t.pace_wpm) {
    rows.push({
      key: "pace", area: "Speaking pace", score: s.pace,
      value: m.speaking_pace_wpm, shown: `${Math.round(m.speaking_pace_wpm)} wpm`,
      min: 60, max: 240, band: t.pace_wpm.ideal,
      target: `Target ${t.pace_wpm.ideal[0]} to ${t.pace_wpm.ideal[1]} wpm`,
    });
  }
  if (m.filler_rate != null && t.filler_rate) {
    rows.push({
      key: "fillers", area: "Filler words", score: s.fillers,
      value: m.filler_rate * 100, shown: `${(m.filler_rate * 100).toFixed(1)}% of words`,
      min: 0, max: 15, band: [0, t.filler_rate.good * 100],
      target: `Target under ${(t.filler_rate.good * 100).toFixed(0)}% of words`,
    });
  }
  if (m.long_pauses_per_min != null && t.long_pauses_per_min) {
    rows.push({
      key: "pauses", area: "Pauses", score: s.pauses,
      value: m.long_pauses_per_min, shown: `${m.long_pauses_per_min.toFixed(1)} long pauses a minute`,
      min: 0, max: 10, band: [0, t.long_pauses_per_min.good],
      target: `Target under ${t.long_pauses_per_min.good} a minute`,
    });
  }
  if (m.median_response_latency_s != null && t.response_latency_s) {
    rows.push({
      key: "responsiveness", area: "Response time", score: s.responsiveness,
      value: m.median_response_latency_s, shown: `${m.median_response_latency_s.toFixed(1)} s to start`,
      min: 0, max: 6, band: t.response_latency_s.ideal,
      target: `Target within ${t.response_latency_s.ideal[1]} s`,
    });
  }
  if (m.median_words_per_answer != null && t.answer_words) {
    rows.push({
      key: "answer_detail", area: "Answer detail", score: s.answer_detail,
      value: m.median_words_per_answer, shown: `${Math.round(m.median_words_per_answer)} words per answer`,
      min: 0, max: 60, band: [t.answer_words.ideal, 60],
      target: `Target ${t.answer_words.ideal}+ words`,
    });
  }
  return rows;
}

function Ruler({ row }) {
  const pos = (v) => clamp(((v - row.min) / (row.max - row.min)) * 100, 0, 100);
  const left = pos(row.band[0]);
  const width = pos(row.band[1]) - left;
  const inRange = row.score >= 75;
  return (
    <div
      className="fs-ruler"
      role="img"
      aria-label={`${row.area}: ${row.shown}. ${row.target}.`}
    >
      <span className="fs-band" style={{ left: `${left}%`, width: `${width}%` }} />
      <span
        className={`fs-marker ${inRange ? "fs-marker-ok" : "fs-marker-off"}`}
        style={{ left: `${pos(row.value)}%` }}
      />
    </div>
  );
}

function Measurements({ rows, messages }) {
  if (!rows.length) return null;
  return (
    <section className="fs-section" aria-labelledby="fs-h-measure">
      <h2 id="fs-h-measure">Your measurements</h2>
      <p className="fs-hint">The shaded stretch on each line is the target range. The dot is where you landed.</p>
      <ul className="fs-rows">
        {rows.map((row) => (
          <li key={row.key} className="fs-row">
            <div className="fs-row-name">
              <span className="fs-row-area">{row.area}</span>
              <span className="fs-row-value">{row.shown}</span>
            </div>
            <Ruler row={row} />
            <p className="fs-row-target">{row.target}</p>
            {messages[row.area] && <p className="fs-row-msg">{messages[row.area]}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ActionPlan({ items }) {
  const [done, setDone] = useState({});
  if (!items || !items.length) return null;
  return (
    <section className="fs-section" aria-labelledby="fs-h-plan">
      <h2 id="fs-h-plan">Practice plan</h2>
      <ul className="fs-plan">
        {items.map((text, i) => (
          <li key={i}>
            <label className={done[i] ? "fs-done" : ""}>
              <input
                type="checkbox"
                checked={!!done[i]}
                onChange={() => setDone((d) => ({ ...d, [i]: !d[i] }))}
              />
              <span>{text}</span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Questions({ questions }) {
  if (!questions || !questions.length) return null;
  return (
    <section className="fs-section" aria-labelledby="fs-h-q">
      <h2 id="fs-h-q">Question by question</h2>
      <div className="fs-questions">
        {questions.map((q) => {
          const issues = q.flags ? q.flags.length : 0;
          const m = q.metrics || {};
          return (
            <details key={q.question_id} className="fs-q">
              <summary>
                <span className="fs-q-text">{q.question_text || `Question ${q.question_id}`}</span>
                <span className={`fs-q-badge ${issues ? "fs-q-badge-note" : ""}`}>
                  {issues ? `${issues} to work on` : "No issues"}
                </span>
              </summary>
              <ul className="fs-q-feedback">
                {q.feedback.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
              <p className="fs-q-meta">
                {m.word_count} words in {Number(m.duration_s).toFixed(0)} s
                {m.wpm != null ? `, ${Math.round(m.wpm)} wpm` : ""}
              </p>
            </details>
          );
        })}
      </div>
    </section>
  );
}

export default function FeedbackSummary({ sessionId }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setReport(null);
    setError("");
    (async () => {
      try {
        let data;
        try {
          data = await getFeedback(sessionId);
        } catch (e) {
          if (e.status !== 404) throw e;
          data = await generateFeedback(sessionId); // first visit: create the report
        }
        if (!cancelled) setReport(data);
      } catch (e) {
        if (!cancelled) setError(e.message || "Something went wrong.");
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId, attempt]);

  if (error) {
    return (
      <main className="fs fs-state">
        <h1 className="fs-hero">We couldn't load your feedback.</h1>
        <p className="fs-sub">{error}</p>
        <button className="fs-button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
      </main>
    );
  }
  if (!report) {
    return (
      <main className="fs fs-state" aria-busy="true">
        <p className="fs-sub">Preparing your feedback...</p>
      </main>
    );
  }

  const strengths = report.strengths || [];
  const improvements = report.improvements || [];
  const messages = {};
  [...strengths, ...improvements].forEach((i) => { messages[i.area] = i.message; });

  const hero = improvements.length
    ? `Next, work on ${joinList(improvements.map((i) => lower(i.area)))}.`
    : "Your delivery stayed in range throughout.";
  const sub = strengths.length
    ? `You did well on ${joinList(strengths.map((s) => lower(s.area)))}.`
    : "";

  return (
    <main className="fs">
      <header className="fs-head">
        <h1 className="fs-hero">{hero}</h1>
        {sub && <p className="fs-sub">{sub}</p>}
        <p className="fs-score">
          Delivery score <strong>{report.scores.delivery_overall}</strong> out of 100. This is a
          preliminary score from pace, filler words, pauses, response time and answer detail.
        </p>
      </header>

      <Measurements rows={buildRows(report)} messages={messages} />

      {improvements.length > 0 && (
        <section className="fs-section" aria-labelledby="fs-h-improve">
          <h2 id="fs-h-improve">What to work on</h2>
          <ul className="fs-list">
            {improvements.map((i) => (
              <li key={i.area}>
                <p className="fs-list-main">{i.message}</p>
                <p className="fs-list-tip">{i.tip}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {strengths.length > 0 && (
        <section className="fs-section" aria-labelledby="fs-h-strong">
          <h2 id="fs-h-strong">What went well</h2>
          <ul className="fs-list">
            {strengths.map((s) => (
              <li key={s.area}><p className="fs-list-main">{s.message}</p></li>
            ))}
          </ul>
        </section>
      )}

      <ActionPlan items={report.action_plan} />
      <Questions questions={report.questions} />

      {report.notes && report.notes.length > 0 && (
        <footer className="fs-notes">
          {report.notes.map((n, i) => <p key={i}>{n}</p>)}
        </footer>
      )}
    </main>
  );
}
