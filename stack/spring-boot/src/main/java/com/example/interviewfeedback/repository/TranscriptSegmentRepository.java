package com.example.interviewfeedback.repository;

import com.example.interviewfeedback.model.TranscriptSegment;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface TranscriptSegmentRepository extends JpaRepository<TranscriptSegment, Long> {

    List<TranscriptSegment> findBySessionIdOrderByStartSAsc(Long sessionId);

    void deleteBySessionId(Long sessionId);
}
