# Interview feedback: setup guide

Flow: **React** (interview + `/summary` page) → **Spring Boot** (stores data, port 8080) → **Python feedback service** (port 8000) → report JSON stored in **MySQL** → shown in React.

```
python-service/   feedback_service.py + interview_feedback.py + extract_features.py
database/         schema.sql
spring-boot/      Java files to copy into your project + application.properties.example
react/            feedbackApi.js, FeedbackSummary.jsx, FeedbackSummary.css
samples/          ready-made test payloads (from DAIC-WOZ session 300)
```

**What has been tested:** the Python service (run end to end on session 300). The Java and React files were written for Spring Boot 3 / Java 17 and React 18 but were not compiled or run in my environment, so the first run may need small fixes (package names, versions). If something fails, send me the error text.

You need: Python 3.10+, Java 17+, MySQL 8, Node 18+.

---

## Step 1: Run the Python feedback service

```bash
cd python-service
python -m venv .venv
# Windows: .venv\Scripts\activate      Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python feedback_service.py
```

Leave it running. In a second terminal, check it:

```bash
curl http://localhost:8000/health
# {"engine":"rule_based_v0","status":"ok"}

curl -X POST http://localhost:8000/analyze -H "Content-Type: application/json" \
     -d @../samples/sample_analyze_request.json
```

You should get a JSON report with `scores`, `strengths`, `improvements` and `questions`. (On Windows PowerShell use `curl.exe` instead of `curl`.)

## Step 2: Set up MySQL

Either run the SQL file:

```bash
mysql -u root -p < database/schema.sql
```

or skip this and let Spring Boot create the tables for you (`ddl-auto=update`, set in Step 3).

## Step 3: Add the backend to your Spring Boot project

1. Copy the folders inside `spring-boot/src/main/java/com/example/interviewfeedback/` (`model`, `repository`, `dto`, `service`, `controller`, `config`) into your project.
2. **Package name:** your project has its own base package (for example `com.myteam.interview`). Rename `com.example.interviewfeedback` in the copied files, and place them under your base package. Spring only finds them if they sit under the package of your `@SpringBootApplication` class.
3. Add the three dependencies listed at the bottom of `application.properties.example` to your `pom.xml` (or Gradle file), if you don't already have them.
4. Add the lines from `application.properties.example` to your `application.properties`, using your own MySQL user and password.
5. Start the app. It listens on `http://localhost:8080`.

Test the three endpoints (the Python service from Step 1 must still be running):

```bash
# 1. save a transcript for session 1
curl -X POST http://localhost:8080/api/sessions/1/transcript \
     -H "Content-Type: application/json" -d @samples/sample_segments.json

# 2. create the feedback report
curl -X POST http://localhost:8080/api/sessions/1/feedback

# 3. read it back
curl http://localhost:8080/api/sessions/1/feedback
```

Check MySQL: `SELECT session_id, delivery_score, created_at FROM feedback_report;`

Notes: if your project uses Spring Boot 2 or Java 8/11, change `jakarta.persistence` to `javax.persistence` and replace the `record` in `SegmentDto` with a normal class.

## Step 4: Add the frontend

1. Copy the three files in `react/` into your `src/` (for example `src/feedback/`).
2. Open `feedbackApi.js` and set `API_BASE` if your backend is not on `http://localhost:8080`.
3. Add a route for the summary page. With React Router:

```jsx
import { useParams } from "react-router-dom";
import FeedbackSummary from "./feedback/FeedbackSummary";

function SummaryPage() {
  const { sessionId } = useParams();
  return <FeedbackSummary sessionId={sessionId} />;
}
// <Route path="/summary/:sessionId" element={<SummaryPage />} />
```

4. Optional: add the Google Fonts `<link>` from the top of `FeedbackSummary.css` to `public/index.html` (or `index.html` in Vite).

Open `http://localhost:3000/summary/1` (or port 5173). Session 1 now has the sample data from Step 3, so you should see the full page.

## Step 5: Send real transcripts from your interview flow

During the interview, collect segments with times measured from the start of the interview (one shared clock), then send them when it ends. Example using the browser's speech recognition; adapt it to whatever speech-to-text you already use:

```jsx
import { saveTranscript, generateFeedback } from "./feedback/feedbackApi";

const startedAt = useRef(performance.now());
const segments = useRef([]);
const now = () => (performance.now() - startedAt.current) / 1000;
let speechStart = null;

// When a question is shown or read out:
const qStart = now();
// ...after it finishes:
segments.current.push({ questionId, speaker: "interviewer", startS: qStart, endS: now(), text: questionText });

// Speech recognition callbacks:
recognition.onspeechstart = () => { speechStart = now(); };
recognition.onresult = (e) => {
  const r = e.results[e.results.length - 1];
  if (!r.isFinal) return;
  segments.current.push({
    questionId, speaker: "candidate",
    startS: speechStart ?? now(), endS: now(), text: r[0].transcript.trim(),
  });
  speechStart = null;
};

// When the interview ends:
await saveTranscript(sessionId, segments.current);
await generateFeedback(sessionId);          // optional: the summary page also does this on first visit
navigate(`/summary/${sessionId}`);
```

Rules for good data: use the same `questionId` for the interviewer's question and the candidate's answers to it, and keep `speaker` as `"interviewer"` or `"candidate"`. Browser speech recognition gives only rough timings, so pause measures will be approximate; word-level timestamps from your speech service would be better.

---

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Browser console: CORS error | Your React port is missing from `feedback.cors.allowed-origins`. Add it and restart Spring Boot. |
| `502` "Feedback service could not analyze..." | Python service isn't running, or `feedback.service.url` is wrong. Check `curl http://localhost:8000/health`. |
| `404` "No transcript saved for session..." | Run the transcript step first (Step 3, call 1, or `saveTranscript` in Step 5). |
| Spring Boot can't connect to MySQL | Check URL, user and password in `application.properties`, and that MySQL is running on port 3306. |
| Controller not found (all `404`) | The copied files aren't under your `@SpringBootApplication` package. |
| Summary says "No candidate answers found" | No segment has `speaker` set to `candidate`. |
| Python: `ModuleNotFoundError` | Activate the virtual environment, then `pip install -r requirements.txt`. |

## Later

- **Tobii gaze:** the report already has a `gaze` block set to unavailable. Add a gaze feature step to the Python service and fill that block in.
- **Trained model:** when you have rated data, replace the scores in `interview_feedback.py` with model predictions. The `engine` field in the report (stored in `feedback_report.engine`) records which version produced each report.
- **Thresholds:** run `python interview_feedback.py --write_default_thresholds thresholds.json`, edit the file, then start the service with `THRESHOLDS_FILE=thresholds.json`.
