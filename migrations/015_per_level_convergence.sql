-- Per-level output convergence results for M2.6 convergence monitoring. For an
-- accepted reveal, records which reproducible levels matched the foundation's
-- published hashes (RAW, PARSED, SELECTED_UNL), the first diverging stage, and
-- the shared failure-taxonomy category. Vocabulary matches the comparison
-- levels and categories defined in docs/phase2/SidecarScoringSpec.md.
ALTER TABLE validator_round_outcomes
    ADD COLUMN IF NOT EXISTS comparison_levels_matched TEXT,
    ADD COLUMN IF NOT EXISTS divergence_stage TEXT,
    ADD COLUMN IF NOT EXISTS divergence_category TEXT;
