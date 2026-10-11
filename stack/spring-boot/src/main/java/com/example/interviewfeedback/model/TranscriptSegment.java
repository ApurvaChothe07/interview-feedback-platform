package com.example.interviewfeedback.model;

import jakarta.persistence.*;

@Entity
@Table(name = "transcript_segment")
public class TranscriptSegment {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "session_id", nullable = false)
    private Long sessionId;

    @Column(name = "question_id")
    private Integer questionId;

    @Column(nullable = false, length = 20)
    private String speaker;

    @Column(name = "start_s", nullable = false)
    private Double startS;

    @Column(name = "end_s", nullable = false)
    private Double endS;

    @Column(name = "text", nullable = false, columnDefinition = "TEXT")
    private String text;

    public TranscriptSegment() {}

    public TranscriptSegment(Long sessionId, Integer questionId, String speaker,
                             Double startS, Double endS, String text) {
        this.sessionId = sessionId;
        this.questionId = questionId;
        this.speaker = speaker;
        this.startS = startS;
        this.endS = endS;
        this.text = text;
    }

    public Long getId() { return id; }
    public Long getSessionId() { return sessionId; }
    public Integer getQuestionId() { return questionId; }
    public String getSpeaker() { return speaker; }
    public Double getStartS() { return startS; }
    public Double getEndS() { return endS; }
    public String getText() { return text; }
}
