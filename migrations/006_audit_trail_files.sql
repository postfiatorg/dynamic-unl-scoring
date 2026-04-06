CREATE TABLE audit_trail_files (
    round_number  INTEGER NOT NULL,
    file_path     TEXT NOT NULL,
    content       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (round_number, file_path)
);
