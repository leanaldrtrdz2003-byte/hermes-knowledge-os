# 02_WIKI — Wiki compilada

> Páginas de síntesis generadas automáticamente (§9/§13).

## Reglas de oro
1. **Nunca editar a mano** — cualquier edición se pierde en la siguiente compilación.
2. Se recompila solo cuando cambian sus fuentes (fingerprint de chunks, §13):
   `make wiki`.
3. Cada página lleva frontmatter con `fingerprint`, `source_chunks` (lineage §48)
   y `compiled_at` (fecha ISO).

## Navegación
- `Índice.md` — índice alfabético de páginas.
- Cada página enlaza a sus fuentes (04_GRAPH o 01_SOURCES) cuando aplica.

## Verificación
```bash
make wiki        # compila lo pendiente (incremental)
kos wiki         # alias CLI
```