"""Fase 3 - Embeddings por lotes con control de rate limit (429 / RESOURCE_EXHAUSTED).

El envío al modelo se hace en batches configurables. Ante un límite de tasa
se aplica backoff exponencial con jitter (reintentos no bloqueantes: el
endpoint que invoca este módulo corre en el threadpool de FastAPI, por lo que
el event loop queda libre durante las pausas).
"""
import hashlib
import os
import random
import time
from collections.abc import Sequence

from google import genai
from google.genai import types

MODEL_EMBEDDING = "models/gemini-embedding-001"
EMBED_DIM = 768
BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "10"))
BATCH_PAUSE_S = float(os.getenv("EMBED_BATCH_PAUSE_S", "1.0"))
MAX_RETRIES = 6
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 60.0

_cliente: genai.Client | None = None


def _get_client() -> genai.Client:
    global _cliente
    if _cliente is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Falta GEMINI_API_KEY en el entorno/.env")
        _cliente = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=30_000),
        )
    return _cliente


def es_rate_limit(e: Exception) -> bool:
    s = str(e).lower()
    return any(
        k in s
        for k in ("429", "resource_exhausted", "rate limit", "quota", "quota exceeded")
    )


def _embedding_falso(texto: str) -> list[float]:
    """Vector determinista y normalizado (modo --dry-run, sin consumir cuota)."""
    semilla = int.from_bytes(
        hashlib.sha256(texto.encode("utf-8")).digest()[:8], "big"
    )
    rnd = random.Random(semilla)
    vec = [rnd.uniform(-1.0, 1.0) for _ in range(EMBED_DIM)]
    norma = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norma for v in vec]


def generar_embeddings(
    textos: Sequence[str],
    batch_size: int | None = None,
    dry_run: bool = False,
) -> list[list[float]]:
    """Genera los vectores de `textos` respetando batching y rate limits."""
    if dry_run:
        return [_embedding_falso(t) for t in textos]
    if not textos:
        return []

    batch_size = batch_size or BATCH_SIZE
    cliente = _get_client()
    vectores: list[list[float]] = []

    for i in range(0, len(textos), batch_size):
        lote = list(textos[i : i + batch_size])
        intento = 0
        while True:
            try:
                res = cliente.models.embed_content(
                    model=MODEL_EMBEDDING,
                    contents=lote,
                    config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
                )
                vectores.extend([e.values for e in res.embeddings])
                break
            except Exception as e:
                if es_rate_limit(e) and intento < MAX_RETRIES:
                    espera = min(
                        BACKOFF_MAX_S,
                        BACKOFF_BASE_S * (2 ** intento),
                    ) + random.uniform(0.0, 1.0)
                    intento += 1
                    print(
                        f"    [rate-limit] 429/RESOURCE_EXHAUSTED en lote "
                        f"{i // batch_size + 1}: espera {espera:.1f}s "
                        f"(intento {intento}/{MAX_RETRIES})"
                    )
                    time.sleep(espera)
                    continue
                raise
        if BATCH_PAUSE_S > 0:
            time.sleep(BATCH_PAUSE_S)

    if len(vectores) != len(textos):
        raise RuntimeError(
            f"Desajuste de vectores: {len(vectores)} recibidos, {len(textos)} esperados"
        )
    return vectores
