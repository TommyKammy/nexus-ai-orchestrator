BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memory_vectors (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  content TEXT NOT NULL,
  embedding VECTOR(1536) NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  source TEXT,
  content_hash TEXT,
  metadata_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE memory_vectors
  ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS source TEXT,
  ADD COLUMN IF NOT EXISTS content_hash TEXT,
  ADD COLUMN IF NOT EXISTS metadata_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_memory_vectors_tenant_scope
  ON memory_vectors (tenant_id, scope);

CREATE INDEX IF NOT EXISTS idx_memory_vectors_created_at
  ON memory_vectors (created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_memory_vectors_content_hash
  ON memory_vectors (tenant_id, scope, content_hash)
  WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_vectors_lookup
  ON memory_vectors (tenant_id, scope, content_hash)
  WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_vectors_embedding
  ON memory_vectors USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50);

CREATE TABLE IF NOT EXISTS audit_events (
  id BIGSERIAL PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT NOT NULL,
  decision TEXT NOT NULL,
  payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  request_id TEXT,
  policy_id TEXT,
  policy_version TEXT,
  policy_reason TEXT,
  risk_score INTEGER,
  prev_hash TEXT,
  event_hash TEXT
);

ALTER TABLE audit_events
  ADD COLUMN IF NOT EXISTS payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS request_id TEXT,
  ADD COLUMN IF NOT EXISTS policy_id TEXT,
  ADD COLUMN IF NOT EXISTS policy_version TEXT,
  ADD COLUMN IF NOT EXISTS policy_reason TEXT,
  ADD COLUMN IF NOT EXISTS risk_score INTEGER,
  ADD COLUMN IF NOT EXISTS prev_hash TEXT,
  ADD COLUMN IF NOT EXISTS event_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_audit_events_created_at
  ON audit_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_events_actor_action
  ON audit_events (actor, action);

CREATE INDEX IF NOT EXISTS idx_audit_events_target
  ON audit_events (target);

COMMIT;
