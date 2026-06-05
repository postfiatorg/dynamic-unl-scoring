ALTER TABLE scoring_rounds
    ADD COLUMN IF NOT EXISTS announcement_tx_hash TEXT;
