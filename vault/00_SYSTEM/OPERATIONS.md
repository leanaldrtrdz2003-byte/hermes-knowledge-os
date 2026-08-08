# OPERATIONS — Hermes Knowledge OS

> Guía operativa: arranque, ingesta, consulta, backups, troubleshooting (§53).

## Arranque

```bash
docker compose up -d          # postgres + qdrant + minio (red kos-net)
sudo systemctl start ollama   # daemon LLM local (ver AUDIT.md: /var/lib/ollama)
make setup                    # esquema PG + buckets + colección + versiones
```

Health:
```bash
make health                    # compose ps + ollama version
kos dashboard                 # métricas del control plane
```

## Ingestión

```bash
make ingest DIR=data/raw        # registra y encola documentos (idempotente)
make worker                     # consume jobs (etapas: parse→chunk→embed→index→graph→wiki)
```

- Re-ingestar el mismo directorio NO reprocesa (dedupe por SHA256, §18).
- Jobs fallidos: `UPDATE ingestion_jobs SET status='queued' WHERE status='failed';`
  (reanudable, §17).

## Consulta

```bash
make query Q="¿Qué es la entropía?"
kos query "¿Cómo se relaciona el transformador con la atención?" --mode hybrid
```

El router clasifica A–H (§25), ensambla evidencia con fence (§33) y cita
`[Source: doc_id] [Chunk: chunk_id]`.

## Memoria

```bash
make memory O="El usuario prefiere respuestas en español."
kos memory                      # lista memorias persistidas
```

## Wiki y grafo

```bash
make wiki     # compila/actualiza páginas wiki incrementalmente (§9/§13)
make graph    # grafo estructural Graphify → vault/04_GRAPH
```

## Backups (§34)

```bash
make backup                          # pg_dump + tar (vault/staging/lightrag)
make restore F=data/backups/kos_backup_<ts>.sql
```

## Troubleshooting

| Síntoma                         | Causa típica                 | Fix                                            |
|---------------------------------|------------------------------|------------------------------------------------|
| Ollama "activating" inmortal   | /var/lib/ollama sin dueño    | `sudo chown -R ollama:ollama /var/lib/ollama`  |
| Import de kos falla               | PYTHONPATH heredado          | `env -u PYTHONPATH .venv/bin/python …`         |
| uv pip "No module pip"            | venv de uv sin pip           | `uv pip install --python .venv/bin/python …`   |
| Jobs en failed                    | etapa con error transitorio  | re-encolar: status='queued'                    |
| Qdrant colección mal dimensionada | cambio de embedding           | crear colección nueva + reindex (§16)           |
| LightRAG lento en CPU             | qwen2.5:7b en generación     | normal: ~1-3 min/doc — paralelizar workers     |

## Monitoreo

```bash
sudo journalctl -u ollama -f
docker compose logs -f postgres qdrant minio
```