# MODEL_SELECTION — Modelos y embeddings

> Decisión documentada (§23/§22). Revisar con cada cambio de modelo.

## Stack local (por defecto, CPU)

| Rol                | Modelo        | Proveedor | Coste  | Notas                          |
|--------------------|---------------|-----------|--------|--------------------------------|
| LLM estándar       | qwen2.5:7b    | Ollama    | 0      | 7B, 4.7 GB, razonable en CPU |
| Embeddings         | bge-m3        | Ollama    | 0      | 1024 dims, multilingüe, 8192 ctx |
| LLM ligero         | gemma3:1b     | Ollama    | 0      | pruebas rápidas               |

## Criterios de selección (evaluados)

- **Multilingüe**: bge-m3 homologado en MTEB multilingüe; español + inglés.
- **Texto científico y código**: 8192 tokens de contexto cubren chunks largos.
- **Footprint CPU**: bge-m3 ≈ 1.2 GB RAM; qwen2.5:7b ≈ 5-6 GB RAM (14 GB totales OK).
- **Coste**: 100% local → 0 USD por procesamiento; solo el router final puede
  apuntar a un proveedor API si se configura `LLM_PROVIDER=openai`.

## Routing por tarea (§22)

| Tarea                    | Modelo usado hoy              | Alternativa API                  |
|--------------------------|-------------------------------|----------------------------------|
| Embeddings (todo)        | bge-m3 (Ollama)               | text-embedding-3-small           |
| Entidad/relaciones       | qwen2.5:7b (etapa graph)      | llama-3.1-8b / gpt-4o-mini      |
| Wiki síntesis            | qwen2.5:7b (stage=wiki)       | gpt-4o-mini / claude-haiku        |
| Router final (§26/§27)   | qwen2.5:7b (stage=router)     | gpt-4o-mini / claude-sonnet       |
| Memoria (scoring)        | qwen2.5:7b (stage=extract)    | gpt-4o-mini                       |

## Verificación

```bash
curl 127.0.0.1:11434/api/tags | python3 -m json.tool   # modelos disponibles
kos versions                                            # versiones registradas
```

## Embeddings — versión y migración (§16)
- Dimensión: **1024** (bge-m3). Colección Qdrant `kos_chunks` creada con esa dim.
- Si se cambia el modelo de embeddings: crear colección nueva (`EMBEDDING_MODEL`),
  re-embedding incremental y reindex → nunca destruir la v1 sin migrar.