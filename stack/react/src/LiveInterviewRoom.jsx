import React, { useState, useRef, useEffect } from "react";
import { saveTranscript, generateFeedback } from "./feedbackApi";

const DEFAULT_QUESTIONS = [
  {
    id: 1,
    text: "Tell me about yourself, your background, and what you are passionate about.",
    sampleAnswer: "I have over four years of experience in software engineering, primarily focused on building scalable full-stack applications. I enjoy working on distributed architectures and real-time systems, and I love taking complex engineering problems and turning them into intuitive user experiences."
  },
  {
    id: 2,
    text: "Can you describe a complex or challenging project you worked on recently and how you approached it?",
    sampleAnswer: "In my recent role, our backend data processing pipeline was experiencing significant bottlenecks during peak traffic. I led the refactoring of our synchronous batch processing into an asynchronous event-driven queue, which reduced processing latency by over forty percent and increased system stability."
  },
  {
    id: 3,
    text: "How do you handle technical disagreements or differing opinions with teammates?",
    sampleAnswer: "I always approach technical disagreements with empathy and focus on data. Instead of debating in the abstract, I encourage setting up quick benchmarks or proof-of-concept tests to compare trade-offs objectively, ensuring our decisions align with user requirements and delivery timelines."
  },
  {
    id: 4,
    text: "What is a major professional accomplishment you are proud of, and what was your contribution?",
    sampleAnswer: "I spearheaded the automated testing and continuous deployment overhaul for our team's core services. This improved deployment frequency from bi-weekly releases to multiple safe releases per day, while cutting production bug incidents by more than half."
  },
  {
    id: 5,
    text: "Where do you see your career heading in the next few years, and what skills are you looking to grow?",
    sampleAnswer: "Over the next few years, I want to deepen my expertise in cloud architecture and machine learning systems while growing into a technical leadership role where I can mentor junior engineers and help guide architectural decisions."
  }
];

export default function LiveInterviewRoom({ sessionId, onInterviewCompleted }) {
  const [currentQIndex, setCurrentQIndex] = useState(0);
  const [isInterviewActive, setIsInterviewActive] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [micVolume, setMicVolume] = useState(0);
  const [hasMicHardware, setHasMicHardware] = useState(true);
  const [currentAnswerText, setCurrentAnswerText] = useState("");
  const [interimText, setInterimText] = useState("");
  const [segments, setSegments] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [isSpeakingQuestion, setIsSpeakingQuestion] = useState(false);
  const [noticeMessage, setNoticeMessage] = useState("");

  const interviewStartTimeRef = useRef(null);
  const speechStartTimeRef = useRef(null);
  const isRecordingRef = useRef(false);
  const recognitionRef = useRef(null);
  const audioContextRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const animFrameRef = useRef(null);

  // Time in seconds from shared clock
  const getInterviewTimeS = () => {
    if (!interviewStartTimeRef.current) return 0.0;
    return Number(((performance.now() - interviewStartTimeRef.current) / 1000).toFixed(2));
  };

  // Detect whether an audio input device (mic) actually exists on this system
  useEffect(() => {
    async function checkDevices() {
      if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          const hasInput = devices.some((d) => d.kind === "audioinput");
          setHasMicHardware(hasInput);
          if (!hasInput) {
            setNoticeMessage(
              "No microphone hardware was detected on this PC (e.g. Remote Desktop / VM). You can type responses or use 'Auto-Fill Sample' to test the XGBoost grader seamlessly."
            );
          }
        } catch (_) {
          // Keep default
        }
      }
    }
    checkDevices();

    return () => {
      stopMicAndRecognition();
    };
  }, []);

  const stopMicAndRecognition = () => {
    isRecordingRef.current = false;
    setIsRecording(false);
    setMicVolume(0);

    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    if (audioContextRef.current) {
      try { audioContextRef.current.close(); } catch (_) {}
      audioContextRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch (_) {}
      recognitionRef.current = null;
    }
  };

  const speakQuestion = (text) => {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 0.95;
      utterance.onstart = () => setIsSpeakingQuestion(true);
      utterance.onend = () => setIsSpeakingQuestion(false);
      utterance.onerror = () => setIsSpeakingQuestion(false);
      window.speechSynthesis.speak(utterance);
    }
  };

  const handleStartInterview = () => {
    interviewStartTimeRef.current = performance.now();
    setIsInterviewActive(true);
    setCurrentQIndex(0);
    setSegments([]);
    setCurrentAnswerText("");
    setInterimText("");
    setStatusMessage("Interview started! Enter your answer below or use a sample response.");

    const q = DEFAULT_QUESTIONS[0];
    setSegments([
      {
        questionId: q.id,
        speaker: "interviewer",
        startS: 0.0,
        endS: 3.5,
        text: q.text
      }
    ]);

    speakQuestion(q.text);
  };

  const handleStartRecording = async () => {
    setNoticeMessage("");
    setStatusMessage("Activating microphone...");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioCtx();
      audioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const updateVolume = () => {
        if (!isRecordingRef.current) return;
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) sum += dataArray[i];
        const avg = sum / bufferLength;
        setMicVolume(Math.min(100, Math.round((avg / 128) * 100)));
        animFrameRef.current = requestAnimationFrame(updateVolume);
      };

      isRecordingRef.current = true;
      setIsRecording(true);
      speechStartTimeRef.current = getInterviewTimeS();
      updateVolume();

      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = "en-US";

        recognition.onresult = (event) => {
          let finalTranscript = "";
          let interim = "";
          for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript + " ";
            else interim += event.results[i][0].transcript;
          }
          if (finalTranscript) {
            setCurrentAnswerText((prev) => (prev ? prev + " " + finalTranscript.trim() : finalTranscript.trim()));
          }
          setInterimText(interim);
        };

        recognition.onerror = (e) => {
          if (e.error !== "no-speech") console.warn("Speech error:", e.error);
        };

        recognition.onend = () => {
          if (isRecordingRef.current) {
            try { recognition.start(); } catch (_) {}
          }
        };

        recognitionRef.current = recognition;
        recognition.start();
      }
      setStatusMessage("Microphone active! Speak now.");
    } catch (err) {
      console.warn("getUserMedia failed:", err.name, err.message);
      setHasMicHardware(false);
      setNoticeMessage(
        "No audio input device is available on this system (Remote Desktop / VM). You can type your response or click 'Auto-Fill Sample Answer' below."
      );
      setIsRecording(false);
      isRecordingRef.current = false;
    }
  };

  const handleStopRecording = () => {
    stopMicAndRecognition();
    setStatusMessage("Microphone paused.");
  };

  // Populate realistic sample response for testing
  const handleAutoFillSample = () => {
    const q = DEFAULT_QUESTIONS[currentQIndex];
    setCurrentAnswerText(q.sampleAnswer);
    setInterimText("");
    speechStartTimeRef.current = getInterviewTimeS();
    setStatusMessage("Sample answer loaded! Review and click 'Save Answer & Next Question'.");
  };

  // Save current answer and advance to next question
  const handleNextQuestion = () => {
    const finalAnswer = (currentAnswerText + (interimText ? " " + interimText : "")).trim();

    if (!finalAnswer) {
      alert("Please enter or speak an answer before proceeding.");
      return;
    }

    stopMicAndRecognition();

    const q = DEFAULT_QUESTIONS[currentQIndex];
    const wordCount = finalAnswer.split(/\s+/).filter(Boolean).length;
    // Calculate realistic speaking duration: average pace ~140 WPM (2.3 words/sec)
    const simulatedDurationS = Number(Math.max(4.0, (wordCount / 2.3)).toFixed(2));

    const speechStart = speechStartTimeRef.current || Math.max(0.0, getInterviewTimeS() - simulatedDurationS);
    const speechEnd = Math.max(getInterviewTimeS(), speechStart + simulatedDurationS);

    const candidateSegment = {
      questionId: q.id,
      speaker: "candidate",
      startS: Number(speechStart.toFixed(2)),
      endS: Number(speechEnd.toFixed(2)),
      text: finalAnswer
    };

    const newSegments = [...segments, candidateSegment];

    setCurrentAnswerText("");
    setInterimText("");
    speechStartTimeRef.current = null;

    if (currentQIndex + 1 < DEFAULT_QUESTIONS.length) {
      const nextIndex = currentQIndex + 1;
      const nextQ = DEFAULT_QUESTIONS[nextIndex];
      const qStart = Number(speechEnd.toFixed(2));
      const qEnd = Number((qStart + 3.0).toFixed(2));

      newSegments.push({
        questionId: nextQ.id,
        speaker: "interviewer",
        startS: qStart,
        endS: qEnd,
        text: nextQ.text
      });

      setSegments(newSegments);
      setCurrentQIndex(nextIndex);
      speakQuestion(nextQ.text);
      setStatusMessage(`Question ${nextIndex + 1} of ${DEFAULT_QUESTIONS.length}`);
    } else {
      setSegments(newSegments);
      setIsInterviewActive(false);
      setStatusMessage("All 5 questions completed! Click 'View AI Delivery Report' to run the XGBoost evaluation.");
    }
  };

  // Send segments to Spring Boot -> Python XGBoost service
  const handleFinishAndGrade = async () => {
    if (segments.length === 0) {
      alert("No transcript recorded yet.");
      return;
    }

    setSubmitting(true);
    setStatusMessage("Sending transcript to Spring Boot (:8080)...");

    try {
      await saveTranscript(sessionId, segments);
      setStatusMessage("Evaluating with XGBoost Multimodal ML Model (:8000)...");
      await generateFeedback(sessionId);
      setStatusMessage("Evaluation complete! Opening report...");
      if (onInterviewCompleted) {
        onInterviewCompleted(sessionId);
      }
    } catch (err) {
      setStatusMessage(`Error: ${err.message}. Check that Spring Boot (:8080) and Python (:8000) are running.`);
    } finally {
      setSubmitting(false);
    }
  };

  const currentQ = DEFAULT_QUESTIONS[currentQIndex];
  const candidateAnswers = segments.filter((s) => s.speaker === "candidate");

  return (
    <div style={{
      maxWidth: "52rem",
      margin: "0 auto",
      backgroundColor: "#ffffff",
      borderRadius: "16px",
      padding: "2.5rem",
      boxShadow: "0 10px 30px rgba(0,0,0,0.06)",
      border: "1px solid #e2e8f0",
      color: "#0f172a"
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 700, color: "#0f172a" }}>
            Live Interactive Interview Room
          </h2>
          <p style={{ margin: "0.25rem 0 0", color: "#64748b", fontSize: "0.95rem" }}>
            Answer 5 questions. Pacing, latency, and detail are graded by the trained XGBoost model.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span style={{
            backgroundColor: isRecording ? "#fef2f2" : "#f1f5f9",
            color: isRecording ? "#dc2626" : "#475569",
            padding: "0.4rem 0.9rem",
            borderRadius: "999px",
            fontWeight: 600,
            fontSize: "0.85rem",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            border: isRecording ? "1px solid #fecaca" : "1px solid #e2e8f0"
          }}>
            <span style={{
              width: "10px",
              height: "10px",
              borderRadius: "50%",
              backgroundColor: isRecording ? "#dc2626" : hasMicHardware ? "#94a3b8" : "#f59e0b",
              display: "inline-block"
            }} />
            {isRecording ? "MIC RECORDING" : hasMicHardware ? `Q ${currentQIndex + 1} / 5` : "TYPING MODE"}
          </span>
        </div>
      </div>

      {/* Notice Banner */}
      {noticeMessage && (
        <div style={{
          backgroundColor: "#fffbeb",
          border: "1px solid #fde68a",
          padding: "0.85rem 1.1rem",
          borderRadius: "8px",
          color: "#92400e",
          marginBottom: "1.5rem",
          fontSize: "0.9rem",
          lineHeight: 1.5
        }}>
          💡 <strong>Notice:</strong> {noticeMessage}
        </div>
      )}

      {/* Initial Start Screen */}
      {!isInterviewActive && segments.length === 0 && (
        <div style={{ textAlign: "center", padding: "3rem 1.5rem", backgroundColor: "#f8fafc", borderRadius: "12px", border: "2px dashed #cbd5e1" }}>
          <div style={{ fontSize: "3.5rem", marginBottom: "1rem" }}>🎙️</div>
          <h3 style={{ margin: "0 0 0.5rem", color: "#0f172a", fontSize: "1.3rem", fontWeight: 700 }}>
            Ready for Your Practice Interview?
          </h3>
          <p style={{ color: "#64748b", maxWidth: "480px", margin: "0 auto 1.5rem", fontSize: "0.95rem", lineHeight: 1.5 }}>
            You will answer 5 interview questions. You can speak into your microphone or type your answers. When complete, our XGBoost ML model evaluates your performance.
          </p>
          <button
            onClick={handleStartInterview}
            style={{
              backgroundColor: "#2563eb",
              color: "#ffffff",
              border: "none",
              padding: "0.85rem 2.2rem",
              borderRadius: "8px",
              fontWeight: 700,
              fontSize: "1rem",
              cursor: "pointer",
              boxShadow: "0 4px 14px rgba(37,99,235,0.35)"
            }}
          >
            Start Live Interview Now
          </button>
        </div>
      )}

      {/* Active Question Screen */}
      {isInterviewActive && (
        <div>
          {/* Question Display Card */}
          <div style={{
            backgroundColor: "#f8fafc",
            border: "1px solid #e2e8f0",
            borderRadius: "12px",
            padding: "1.5rem",
            marginBottom: "1.5rem"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
              <span style={{ fontSize: "0.82rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "#2563eb" }}>
                Question {currentQIndex + 1} of {DEFAULT_QUESTIONS.length}
              </span>
              <button
                onClick={() => speakQuestion(currentQ.text)}
                style={{
                  background: "#ffffff",
                  border: "1px solid #cbd5e1",
                  borderRadius: "6px",
                  padding: "0.3rem 0.75rem",
                  fontSize: "0.82rem",
                  cursor: "pointer",
                  color: "#334155",
                  fontWeight: 500
                }}
              >
                🔊 {isSpeakingQuestion ? "Speaking..." : "Read Aloud"}
              </button>
            </div>
            <h3 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "#0f172a", lineHeight: 1.45 }}>
              {currentQ.text}
            </h3>
          </div>

          {/* Live Mic Volume Level Indicator */}
          {isRecording && (
            <div style={{
              display: "flex",
              alignItems: "center",
              gap: "0.75rem",
              marginBottom: "1rem",
              padding: "0.6rem 1rem",
              backgroundColor: "#f0fdf4",
              borderRadius: "8px",
              border: "1px solid #bbf7d0"
            }}>
              <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "#166534" }}>
                🎙️ Mic Input:
              </span>
              <div style={{ flex: 1, height: "10px", backgroundColor: "#dcfce7", borderRadius: "999px", overflow: "hidden" }}>
                <div style={{
                  width: `${Math.max(8, micVolume)}%`,
                  height: "100%",
                  backgroundColor: micVolume > 60 ? "#ef4444" : "#16a34a",
                  transition: "width 0.1s ease-out"
                }} />
              </div>
              <span style={{ fontSize: "0.82rem", color: "#15803d" }}>
                {micVolume > 15 ? "Speaking detected" : "Listening..."}
              </span>
            </div>
          )}

          {/* Response Box */}
          <div style={{ marginBottom: "1.5rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
              <label style={{ fontWeight: 700, fontSize: "0.95rem", color: "#1e293b" }}>
                Your Answer:
              </label>
              <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
                <span style={{ fontSize: "0.85rem", color: "#64748b" }}>
                  Words: {((currentAnswerText + " " + interimText).trim().split(/\s+/).filter(Boolean)).length}
                </span>
                <button
                  type="button"
                  onClick={handleAutoFillSample}
                  style={{
                    background: "#eff6ff",
                    border: "1px solid #bfdbfe",
                    borderRadius: "6px",
                    padding: "0.25rem 0.65rem",
                    fontSize: "0.8rem",
                    color: "#2563eb",
                    fontWeight: 600,
                    cursor: "pointer"
                  }}
                  title="Fills in a realistic practice answer for this question"
                >
                  ⚡ Auto-Fill Sample Answer
                </button>
              </div>
            </div>

            <textarea
              rows={6}
              value={currentAnswerText + (interimText ? " " + interimText : "")}
              onChange={(e) => {
                setCurrentAnswerText(e.target.value);
                setInterimText("");
              }}
              placeholder="Type your response here, or click 'Start Answering (Mic ON)' if a microphone is connected..."
              style={{
                width: "100%",
                boxSizing: "border-box",
                padding: "1rem",
                borderRadius: "10px",
                border: isRecording ? "2px solid #ef4444" : "1px solid #cbd5e1",
                fontSize: "1rem",
                lineHeight: "1.6",
                color: "#0f172a",
                backgroundColor: isRecording ? "#fffdfd" : "#ffffff",
                resize: "vertical",
                fontFamily: "inherit"
              }}
            />
          </div>

          {/* Action Buttons */}
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
            {hasMicHardware && (
              !isRecording ? (
                <button
                  onClick={handleStartRecording}
                  style={{
                    backgroundColor: "#dc2626",
                    color: "#ffffff",
                    border: "none",
                    padding: "0.75rem 1.5rem",
                    borderRadius: "8px",
                    fontWeight: 700,
                    fontSize: "0.95rem",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    boxShadow: "0 3px 12px rgba(220,38,38,0.3)"
                  }}
                >
                  🎙️ Start Answering (Mic ON)
                </button>
              ) : (
                <button
                  onClick={handleStopRecording}
                  style={{
                    backgroundColor: "#475569",
                    color: "#ffffff",
                    border: "none",
                    padding: "0.75rem 1.5rem",
                    borderRadius: "8px",
                    fontWeight: 700,
                    fontSize: "0.95rem",
                    cursor: "pointer"
                  }}
                >
                  ⏹️ Pause Microphone
                </button>
              )
            )}

            <button
              onClick={handleNextQuestion}
              style={{
                backgroundColor: "#2563eb",
                color: "#ffffff",
                border: "none",
                padding: "0.75rem 1.6rem",
                borderRadius: "8px",
                fontWeight: 700,
                fontSize: "0.95rem",
                cursor: "pointer",
                boxShadow: "0 3px 12px rgba(37,99,235,0.25)"
              }}
            >
              {currentQIndex + 1 < DEFAULT_QUESTIONS.length ? "Save Answer & Next Question ➔" : "Save Final Answer ➔"}
            </button>
          </div>
        </div>
      )}

      {/* When All Questions Completed */}
      {!isInterviewActive && segments.length > 0 && (
        <div style={{ textAlign: "center", padding: "2.5rem 1.5rem", backgroundColor: "#f0fdf4", borderRadius: "12px", border: "1px solid #bbf7d0" }}>
          <div style={{ fontSize: "3rem", marginBottom: "0.5rem" }}>🎉</div>
          <h3 style={{ margin: "0 0 0.5rem", color: "#166534", fontSize: "1.35rem", fontWeight: 700 }}>
            Interview Successfully Completed!
          </h3>
          <p style={{ color: "#15803d", margin: "0 0 1.5rem", fontSize: "0.95rem" }}>
            Recorded <strong>{candidateAnswers.length}</strong> answers. Ready to run XGBoost evaluation.
          </p>
          <div style={{ display: "flex", justifyContent: "center", gap: "1rem", flexWrap: "wrap" }}>
            <button
              onClick={handleFinishAndGrade}
              disabled={submitting}
              style={{
                backgroundColor: "#16a34a",
                color: "#ffffff",
                border: "none",
                padding: "0.85rem 2.2rem",
                borderRadius: "8px",
                fontWeight: 700,
                fontSize: "1rem",
                cursor: submitting ? "not-allowed" : "pointer",
                boxShadow: "0 4px 14px rgba(22,163,74,0.35)"
              }}
            >
              {submitting ? "Evaluating with ML..." : "View AI Delivery Report ➔"}
            </button>

            <button
              onClick={handleStartInterview}
              style={{
                backgroundColor: "#ffffff",
                color: "#475569",
                border: "1px solid #cbd5e1",
                padding: "0.85rem 1.5rem",
                borderRadius: "8px",
                fontWeight: 600,
                fontSize: "0.95rem",
                cursor: "pointer"
              }}
            >
              Start Over
            </button>
          </div>
        </div>
      )}

      {/* Answered Questions Progress Summary */}
      {candidateAnswers.length > 0 && (
        <div style={{ marginTop: "2rem", borderTop: "1px solid #e2e8f0", paddingTop: "1.5rem" }}>
          <h4 style={{ margin: "0 0 0.85rem", fontSize: "0.95rem", color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Recorded Responses ({candidateAnswers.length} / 5)
          </h4>
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {candidateAnswers.map((ans, idx) => (
              <div key={idx} style={{
                padding: "0.6rem 0.9rem",
                backgroundColor: "#f8fafc",
                borderRadius: "8px",
                border: "1px solid #e2e8f0",
                display: "flex",
                justifyContent: "space-between",
                fontSize: "0.88rem"
              }}>
                <span style={{ fontWeight: 600, color: "#0f172a" }}>
                  Q{ans.questionId}: {ans.text.length > 60 ? ans.text.slice(0, 60) + "..." : ans.text}
                </span>
                <span style={{ color: "#16a34a", fontWeight: 600 }}>
                  ✓ Saved ({ans.text.split(/\s+/).filter(Boolean).length} words, {(ans.endS - ans.startS).toFixed(1)}s)
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Status Bar */}
      {statusMessage && (
        <div style={{ marginTop: "1.5rem", padding: "0.75rem 1rem", backgroundColor: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0", fontSize: "0.88rem", color: "#475569" }}>
          ℹ️ {statusMessage}
        </div>
      )}
    </div>
  );
}
