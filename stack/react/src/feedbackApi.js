// Change this to wherever your Spring Boot app runs.
export const API_BASE = "http://localhost:8080";

async function request(path, options) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body && body.message) message = body.message;
    } catch (_) {
      /* response had no JSON body */
    }
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/**
 * Call once when the interview ends.
 * segments: [{ questionId, speaker: "interviewer" | "candidate", startS, endS, text }]
 * startS / endS are seconds from the start of the interview, on one shared clock.
 */
export function saveTranscript(sessionId, segments) {
  return request(`/api/sessions/${sessionId}/transcript`, {
    method: "POST",
    body: JSON.stringify(segments),
  });
}

/** Analyze the saved transcript and store the report. */
export function generateFeedback(sessionId) {
  return request(`/api/sessions/${sessionId}/feedback`, { method: "POST" });
}

/** Read the latest stored report. Rejects with err.status === 404 if none exists yet. */
export function getFeedback(sessionId) {
  return request(`/api/sessions/${sessionId}/feedback`, { method: "GET" });
}
