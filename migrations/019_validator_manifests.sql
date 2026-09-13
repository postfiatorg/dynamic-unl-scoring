-- Manifests the scoring service has seen for validator master keys.
-- Since postfiatd 1.0.6 a node keeps only a bounded set of manifests for
-- validators outside its list and forgets them on restart, so the RPC node
-- may not know a candidate's manifest at the moment it is selected for the
-- UNL. Every successful RPC lookup is remembered here and used as the
-- fallback when the node has no manifest for a selected validator.
CREATE TABLE IF NOT EXISTS validator_manifests (
    master_key TEXT PRIMARY KEY,
    manifest TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dry runs record whether a manifest was available for every selected
-- validator, so an operator can see a signing problem before a real round.
ALTER TABLE dry_runs ADD COLUMN IF NOT EXISTS manifest_check JSONB;
