"""Router LLM del Knowledge OS (§22).

Un único punto de entrada para generar texto con:
  - proveedor local  (ollama)            → coste 0
  - proveedor API    (openai-compatible) → modelos baratos configurados en .env

Todas las llamadas registran tokens/coste en PostgreSQL (processing_costs, §31).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx

from kos.config import settings

log = logging.getLogger("kos.llm")


class LLMError(RuntimeError):
    pass


async def complete(prompt: str, *, system: str | None = None,
                   model: str | None = None, temperature: float | None = None,
                   max_tokens: int | None = None, stage: str = "llm",
                   job_id: str | None = None, json_mode: bool = False) -> str:
    """Genera texto con el proveedor activo. Retorna el contenido textual."""
    from kos import db  # import tardío para evitar ciclos
    model = model or settings.llm_model
    temperature = settings.llm_temperature if temperature is None else temperature
    max_tokens = max_tokens or settings.llm_max_tokens
    t0 = time.time()
    try:
        if settings.llm_provider == "ollama":
            text, inp, out = await _ollama_chat(prompt, system, model, temperature, max_tokens, json_mode)
        else:
            text, inp, out = await _openai_chat(prompt, system, model, temperature, max_tokens, json_mode)
    except Exception as exc:  # noqa: BLE001
        # Fallback a la cadena de Hermes: opencode-zen → opencode-go (§22)
        if settings.llm_fallback_base_url and settings.llm_fallback_api_key:
            log.warning("LLM %s/%s falló (%s); fallback → %s", settings.llm_provider, model, exc,
                        settings.llm_fallback_model)
            try:
                text, inp, out = await _openai_chat(
                    prompt, system, settings.llm_fallback_model, temperature, max_tokens, json_mode,
                    _base_url=settings.llm_fallback_base_url, _api_key=settings.llm_fallback_api_key,
                )
                model = settings.llm_fallback_model
            except Exception as exc2:  # noqa: BLE001
                log.exception("fallback %s también falló", settings.llm_fallback_model)
                raise LLMError(f"LLM {settings.llm_provider}/{model} y fallback {settings.llm_fallback_model}: {exc2}") from exc2
        else:
            log.exception("LLM falló (%s/%s)", settings.llm_provider, model)
            raise LLMError(f"LLM {settings.llm_provider}/{model}: {exc}") from exc
    # registro de coste (estimación §31: USD por 1M tokens)
    cost = inp * 0.000_000_15 + out * 0.000_000_60  # tarifa genérica barata
    await db.log_cost(stage, settings.llm_provider, model, inp, out, cost, job_id)
    log.debug("LLM %s: in=%d out=%d (%.2fs)", model, inp, out, time.time() - t0)
    return text


async def _ollama_chat(prompt: str, system: str | None, model: str,
                       temperature: float, max_tokens: int, json_mode: bool) -> tuple[str, int, int]:
    url = settings.llm_base_url.replace("/v1", "") + "/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=settings.llm_timeout) as cli:
        r = await cli.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    msg = data["message"]["content"]
    usage = data.get("prompt_eval_count", 0), data.get("eval_count", 0)
    return msg, usage[0], usage[1]


async def _openai_chat(prompt: str, system: str | None, model: str,
                       temperature: float, max_tokens: int, json_mode: bool,
                       _base_url: str | None = None, _api_key: str | None = None) -> tuple[str, int, int]:
    base_url = (_base_url or settings.llm_base_url).rstrip("/")
    headers = {"Authorization": f"Bearer {_api_key or settings.llm_api_key}"}
    body: dict[str, Any] = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=settings.llm_timeout) as cli:
        r = await cli.post(base_url + "/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"], data["usage"]["prompt_tokens"], data["usage"]["completion_tokens"]


async def extract_json(prompt: str, *, system: str | None = None, model: str | None = None,
                       stage: str = "extract", job_id: str | None = None) -> dict:
    """Prompt → JSON robusto (con recuperación si el modelo escupe markdown)."""
    text = await complete(prompt, system=system, model=model, stage=stage,
                          job_id=job_id, json_mode=True)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text[text.index("{"): text.rindex("}") + 1])