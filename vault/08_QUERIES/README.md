# 08_QUERIES — Registro de consultas

> Espejo legible de la tabla `queries_log`: qué se preguntó y cómo se respondió.
> Útil para auditar cobertura (¿qué dominios se han consultado?) y calidad.

Ver SQL:
```sql
SELECT q.type_name, COUNT(*), ROUND(AVG(q.latency_ms)) FROM queries_log GROUP BY 1;
```

Regenerar resumen:
```bash
env -u PYTHONPATH .venv/bin/python scripts/query_summary.py   # (si existe)
```