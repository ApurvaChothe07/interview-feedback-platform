package com.example.interviewfeedback.repository;

import com.example.interviewfeedback.model.FeedbackReport;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface FeedbackReportRepository extends JpaRepository<FeedbackReport, Long> {

    Optional<FeedbackReport> findFirstBySessionIdOrderByCreatedAtDesc(Long sessionId);
}
