import React, { useState } from "react";
import FeedbackSummary from "./FeedbackSummary";
import LiveInterviewRoom from "./LiveInterviewRoom";
import { saveTranscript, generateFeedback } from "./feedbackApi";

// Pre-packaged sample interview in case the user wants to test with 1-click
const SAMPLE_SEGMENTS = [
  { questionId: 1, speaker: "interviewer", startS: 0.0, endS: 3.5, text: "Tell me about yourself and your professional background." },
  { questionId: 1, speaker: "candidate", startS: 4.2, endS: 18.5, text: "I have over five years of experience in full-stack software development. I primarily work with modern web architectures, distributed systems, and real-time event streaming." },
  { questionId: 2, speaker: "interviewer", startS: 19.8, endS: 23.0, text: "How do you handle difficult technical disagreements in a team?" },
  { questionId: 2, speaker: "candidate", startS: 24.1, endS: 42.0, text: "I believe in bringing objective data to the discussion. Um, we usually set up quick proof-of-concept benchmarks, evaluate trade-offs together, and align on team delivery goals." },
  { questionId: 3, speaker: "interviewer", startS: 43.5, endS: 47.0, text: "What is your proudest engineering accomplishment?" },
  { questionId: 3, speaker: "candidate", startS: 48.0, endS: 70.0, text: "At my previous role, I re-architected the asynchronous data processing pipeline, which reduced end-to-end user latency by forty percent and lowered infrastructure costs significantly." }
];

export default function App() {
  const [activeTab, setActiveTab] = useState("interview"); // 'interview' | 'report'
  const [sessionId, setSessionId] = useState(1);
  const [loadingSample, setLoadingSample] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleInterviewCompleted = (completedSessionId) => {
    setRefreshKey((k) => k + 1);
    setActiveTab("report");
  };

  const handleLoadSample = async () => {
    setLoadingSample(true);
    try {
      await saveTranscript(sessionId, SAMPLE_SEGMENTS);
      await generateFeedback(sessionId);
      setRefreshKey((k) => k + 1);
      setActiveTab("report");
    } catch (err) {
      alert(`Spring Boot communication error: ${err.message}`);
    } finally {
      setLoadingSample(false);
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      backgroundColor: "#f1f5f9",
      color: "#0f172a",
      fontFamily: "'Plus Jakarta Sans', system-ui, -apple-system, sans-serif"
    }}>
      {/* Top Header Bar */}
      <header style={{
        backgroundColor: "#0f172a",
        color: "#ffffff",
        padding: "0.85rem 2rem",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexWrap: "wrap",
        gap: "1rem",
        boxShadow: "0 4px 12px rgba(0,0,0,0.15)"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <div style={{
            backgroundColor: "#2563eb",
            color: "#ffffff",
            width: "36px",
            height: "36px",
            borderRadius: "8px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 800,
            fontSize: "1.1rem"
          }}>
            AI
          </div>
          <div>
            <h1 style={{ fontSize: "1.15rem", fontWeight: 700, margin: 0, color: "#f8fafc" }}>
              AI Interview Platform
            </h1>
            <div style={{ fontSize: "0.78rem", color: "#94a3b8" }}>
              XGBoost Multimodal ML Grader (:8000) &bull; Spring Boot (:8080)
            </div>
          </div>
        </div>

        {/* Tab Controls & Session Selector */}
        <div style={{ display: "flex", alignItems: "center", gap: "1.25rem", flexWrap: "wrap" }}>
          <div style={{
            display: "flex",
            backgroundColor: "#1e293b",
            padding: "0.25rem",
            borderRadius: "8px",
            border: "1px solid #334155"
          }}>
            <button
              onClick={() => setActiveTab("interview")}
              style={{
                backgroundColor: activeTab === "interview" ? "#2563eb" : "transparent",
                color: activeTab === "interview" ? "#ffffff" : "#cbd5e1",
                border: "none",
                padding: "0.45rem 1rem",
                borderRadius: "6px",
                fontWeight: 600,
                fontSize: "0.88rem",
                cursor: "pointer",
                transition: "all 0.2s"
              }}
            >
              🎙️ Live Interview Room
            </button>
            <button
              onClick={() => setActiveTab("report")}
              style={{
                backgroundColor: activeTab === "report" ? "#2563eb" : "transparent",
                color: activeTab === "report" ? "#ffffff" : "#cbd5e1",
                border: "none",
                padding: "0.45rem 1rem",
                borderRadius: "6px",
                fontWeight: 600,
                fontSize: "0.88rem",
                cursor: "pointer",
                transition: "all 0.2s"
              }}
            >
              📊 Delivery Report
            </button>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>Session:</span>
            <input
              type="number"
              value={sessionId}
              onChange={(e) => setSessionId(Number(e.target.value))}
              style={{
                width: "55px",
                padding: "0.35rem 0.5rem",
                borderRadius: "6px",
                border: "1px solid #475569",
                backgroundColor: "#1e293b",
                color: "#ffffff",
                fontWeight: 600,
                fontSize: "0.9rem"
              }}
            />
          </div>

          <button
            onClick={handleLoadSample}
            disabled={loadingSample}
            style={{
              backgroundColor: "#334155",
              color: "#f8fafc",
              border: "1px solid #475569",
              padding: "0.45rem 0.85rem",
              borderRadius: "6px",
              fontWeight: 500,
              fontSize: "0.82rem",
              cursor: loadingSample ? "not-allowed" : "pointer"
            }}
            title="Load demo data from DAIC-WOZ sample"
          >
            {loadingSample ? "Loading..." : "Load Demo Report"}
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main style={{ padding: "2.5rem 1.5rem" }}>
        {activeTab === "interview" ? (
          <LiveInterviewRoom
            sessionId={sessionId}
            onInterviewCompleted={handleInterviewCompleted}
          />
        ) : (
          <FeedbackSummary
            key={`${sessionId}-${refreshKey}`}
            sessionId={sessionId}
          />
        )}
      </main>
    </div>
  );
}
