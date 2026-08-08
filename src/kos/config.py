"""Configuración 12-factor del Knowledge OS.

Todo lo configurable vive en .env (ver .env.example). Sin secretos en código.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: str) -> str:
    """Expande ${VAR} y ${VAR:-default} del .env (los loaders de shell no aplican)."""

    def _sub(m: re.Match) -> str:
        name, dflt = m.group(1), m.group(2)
        if os.environ.get(name):
            return os.environ[name]
        if dflt is not None:
            return dflt
        return ""

    return _VAR_RE.sub(_sub, value.replace("$PROJECT_ROOT", str(PROJECT_ROOT)))


def _load_dotenv(path: Path | None = None) -> None:
    """Mini loader de .env (sin dependencias). Las vars ya presentes en env ganan."""
    p = path or PROJECT_ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        v = _expand(v)
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()


def _b(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Settings:
    # ── rutas
    data_dir: Path = Path(_b("DATA_DIR", str(PROJECT_ROOT / "data")))
    obsidian_vault: Path = Path(_b("OBSIDIAN_VAULT_PATH", str(PROJECT_ROOT / "vault")))

    # ── PostgreSQL (control plane)
    pg_host: str = _b("POSTGRES_HOST", "localhost")
    pg_port: str = _b("POSTGRES_PORT", "5432")
    pg_user: str = _b("POSTGRES_USER", "kos")
    pg_password: str = _b("POSTGRES_PASSWORD", "kos")
    pg_database: str = _b("POSTGRES_DB", "knowledge_os")
    pg_dsn: str = _b(
        "POSTGRES_DSN",
        f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_database}",
    )

    # ── Qdrant
    qdrant_url: str = _b("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key: str = _b("QDRANT_API_KEY", "")
    vector_collection: str = _b("QDRANT_COLLECTION", "kos_chunks")

    # ── MinIO (S3)
    s3_endpoint: str = _b("S3_ENDPOINT", "localhost:9000")
    s3_access_key: str = _b("S3_ACCESS_KEY", "minioadmin")
    s3_secret_key: str = _b("S3_SECRET_KEY", "")
    s3_bucket: str = _b("S3_BUCKET", "kos-sources")
    s3_secure: bool = _b("S3_SECURE", "false").lower() == "true"

    # ── LLM (router §22). provider: ollama | openai (openai-compatible)
    llm_provider: str = _b("LLM_PROVIDER", "ollama")
    llm_model: str = _b("LLM_MODEL", "qwen2.5:7b")
    llm_base_url: str = _b("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    llm_api_key: str = _b("LLM_API_KEY", "")
    llm_temperature: float = float(_b("LLM_TEMPERATURE", "0.2"))
    llm_max_tokens: int = int(_b("LLM_MAX_TOKENS", "2048"))
    llm_timeout: int = int(_b("LLM_TIMEOUT", "1200"))
    # ── Fallback del proveedor (misma cadena que Hermes Agent: zen → opencode-go)
    llm_fallback_base_url: str = _b("LLM_FALLBACK_BASE_URL", "")
    llm_fallback_api_key: str = _b("LLM_FALLBACK_API_KEY", "")
    llm_fallback_model: str = _b("LLM_FALLBACK_MODEL", "")

    # ── Embeddings (independientes del LLM: siguen locales por defecto)
    embedding_provider: str = _b("EMBEDDING_PROVIDER", "ollama")
    embedding_model: str = _b("EMBEDDING_MODEL", "bge-m3")
    embedding_base_url: str = _b("EMBEDDING_BASE_URL", "http://127.0.0.1:11434/v1")
    embedding_dimension: int = int(_b("EMBEDDING_DIMENSION", "1024"))
    embedding_batch: int = int(_b("EMBEDDING_BATCH", "32"))

    # ── Chunking
    chunk_size: int = int(_b("CHUNK_SIZE_TOKENS", "1200"))
    chunk_overlap: int = int(_b("CHUNK_OVERLAP_TOKENS", "100"))

    # ── Reranker (opcional §24)
    reranker_enabled: bool = _b("RERANKER_ENABLED", "false").lower() == "true"
    reranker_model: str = _b("RERANKER_MODEL", "")

    # ── Pipeline
    workers: int = int(_b("WORKERS", "2"))
    log_level: str = _b("LOG_LEVEL", "INFO")
    tenant: str = _b("KOS_TENANT", "default")

    # ── Jobs
    job_poll_seconds: float = float(_b("JOB_POLL_SECONDS", "2.0"))

    @property
    def vault_path(self) -> Path:
        """Alias conveniente para el vault de Obsidian."""
        return self.obsidian_vault


settings = Settings()