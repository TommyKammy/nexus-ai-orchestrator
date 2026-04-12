BEGIN;

CREATE OR REPLACE FUNCTION app_current_tenant_id()
RETURNS TEXT AS $$
BEGIN
  RETURN NULLIF(current_setting('app.current_tenant_id', true), '');
END;
$$ LANGUAGE plpgsql STABLE;

CREATE TABLE IF NOT EXISTS memory_episodes (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  summary TEXT NOT NULL,
  outcome TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ NOT NULL,
  metadata_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_episodes_tenant_scope
  ON memory_episodes (tenant_id, scope);

CREATE INDEX IF NOT EXISTS idx_memory_episodes_created_at
  ON memory_episodes (created_at DESC);

ALTER TABLE memory_vectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_vectors FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memory_vectors_tenant_select ON memory_vectors;
CREATE POLICY memory_vectors_tenant_select
  ON memory_vectors
  FOR SELECT
  USING (tenant_id = app_current_tenant_id());

DROP POLICY IF EXISTS memory_vectors_tenant_insert ON memory_vectors;
CREATE POLICY memory_vectors_tenant_insert
  ON memory_vectors
  FOR INSERT
  WITH CHECK (tenant_id = app_current_tenant_id());

DROP POLICY IF EXISTS memory_vectors_tenant_update ON memory_vectors;
CREATE POLICY memory_vectors_tenant_update
  ON memory_vectors
  FOR UPDATE
  USING (tenant_id = app_current_tenant_id())
  WITH CHECK (tenant_id = app_current_tenant_id());

DROP POLICY IF EXISTS memory_vectors_tenant_delete ON memory_vectors;
CREATE POLICY memory_vectors_tenant_delete
  ON memory_vectors
  FOR DELETE
  USING (tenant_id = app_current_tenant_id());

ALTER TABLE memory_episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_episodes FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memory_episodes_tenant_select ON memory_episodes;
CREATE POLICY memory_episodes_tenant_select
  ON memory_episodes
  FOR SELECT
  USING (tenant_id = app_current_tenant_id());

DROP POLICY IF EXISTS memory_episodes_tenant_insert ON memory_episodes;
CREATE POLICY memory_episodes_tenant_insert
  ON memory_episodes
  FOR INSERT
  WITH CHECK (tenant_id = app_current_tenant_id());

DROP POLICY IF EXISTS memory_episodes_tenant_update ON memory_episodes;
CREATE POLICY memory_episodes_tenant_update
  ON memory_episodes
  FOR UPDATE
  USING (tenant_id = app_current_tenant_id())
  WITH CHECK (tenant_id = app_current_tenant_id());

DROP POLICY IF EXISTS memory_episodes_tenant_delete ON memory_episodes;
CREATE POLICY memory_episodes_tenant_delete
  ON memory_episodes
  FOR DELETE
  USING (tenant_id = app_current_tenant_id());

COMMIT;
