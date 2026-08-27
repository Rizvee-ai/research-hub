-- AI Research Hub — database schema
-- Run this once, in the Supabase SQL Editor.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per document ----------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id            SERIAL PRIMARY KEY,
    filename      TEXT NOT NULL,
    content_hash  TEXT UNIQUE,              -- stops the same file twice
    source_path   TEXT,
    page_count    INT,
    word_count    INT,
    full_text     TEXT,                     -- kept for whole-document reviews

    -- filled in by the model
    title         TEXT,
    authors       TEXT,
    doc_date      TEXT,
    doc_type      TEXT,                     -- from a fixed list
    audience      TEXT,
    topics        TEXT[],                   -- from a fixed list
    summary       TEXT,
    key_points    TEXT,

    -- recorded by the pipeline
    status        TEXT DEFAULT 'ingested',  -- ingested | ocr | excluded
    status_note   TEXT,
    reviewed_by   TEXT,                     -- empty until a person checks it
    added_at      TIMESTAMPTZ DEFAULT now()
);

-- One row per passage -----------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id        SERIAL PRIMARY KEY,
    doc_id    INT REFERENCES documents(id) ON DELETE CASCADE,
    page      INT,
    seq       INT,
    text      TEXT NOT NULL,
    embedding vector(384),
    tsv       tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

-- Indexes -----------------------------------------------------------------
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_tsv_idx
    ON chunks USING gin (tsv);

CREATE INDEX IF NOT EXISTS chunks_doc_idx
    ON chunks (doc_id);

CREATE INDEX IF NOT EXISTS documents_type_idx
    ON documents (doc_type);
