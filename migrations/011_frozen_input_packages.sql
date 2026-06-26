ALTER TABLE scoring_rounds
    ADD COLUMN IF NOT EXISTS input_package_cid TEXT,
    ADD COLUMN IF NOT EXISTS input_package_hash TEXT,
    ADD COLUMN IF NOT EXISTS input_frozen_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS input_package_files (
    round_number  INTEGER NOT NULL,
    file_path     TEXT NOT NULL,
    content       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (round_number, file_path)
);
