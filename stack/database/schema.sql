-- Optional: run this by hand, OR leave spring.jpa.hibernate.ddl-auto=update and let
-- Spring Boot create the same tables on first start.
-- session_id is the id your app already uses for an interview attempt (no foreign key
-- is added here so it works with whatever session table you have).

CREATE DATABASE IF NOT EXISTS interview_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE interview_db;

CREATE TABLE IF NOT EXISTS transcript_segment (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id  BIGINT      NOT NULL,
  question_id INT         NULL,
  speaker     VARCHAR(20) NOT NULL,          -- 'interviewer' or 'candidate'
  start_s     DOUBLE      NOT NULL,          -- seconds from interview start
  end_s       DOUBLE      NOT NULL,
  text        TEXT        NOT NULL,
  INDEX idx_segment_session (session_id, start_s)
);

CREATE TABLE IF NOT EXISTS feedback_report (
  id             BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id     BIGINT      NOT NULL,
  engine         VARCHAR(40) NOT NULL,       -- e.g. rule_based_v0, later your ML model
  delivery_score INT         NULL,
  report_json    LONGTEXT    NOT NULL,       -- full JSON from the feedback service
  created_at     DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_report_session (session_id, created_at)
);
