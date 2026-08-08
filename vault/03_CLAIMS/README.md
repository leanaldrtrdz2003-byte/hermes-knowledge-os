# 03_CLAIMS — Hechos con procedencia

> Claims = afirmaciones verificables extraídas del corpus (§49).
> Tabla `claims` (src: chunk_id · claim_type: EXTRACTED | INFERRED |
> AMBIGUOUS | HUMAN_VERIFIED).

## Verificación
```sql
SELECT c.id, c.claim_type, c.claim_text, c.confidence, c.source_chunk
FROM claims c ORDER BY c.claim_type;
```

## Uso
- El router (§25) usa claims para respuestas tipo F (evidencia) y G (metaconocimiento).
- El grafo (04_GRAPH) enlaza claims con las entidades que mencionan.