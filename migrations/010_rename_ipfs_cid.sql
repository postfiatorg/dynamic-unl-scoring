DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'scoring_rounds'
          AND column_name = 'ipfs_cid'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'scoring_rounds'
          AND column_name = 'final_bundle_cid'
    ) THEN
        ALTER TABLE scoring_rounds RENAME COLUMN ipfs_cid TO final_bundle_cid;
    ELSIF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'scoring_rounds'
          AND column_name = 'ipfs_cid'
    ) AND EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'scoring_rounds'
          AND column_name = 'final_bundle_cid'
    ) THEN
        UPDATE scoring_rounds
        SET final_bundle_cid = COALESCE(final_bundle_cid, ipfs_cid);

        ALTER TABLE scoring_rounds DROP COLUMN ipfs_cid;
    END IF;
END $$;
