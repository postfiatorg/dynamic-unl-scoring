-- Phase 2 hardening: withhold output artifacts until the commit window closes.
--
-- Normal rounds park in AWAITING_COMMIT_CLOSE after VL signing. The final
-- output bundle, public VL distribution, and on-chain final-bundle memo are
-- published later by a restart-safe scheduler pass.

ALTER TABLE scoring_rounds
    ADD COLUMN IF NOT EXISTS output_publication_commit_closes_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS output_publication_due_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS output_publication_not_tracked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS scoring_round_publication_artifacts (
    round_number INTEGER PRIMARY KEY,
    snapshot JSONB NOT NULL,
    raw_evidence JSONB NOT NULL,
    scoring_result JSONB NOT NULL,
    unl_result JSONB NOT NULL,
    signed_vl JSONB NOT NULL,
    prompt_messages JSONB NOT NULL,
    validator_id_map JSONB NOT NULL,
    input_package_files JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Existing already-published rows predate the hold; mark their outputs
-- available so historical audit URLs keep working after the gate is added.
UPDATE scoring_rounds
SET output_publication_commit_closes_at = COALESCE(
        output_publication_commit_closes_at,
        completed_at,
        created_at
    ),
    output_publication_due_at = COALESCE(
        output_publication_due_at,
        completed_at,
        created_at
    )
WHERE final_bundle_cid IS NOT NULL
  AND output_publication_commit_closes_at IS NULL;
