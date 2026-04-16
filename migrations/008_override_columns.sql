ALTER TABLE scoring_rounds ADD COLUMN IF NOT EXISTS override_type TEXT;
ALTER TABLE scoring_rounds ADD COLUMN IF NOT EXISTS override_reason TEXT;
