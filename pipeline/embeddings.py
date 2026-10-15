"""Fase 3 - Embeddings por lotes con control de rate limit (429 / RESOURCE_EXHAUSTED).

El envío al modelo se hace en batches configurables. Ante un límite de tasa
se aplica backoff exponencial con jitter (reintentos no bloqueantes: el
endpoint que invoca este módulo corre en el threadpool de FastAPI, por lo que
el event loop queda libre durante las pausas).
"""
import hashlib
import json
import os
import pathlib
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


# ---------------------------------------------------------------
# Caché opcional de embeddings (clave = sha256 del texto).
# Se activa fijando EMBED_CACHE_FILE (ruta del archivo de caché). Permite
# reutilizar vectores entre corridas del benchmark sin volver a consumir
# cuota de la API externa.
# ---------------------------------------------------------------
_CACHE: dict[str, list[float]] = {}
_CACHE_CARGADA = False


def _cache_file() -> pathlib.Path | None:
    ruta = os.getenv("EMBED_CACHE_FILE")
    return pathlib.Path(ruta) if ruta else None


def _clave_cache(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _cargar_cache() -> None:
    global _CACHE, _CACHE_CARGADA
    if _CACHE_CARGADA:
        return
    _CACHE_CARGADA = True
    ruta = _cache_file()
    if ruta and ruta.exists():
        try:
            _CACHE = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _CACHE = {}


def _guardar_cache() -> None:
    ruta = _cache_file()
    if ruta is not None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(_CACHE), encoding="utf-8")


def _embed_lote(
    cliente: genai.Client, lote: list[str], numero_lote: int
) -> list[list[float]]:
    intento = 0
    while True:
        try:
            res = cliente.models.embed_content(
                model=MODEL_EMBEDDING,
                contents=lote,
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
            )
            return [e.values for e in res.embeddings]
        except Exception as e:
            if es_rate_limit(e) and intento < MAX_RETRIES:
                espera = min(
                    BACKOFF_MAX_S, BACKOFF_BASE_S * (2 ** intento)
                ) + random.uniform(0.0, 1.0)
                intento += 1
                print(
                    f"    [rate-limit] 429/RESOURCE_EXHAUSTED en lote "
                    f"{numero_lote}: espera {espera:.1f}s (intento {intento}/{MAX_RETRIES})"
                )
                time.sleep(espera)
                continue
            raise


def generar_embeddings(
    textos: Sequence[str],
    batch_size: int | None = None,
    dry_run: bool = False,
) -> list[list[float]]:
    """Genera los vectores de `textos` respetando batching y rate limits.

    Si la variable de entorno ``EMBED_CACHE_FILE`` está definida, se usa un
    caché en disco (clave = sha256 del texto): los textos ya cacheados se
    reutilizan sin consumir cuota de la API. Así el benchmark puede repetir
    corridas sobre el mismo corpus gastando solo el coste de la primera vez.
    """
    if dry_run:
        return [_embedding_falso(t) for t in textos]
    if not textos:
        return []

    batch_size = batch_size or BATCH_SIZE
    usar_cache = _cache_file() is not None
    if usar_cache:
        _cargar_cache()

    claves = [_clave_cache(t) for t in textos]
    vectores: list[list[float] | None] = [None] * len(textos)
    pendientes: list[tuple[int, str]] = []
    for i, (texto, clave) in enumerate(zip(textos, claves)):
        if usar_cache and clave in _CACHE:
            vectores[i] = _CACHE[clave]
        else:
            pendientes.append((i, texto))

    if pendientes:
        cliente = _get_client()
        for start in range(0, len(pendientes), batch_size):
            lote = pendientes[start : start + batch_size]
            generados = _embed_lote(
                cliente,
                [t for _, t in lote],
                start // batch_size + 1,
            )
            for (idx, _), vec in zip(lote, generados):
                vectores[idx] = vec
                if usar_cache:
                    _CACHE[claves[idx]] = vec
            if BATCH_PAUSE_S > 0:
                time.sleep(BATCH_PAUSE_S)
        if usar_cache:
            _guardar_cache()

    if any(v is None for v in vectores):
        raise RuntimeError("Desajuste de vectores: faltan embeddings por calcular")
    return [v for v in vectores if v is not None]
