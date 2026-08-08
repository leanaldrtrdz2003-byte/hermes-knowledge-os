# 05_MEMORY — Memoria del agente

> Conocimiento SOBRE el agente, sus proyectos y decisiones (§12) —
> **separado del conocimiento mundial** (que vive en 00_SYSTEM/02_WIKI/04_GRAPH).

## Reglas
1. Aquí SOLO memoria de agente: preferencias, decisiones, contexto de proyectos,
   hechos sobre Maestro, atajos de trabajo.
2. El conocimiento del mundo (ciencia, historia…) NO va aquí: va al corpus/wikis.
3. Backend: `agent_memory` (PG) con tipos `episodic | semantic | procedural |
   decision` e importancia (1-10, §31).

## Gestión
```bash
make memory O="El usuario prefiere respuestas en español."   # persistir
kos memory                                                    # listar
```

## Pipeline de persistencia (§12)
candidato → scoring de importancia → dedupe (dedupe_key) → validación
(información verificable, no alucinada) → persistencia en PG.