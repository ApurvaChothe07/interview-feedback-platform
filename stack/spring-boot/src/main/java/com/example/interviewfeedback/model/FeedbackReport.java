package com.example.interviewfeedback.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "feedback_report")
public class FeedbackReport {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "session_id", nullable = false)
    private Long sessionId;

    @Column(nullable = false, length = 40)
    private String engine;

    @Column(name = "delivery_score")
    private Integer deliveryScore;

    @Column(name = "report_json", nullable = false, columnDefinition = "LONGTEXT")
    private String reportJson;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    public FeedbackReport() {}

    public FeedbackReport(Long sessionId, String engine, Integer deliveryScore, String reportJson) {
        this.sessionId = sessionId;
        this.engine = engine;
        this.deliveryScore = deliveryScore;
        this.reportJson = reportJson;
    }

    @PrePersist
    void onCreate() {
        if (createdAt == null) createdAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public Long getSessionId() { return sessionId; }
    public String getEngine() { return engine; }
    public Integer getDeliveryScore() { return deliveryScore; }
    public String getReportJson() { return reportJson; }
    public LocalDateTime getCreatedAt() { return createdAt; }
}
