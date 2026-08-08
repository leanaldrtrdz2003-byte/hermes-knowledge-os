# SECURITY — Hermes Knowledge OS

> Modelo de amenazas y defensas (§32/§33). Corto y operativo.

## 1. Secretos
- `.env` NUNCA se sube a Git (`.gitignore` lo excluye).
- `.env.example` documenta las variables sin valores.
- Credenciales de terceros solo en `.env`; el código lee `os.environ`.
- Regla §22: las credenciales del proveedor de Hermes no se tocan.

## 2. Prompt injection (§33)
Los documentos recuperados son **datos**, nunca instrucciones:
- `src/kos/security.py` neutraliza patrones clásicos
  (`ignore previous instructions`, `reveal system prompt`, `delete database`, …).
- `fence()` envuelve cada fragmento en `<external_source>…</external_source>`.
- `SYSTEM_FENCE` se inyecta en el system prompt de cada respuesta del router:
  el contenido externo no tiene autoridad sobre las instrucciones del agente.
- Mismo tratamiento para MD, HTML, PDF, transcripciones, datasets y código
  (todo pasa por `parse_to_text` + `sanitize_external` antes de llegar al LLM).

## 3. Validación de entrada
`security.validate_file(path)` impone:
- extensiones permitidas (allowlist; sin ejecutables);
- tamaño máximo 50 MB por archivo;
- rechazo de archivos vacíos.
`validate_text()` limita 4M chars por documento parseado.

## 4. Contenedores y red
- Servicios Docker en red interna `kos-net`; puertos expuestos solo los necesarios.
- MinIO usa credenciales propias (no admin por defecto).
- Qdrant sin API key en local; documentado activarla en despliegue externo.

## 5. Auditoría
- `processing_costs` y `queries_log` registran uso LLM y consultas.
- `processing_errors` guarda fallos del pipeline con retryable flag.
- `hashes` da trazabilidad de dedupe (evita reprocesar contenido idéntico).

## 6. Respaldos (§34)
`make backup` → `pg_dump` + tar (vault, staging, lightrag). Restore con `make restore F=…`.
Los objetos MinIO son inmutables y versionados (v1, v2, …).

## 7. Intrusión en la cola de jobs
Los jobs son idempotentes: re-ejecutar una etapa no duplica datos
(índice único `(doc_id, job_type) WHERE status != 'done'` en `ingestion_jobs`).