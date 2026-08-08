-- ============================================================
-- Hermes Knowledge OS — Esquema PostgreSQL (control plane)
-- Reglas: IDs uuid, FK estables, versionado, lineage (§6/§16/§48)
-- ============================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector (para futuros embeddings en PG)

-- Tipos
DO $$ BEGIN
  CREATE TYPE source_kind AS ENUM ('book','paper','website','wikipedia','documentation','video','transcript','dataset','code','archive','other');
  CREATE TYPE doc_status AS ENUM ('pending','detected','parsed','deduped','chunked','embedded','graphed','wiki','indexed','validated','ready','failed','cancelled');
  CREATE TYPE job_status AS ENUM ('queued','running','done','failed','cancelled','skipped');
  CREATE TYPE rel_confidence AS ENUM ('EXTRACTED','INFERRED','AMBIGUOUS','SYNTHESIZED','HUMAN_VERIFIED');
  CREATE TYPE memory_kind AS ENUM ('episodic','semantic','procedural','decision');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ── Licencias / autores / publishers / idiomas (tablas de referencia)
CREATE TABLE IF NOT EXISTS licenses ( license_id serial PRIMARY KEY, name text UNIQUE NOT NULL, commercial_ok boolean DEFAULT true, note text );
CREATE TABLE IF NOT EXISTS languages ( language_code text PRIMARY KEY, name text NOT NULL );
CREATE TABLE IF NOT EXISTS authors ( author_id serial PRIMARY KEY, name text UNIQUE NOT NULL );
CREATE TABLE IF NOT EXISTS publishers ( publisher_id serial PRIMARY KEY, name text UNIQUE NOT NULL );

-- ── Fuentes (objetos inmutables en MinIO)
CREATE TABLE IF NOT EXISTS sources (
  source_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type     source_kind NOT NULL DEFAULT 'other',
  source_uri      text,
  canonical_url   text,
  title           text,
  mime_type       text,
  language        text,
  author_id       int REFERENCES authors(author_id),
  publisher_id    int REFERENCES publishers(publisher_id),
  license_id      int REFERENCES licenses(license_id),
  published_at    timestamptz,
  ingested_at     timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  checksum_sha256 text,
  object_key      text,
  object_size     bigint,
  fingerprint     text,
  metadata_json   jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
CREATE INDEX IF NOT EXISTS idx_sources_canon ON sources(canonical_url);

-- ── Documentos (versión lógica de un asset; versionado por hashes)
CREATE TABLE IF NOT EXISTS documents (
  doc_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id     uuid NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  version       int NOT NULL DEFAULT 1,
  title         text,
  content_hash  text NOT NULL,
  parser_version text,
  chunk_profile text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  superseded_by uuid REFERENCES documents(doc_id),
  UNIQUE (source_id, content_hash, version)
);
CREATE TABLE IF NOT EXISTS document_versions (
  version_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id        uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  content_hash  text NOT NULL,
  status        text NOT NULL DEFAULT 'active',
  ingested_at   timestamptz NOT NULL DEFAULT now()
);

-- ── Chunks
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id      uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  idx         int NOT NULL,
  body_text   text NOT NULL,
  token_count int,
  char_start  int,
  char_end    int,
  section_heading text,
  language    text,
  has_embedding boolean NOT NULL DEFAULT FALSE,
  UNIQUE (doc_id, idx)
);

-- ── Entidades / conceptos / relaciones (@ knowledge graph + wiki)
CREATE TABLE IF NOT EXISTS entities (
  entity_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name           text NOT NULL,
  kind           text NOT NULL DEFAULT 'concept',  -- concept|entity|theory|technology|subject|…
  canonical_name text,
  domain         text,
  UNIQUE (canonical_name, kind)
);
CREATE TABLE IF NOT EXISTS relations (
  relation_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id     uuid NOT NULL REFERENCES entities(entity_id),
  target_id     uuid NOT NULL REFERENCES entities(entity_id),
  relation_type text NOT NULL,   -- prerequisite_of|requires|teaches|explains|example_of|… (§49)
  confidence    rel_confidence NOT NULL DEFAULT 'INFERRED',
  provenance    jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {chunk_id, doc_id, source_id}
  source_doc    uuid REFERENCES documents(doc_id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, target_id, relation_type)
);

-- ── Cola de jobs (§20) — interfaz migrable a Redis/Celery/NATS
CREATE TABLE IF NOT EXISTS ingestion_jobs (
  job_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id       uuid REFERENCES documents(doc_id) ON DELETE CASCADE,
  job_type     text NOT NULL,          -- detect|parse|dedupe|chunk|embed|graph|wiki|index|validate
  status       job_status NOT NULL DEFAULT 'queued',
  attempt      int NOT NULL DEFAULT 0,
  worker       text,
  error        text,
  cost_est_usd numeric(12,8) DEFAULT 0,
  created_at   timestamptz NOT NULL DEFAULT now(),
  started_at   timestamptz,
  finished_at  timestamptz
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs(status, job_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_doc_stage ON ingestion_jobs(doc_id, job_type) WHERE status <> 'done';

-- ── Doc status (equivalente LightRAG aplanado)
CREATE TABLE IF NOT EXISTS ingestion_status (
  doc_id      uuid PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
  pipeline    text NOT NULL,          -- lightrag|graphify|wiki
  status      doc_status NOT NULL DEFAULT 'pending',
  message     text,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (doc_id, pipeline)
);

-- ── Hashes / deduplication
CREATE TABLE IF NOT EXISTS hashes (
  hash_id    bigserial PRIMARY KEY,
  sha256     text NOT NULL,
  kind       text NOT NULL,           -- content|url|fingerprint
  ref_type   text NOT NULL,            -- source|document
  ref_id     uuid NOT NULL,
  classified text NOT NULL DEFAULT 'independent',  -- duplicate|near_duplicate|new_version|translation|mirror
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sha256, kind, ref_type, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_hashes_sha ON hashes(sha256);

-- ── Versiones de pipelines/modelos (§16)
CREATE TABLE IF NOT EXISTS pipeline_versions (
  id           serial PRIMARY KEY,
  component    text NOT NULL,          -- lightrag|graphify|embedding_model|llm_model|parser|pipeline
  name         text NOT NULL,
  version      text NOT NULL,
  commit_tag   text,
  active       boolean NOT NULL DEFAULT false,
  installed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (component, name, version)
);

-- ── Costes (§30/§31) y errores
CREATE TABLE IF NOT EXISTS processing_costs (
  cost_id       bigserial PRIMARY KEY,
  job_id        uuid REFERENCES ingestion_jobs(job_id),
  stage         text,
  provider      text,
  model         text,
  input_tokens  bigint DEFAULT 0,
  output_tokens bigint DEFAULT 0,
  est_cost_usd  numeric(12,8) DEFAULT 0,
  embed_count   int DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS processing_errors (
  error_id    bigserial PRIMARY KEY,
  job_id      uuid REFERENCES ingestion_jobs(job_id),
  stage       text,
  error_class text,
  message     text,
  retryable   boolean DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ── Log de queries (observabilidad §30)
CREATE TABLE IF NOT EXISTS queries_log (
  query_id     bigserial PRIMARY KEY,
  query_hash   text NOT NULL,
  query_type   text,             -- A..H (§25)
  question     text,
  mode         text,
  n_retrieved  int,
  n_after_rerank int,
  answer_chars int,
  provider     text,
  model        text,
  latency_ms   int,
  tokens_in    int,
  tokens_out   int,
  cost_usd     numeric(12,8),
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- ── Memoria del agente (§12)
CREATE TABLE IF NOT EXISTS agent_memory (
  memory_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  memory_kind    memory_kind NOT NULL,
  content        text NOT NULL,
  importance     numeric(4,3) NOT NULL DEFAULT 0.5,
  dedupe_key     text,
  status         text NOT NULL DEFAULT 'candidate',  -- candidate|validated|persisted|discarded
  source_session text,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_dedupe ON agent_memory(dedupe_key) WHERE dedupe_key IS NOT NULL;

-- ── Claims/conflictos (§15)
CREATE TABLE IF NOT EXISTS claims (
  claim_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_text text NOT NULL,
  chunk_id   uuid REFERENCES chunks(chunk_id),
  source_id  uuid REFERENCES sources(source_id),
  status     text NOT NULL DEFAULT 'EXTRACTED',
  confidence numeric(4,3),
  publish_date timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ===== Datos semilla básicos =====
INSERT INTO languages(language_code, name) VALUES ('es','Spanish'),('en','English')
  ON CONFLICT DO NOTHING;
INSERT INTO licenses(name, commercial_ok, note) VALUES
  ('Apache-2.0', true, 'Apache License 2.0'),
  ('MIT', true, 'MIT License'),
  ('PostgreSQL', true, 'PostgreSQL License'),
  ('AGPL-3.0', false, 'GNU AGPL v3 — cuidado redistribution'),
  ('CC-BY-4.0', true, 'Creative Commons BY 4.0')
  ON CONFLICT DO NOTHING;

-- trigger updated_at en sources
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_sources_updated ON sources;
CREATE TRIGGER trg_sources_updated BEFORE UPDATE ON sources FOR EACH ROW EXECUTE FUNCTION set_updated_at();