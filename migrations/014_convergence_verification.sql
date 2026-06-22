-- M2.6.2 commitment verification: bind each round's commit/reveal windows
-- (the authoritative source is the on-chain round announcement) and store the
-- per-validator participation outcome computed from the ingested submissions.

-- Round announcement windows, ingested from chain by the same watcher that
-- ingests commits/reveals. Keyed by round_number; the first announcement seen
-- for a round wins (the watcher scans oldest-first, so that is the earliest by
-- ledger order). These boundaries are not derivable from config — they are
-- anchored to announcement-emission time — so chain is the only source.
CREATE TABLE IF NOT EXISTS round_announcements (
    round_number       INTEGER PRIMARY KEY,
    tx_hash            TEXT NOT NULL,
    input_package_hash TEXT,
    input_package_cid  TEXT,
    protocol_version   INTEGER,
    network            TEXT,
    commit_opens_at    TIMESTAMPTZ NOT NULL,
    commit_closes_at   TIMESTAMPTZ NOT NULL,
    reveal_opens_at    TIMESTAMPTZ NOT NULL,
    reveal_closes_at   TIMESTAMPTZ NOT NULL,
    ledger_index       BIGINT NOT NULL,
    transaction_index  INTEGER NOT NULL,
    ledger_close_time  TIMESTAMPTZ,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One verification verdict per (round, validator), recomputed and upserted as
-- new submissions arrive. The population is the set of observed committers.
CREATE TABLE IF NOT EXISTS validator_round_outcomes (
    round_number         INTEGER NOT NULL,
    validator_master_key TEXT NOT NULL,
    outcome              TEXT NOT NULL,
    accepted_commit_tx   TEXT,
    accepted_reveal_tx   TEXT,
    conflicting_commit   BOOLEAN NOT NULL DEFAULT FALSE,
    conflicting_reveal   BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (round_number, validator_master_key)
);
