CREATE TABLE IF NOT EXISTS vl_sequence (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    confirmed_sequence INTEGER NOT NULL DEFAULT 0,
    reserved_sequence INTEGER,
    reserved_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,
    CONSTRAINT single_row CHECK (id = 1)
);

INSERT INTO vl_sequence (id, confirmed_sequence)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;
