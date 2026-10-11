package com.example.interviewfeedback.controller;

import com.example.interviewfeedback.dto.SegmentDto;
import com.example.interviewfeedback.model.FeedbackReport;
import com.example.interviewfeedback.service.FeedbackService;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/sessions")
public class FeedbackController {

    private final FeedbackService service;

    public FeedbackController(FeedbackService service) {
        this.service = service;
    }

    /** 1) Save the timestamped transcript when the interview ends. */
    @PostMapping("/{sessionId}/transcript")
    public Map<String, Object> saveTranscript(@PathVariable Long sessionId,
                                              @RequestBody List<SegmentDto> segments) {
        int saved = service.saveTranscript(sessionId, segments);
        return Map.of("sessionId", sessionId, "segmentsSaved", saved);
    }

    /** 2) Analyze the saved transcript and store the report. Returns the report JSON. */
    @PostMapping(value = "/{sessionId}/feedback", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> generate(@PathVariable Long sessionId) {
        FeedbackReport report = service.generate(sessionId);
        return ResponseEntity.ok(report.getReportJson());
    }

    /** 3) Read the latest stored report (used by the /summary page). */
    @GetMapping(value = "/{sessionId}/feedback", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> latest(@PathVariable Long sessionId) {
        return ResponseEntity.ok(service.latest(sessionId).getReportJson());
    }
}
