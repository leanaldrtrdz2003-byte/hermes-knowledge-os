# Hermes Knowledge OS — Makefile (§42)
PY    := env -u PYTHONPATH .venv/bin/python
CLI   := $(PY) src/kos/cli.py

.PHONY: setup up down health ingest worker query test dashboard wiki graph memory backup restore install

## Instalación reproducible (§42)
setup:
	@echo "== setup: schema PG + MinIO + Qdrant + versiones"
	$(CLI) setup

install: setup

up:
	docker compose up -d
	$(MAKE) setup

down:
	docker compose down

health:
	docker compose ps
	curl -s http://127.0.0.1:11434/api/version && echo " <- ollama OK"

## Ingestión: <make ingest DIR=data/raw>
ingest:
	$(CLI) ingest $(DIR)

worker:
	$(CLI) worker --worker-id w1

## Consulta: <make query Q="...">  (o QUERY para no pisar make internas)
query:
	$(CLI) query "$(Q)"

## Observabilidad
dashboard:
	$(CLI) dashboard

versions:
	$(CLI) versions

## Memoria / wiki / grafo
memory:
	$(CLI) memory "$(O)"

wiki:
	$(CLI) wiki

graph:
	$(CLI) graph

## Test
test:
	$(PY) -m pytest tests -q

## Backup / restore
backup:
	$(CLI) backup

restore:
	$(CLI) restore $(F)