# DATA MODEL — Hermes Knowledge OS

> Modelo lógico de datos del KOS. Fuente de verdad: PostgreSQL (control plane) + MinIO (objetos) + índices derivados (Qdrant, Graphify, Wiki).
> Reglas: IDs permanentes (uuid7), never filenames as IDs (§6), versionado por pipeline (embedding_v1…, parsers…, modelos…, §16), lineage completo (§48).

---

## 1. Esquema PostgreSQL

### `sources` — origen de un conocimiento
| col | tipo | nota |
|---|---|---|
| source_id | uuid PK | |
| source_uri | text | URL/ruta origen |
| source_type | enum | book/paper/website/wikipedia/documentation/video/transcript/dataset/code/archive/… |
| mime_type, language, author, publisher | text | |
| license | text FK→licenses | |
| canonical_url | text | para dedupe |
| fingerprint | text | hash semántico (LLM-embed) |
| ingested_at, updated_at, published_at | timestamptz | |
| checksum_sha256 | text | del asset estrable |
| object_key | text | ruta S3 |
| metadata_json | jsonb | libre |

### `documents` — versión lógica de un asset
| doc_id uuid PK · source_id FK · version int · title · content_hash_sha256 · parser_pipeline_version · chunking_profile · created_at · superseded_by (self-FK) | |

### `document_versions` — versionado inmutable (n → n+1, no se destruye la anterior)
| version_id PK · doc_id FK · content_hash · status (active/superseded/archived) · ingested_at · validator |

### `chunks`
| chunk_id uuid PK · doc_id FK · idx int · body_text · token_count · char_start · char_end · section_heading · language · (UNIQUE(doc_id, idx)) |

### `entities_concepts` (índice de grafos y wikis)
| entity_id uuid PK · name · type(concept/entity/theory/tech/subject) · canonical_name · domain · |

### `relations` (autoritativo para Graphify/wikis)
| relation_id PK · source_node FK· target_node FK · relation_type (calls/imports/uses/prerequisite_of/requires/teaches/explains/example_of/application_of/contradicts/extends/related_to/part_of…) · confidence · status(EXTRACTED/INFERRED/SYNTHESIZED/HUMAN_VERIFIED) · provenance_json (chunk+dll) · |

### `ingestion_jobs` — cola reanudable (§20)
| job_id PK · doc_id FK · stage (detect/parse/dedupe/chunk/embed/graph/wiki/index/validate) · status (queued/running/done/failed/cancelled) · attempt · worker · error · cost_est · created/started/finished | |

### `ingestion_status` — doc_status equivalente LightRAG (aplanado|PROCESSING|DONE|FAILED|CANCELLED)
| doc_id FK · pipeline (lightrag/graphify/wiki) · status · msg · updated_at · |

### `hashes` tabla única de fingerprints
| hash_id · sha256 · kind (content/url/fingerprint) · → entity doc/source · classified (duplicate/near_duplicate/new_version/translation/mirror/independent) · |

### `processing_costs` —elly tracks (§30/§31)
| cost_id PK · job_id · stage · provider · model · input_tokens · output_tokens · est_cost_usd · embed_count · timestamp · |

### `processing_errors`
| error_id PK · job_id · stage · error_class · message · stacktrace_short · retryable · created_at · |

### `model_versions` / `graphify_versions` / `lightrag_versions` / `knowledge_versions`
| id · name · version · commit/tag · installed_at · active | (equivalente a VERSIONS.md en PG) |

### `queries_log`
| query_id · query_text (hash) · query_type(A..H) · n_retrieved · n_after_rerank · latency_ms · tokens_in · cost · ts | |

### `agent_memory`
| memory_id · memory_type(episodic/semantic/procedural/decision) · content · importance_score · dedupe_key · status(candidate/validated/persisted) · source_session · created_at · | |

### `claims` (conflictos §15)
| claim_id · text · chunk_id · source_id · status · confidence · publish_date · domain · | |

## 2. Qdrant

Colección única **initial** `kos_chunks` con payload:
```
{ document_id, chunk_id, source_id, language, domain, tenant, knowledge_type (world|agent_memory), version, timestamp, embedding_model }
```
→ filtro por tenant/domain/lang/knowledge_type para multi-tenancy futuro (§7). Estrategia de **sharding** documentada en SCALING (a partir de ~10⁶ puntos). Distancia: COSINE. Dim: **1024** (bge-m3).

## 3. MinIO

```
bucket: kos-sources/  (objeto inmutable)
  books/ papers/ wikipedia/ documentation/ videos/ transcripts/ datasets/ code/ websites/ archives/
  key: sources/<kind>/<source_id>/v<version>.<ext>  (+ .sha256)
bucket: kos-derived/  (cache/derivados si algún día)
```
El original **nunca** se borra al actualizar (n → n+1).

## 4. Lineage u object graph (§48)

```
Wiki_page → concept → entity → relationship → chunk_id → document_id → source_id (PG + Qdrant payload + Graphify edges)
```
Cada wiki page guarda `source_chunk_ids[]` y `knowledge_version` → rastreo completo a la evidencia.

## 5. Provenance states

`EXTRACTED (1.0)` > `INFERRED (0.55–0.95)` > `AMBIGUOUS` (flag humano) para relaciones Graphify; `SYNTHESIZED` para compilaciones; `HUMAN_VERIFIED` tras edición humana. Nunca se presenta inferencia como cita.

---
*Versión 1.0 · 2026-08-07*