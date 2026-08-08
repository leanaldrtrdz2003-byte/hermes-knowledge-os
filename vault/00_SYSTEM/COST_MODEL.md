# COST_MODEL — Modelo de costes

> Principio (§46): minimizar coste por unidad de conocimiento útil recuperable.
> El sistema es 100% local por defecto → coste marginal ≈ 0.

## Coste por componente

| Componente     | Local (default) | API (opcional)                        |
|----------------|-----------------|---------------------------------------|
| Embeddings     | 0 (bge-m3 CPU)  | ~$0.02 / 1M tokens                    |
| LLM pipeline   | 0 (qwen2.5:7b)  | ~$0.15-0.60 / 1M in+out (gpt-4o-mini)  |
| Router final   | 0               | según proveedor elegido               |
| Almacenamiento | 0 (disco)       | MinIO/S3 cloud según GB               |

## Tracking (§31)
Cada llamada LLM registra `processing_costs` (stage, provider, model,
input/output tokens, est_cost_usd). Consulta:

```sql
SELECT stage, COUNT(*), ROUND(SUM(est_cost_usd)::numeric, 4) AS usd
FROM processing_costs GROUP BY stage ORDER BY usd DESC;
```

## Optimizaciones implementadas
- **Cache LLM de LightRAG** (llm_response_cache en PG KV) → consultas repetidas
  no regeneran.
- **Cache de extracción Graphify** (SHA256 por archivo → skip sin cambios).
- **Incremental wiki** (fingerprint de fuentes → no recompilar, §9).
- **Embeddings idempotentes** (chunks con has_embedding).
- **Sin reproceso por dedupe** (hash en `hashes`/`sources`).

## Proyección de escala
- Fase actual: ~1-2 llamadas LLM por documento (graph + wiki) + LightRAG interno.
  Coste real: 0 USD (local).
- A 1M documentos con API hipotética (~2 llamadas/doc, gpt-4o-mini):
  ≈ 2M × ~$0.0003 ≈ **$600 por pasada completa** — el cache y el incremento
  reducen pasadas posteriores a 0.