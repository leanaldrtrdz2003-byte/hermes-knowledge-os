# 01_SOURCES — Fuentes

> Corpus y material original ingerido en el Knowledge OS.

## Convenciones
- Cada subcarpeta = dominio (fisica, informatica, matematicas, …).
- Los archivos aquí son las **entradas** del pipeline; el pipeline los copia a
  MinIO (inmutable, versionado) y a `data/staging/`.
- **Nunca se editan** los objetos de MinIO: para corregir, se ingiere una
  versión nueva (nueva fuente con version incrementada, §5).

## Ingesta
```bash
make ingest DIR=data/raw     # o cualquier directorio con .md/.txt/.pdf/.py…
make worker                  # procesa la cola (parse→chunk→embed→index→graph→wiki)
```

## Estado del corpus
- data/raw/fisica/termodinamica-entropia.md
- data/raw/informatica/transformador-atencion.md
- data/raw/matematicas/calculo-integral.md
- data/raw/programacion/python-basico.md