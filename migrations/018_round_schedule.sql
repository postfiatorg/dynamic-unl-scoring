-- Persisted round schedule. A scheduled round is due when now() >= next_due_at.
-- Not seeded here: the seed depends on SCORING_CADENCE_HOURS (an environment
-- setting unavailable to SQL), and a NOW() seed would fire a round immediately
-- on deploy. ensure_schedule_seeded() in scoring_service/services/scheduler.py
-- seeds the row idempotently using the legacy last-attempt + cadence formula.
CREATE TABLE IF NOT EXISTS round_schedule (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    next_due_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT single_row CHECK (id = 1)
);
