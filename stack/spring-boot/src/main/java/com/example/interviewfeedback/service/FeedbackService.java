package com.example.interviewfeedback.service;

import com.example.interviewfeedback.dto.SegmentDto;
import com.example.interviewfeedback.model.FeedbackReport;
import com.example.interviewfeedback.model.TranscriptSegment;
import com.example.interviewfeedback.repository.FeedbackReportRepository;
import com.example.interviewfeedback.repository.TranscriptSegmentRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.server.ResponseStatusException;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class FeedbackService {

    private final TranscriptSegmentRepository segments;
    private final FeedbackReportRepository reports;
    private final RestTemplate rest;
    private final ObjectMapper mapper;
    private final String serviceUrl;

    public FeedbackService(TranscriptSegmentRepository segments,
                           FeedbackReportRepository reports,
                           RestTemplate rest,
                           ObjectMapper mapper,
                           @Value("${feedback.service.url}") String serviceUrl) {
        this.segments = segments;
        this.reports = reports;
        this.rest = rest;
        this.mapper = mapper;
        this.serviceUrl = serviceUrl;
    }

    /** Replaces any transcript already stored for this session, so re-sending is safe. */
    @Transactional
    public int saveTranscript(Long sessionId, List<SegmentDto> dtos) {
        if (dtos == null || dtos.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Transcript is empty.");
        }
        List<TranscriptSegment> rows = new ArrayList<>();
        for (SegmentDto d : dtos) {
            if (d.speaker() == null || d.startS() == null || d.endS() == null || d.text() == null) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "Each segment needs speaker, startS, endS and text.");
            }
            rows.add(new TranscriptSegment(sessionId, d.questionId(), d.speaker(), d.startS(), d.endS(), d.text()));
        }
        segments.deleteBySessionId(sessionId);
        segments.saveAll(rows);
        return rows.size();
    }

    /** Sends the stored transcript to the Python service and stores the report it returns. */
    public FeedbackReport generate(Long sessionId) {
        List<TranscriptSegment> stored = segments.findBySessionIdOrderByStartSAsc(sessionId);
        if (stored.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                    "No transcript saved for session " + sessionId + ".");
        }

        List<Map<String, Object>> rows = new ArrayList<>();
        for (TranscriptSegment s : stored) {
            Map<String, Object> r = new LinkedHashMap<>();
            r.put("question_id", s.getQuestionId());
            r.put("speaker", s.getSpeaker());
            r.put("start_s", s.getStartS());
            r.put("end_s", s.getEndS());
            r.put("text", s.getText());
            rows.add(r);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("session_id", String.valueOf(sessionId));
        body.put("segments", rows);

        String json;
        try {
            json = rest.postForObject(serviceUrl + "/analyze", body, String.class);
        } catch (RestClientException e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "Feedback service could not analyze this session: " + e.getMessage());
        }
        if (json == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Feedback service returned nothing.");
        }

        try {
            JsonNode node = mapper.readTree(json);
            int score = node.path("scores").path("delivery_overall").asInt();
            String engine = node.path("engine").asText("rule_based_v0");
            return reports.save(new FeedbackReport(sessionId, engine, score, json));
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "Feedback service returned an unreadable report.");
        }
    }

    public FeedbackReport latest(Long sessionId) {
        return reports.findFirstBySessionIdOrderByCreatedAtDesc(sessionId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "No feedback yet for session " + sessionId + "."));
    }
}
