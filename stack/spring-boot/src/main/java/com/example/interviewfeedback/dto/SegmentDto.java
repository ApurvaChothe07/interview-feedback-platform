package com.example.interviewfeedback.dto;

/**
 * One timestamped piece of the interview transcript, as sent by the React app.
 * speaker: "interviewer" or "candidate"
 * startS / endS: seconds from the start of the interview (same clock for every segment).
 */
public record SegmentDto(Integer questionId, String speaker, Double startS, Double endS, String text) {}
