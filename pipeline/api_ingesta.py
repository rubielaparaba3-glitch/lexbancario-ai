"""Endpoint POST /api/ingestar-web y orquestador del pipeline concurrente.

Fases del pipeline (cronometradas individualmente):
  1. Scraping/Red        → ThreadPoolExecutor  (o bucle simple si workers <= 1)
  2. Chunking/CPU        → ProcessPoolExecutor (o bucle simple si workers <= 1)
  3. API Embeddings      → lotes secuenciales con backoff ante 429
  4. Inserción Supabase  → sub-lotes con reintentos

El endpoint es síncrono (def): FastAPI lo ejecuta en su threadpool,
por lo que el event loop no se bloquea con los sleeps de rate limiting.
"""
import re
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from pipeline.chunking import chunking_procesos
from pipeline.embeddings import generar_embeddings
from pipeline.scraping import descargar_todas
from pipeline.storage import insertar_filas

router = APIRouter()

PATRON_COLECCION = re.compile(r"^[A-Za-z0-9_\-]{1,50}$")


class IngestaWebRequest(BaseModel):
    coleccion_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Etiqueta de colección / namespace multi-tenant (letras, números, '_' o '-')",
    )
    urls: list[str] = Field(..., min_length=1, max_length=100)
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=4000)
    concurrency_workers: int = Field(default=4, ge=1, le=32)
    dry_run: bool = Field(
        default=False,
        description="Embeddings deterministas sintéticos (pruebas de paralelismo sin consumir cuota Gemini)",
    )

    @field_validator("coleccion_id")
    @classmethod
    def _validar_coleccion(cls, v: str) -> str:
        if not PATRON_COLECCION.match(v):
            raise ValueError(
                "coleccion_id solo puede contener letras, números, '_' o '-' (máx. 50 caracteres)"
            )
        return v

    @field_validator("urls")
    @classmethod
    def _validar_urls(cls, v: list[str]) -> list[str]:
        for u in v:
            if not u.startswith(("http://", "https://")):
                raise ValueError(f"URL inválida (debe comenzar con http:// o https://): {u}")
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def _validar_overlap(cls, v: int, info) -> int:
        cs = info.data.get("chunk_size")
        if cs is not None and v >= cs:
            raise ValueError("chunk_overlap debe ser menor que chunk_size")
        return v


class UrlResultado(BaseModel):
    url: str
    ok: bool
    status_code: int | None = None
    chunks_generados: int = 0
    error: str | None = None
    duracion_descarga_s: float = 0.0


class IngestaWebResponse(BaseModel):
    coleccion_id: str
    urls_totales: int
    urls_ok: int
    urls_fallidas: int
    chunks_insertados: int
    concurrency_workers: int
    modo: str
    dry_run: bool
    tiempos_s: dict[str, float]
    urls: list[UrlResultado]


def ejecutar_pipeline(req: IngestaWebRequest) -> IngestaWebResponse:
    """Ejecuta las 4 fases del pipeline cronometrando cada una."""
    # ---- Fase 1: scraping (red / I/O intensivo) ----
    t0 = time.perf_counter()
    paginas = descargar_todas(req.urls, workers=req.concurrency_workers)
    t_scraping = time.perf_counter() - t0

    ok_pages = [p for p in paginas if p.ok]

    # ---- Fase 2: chunking (CPU intensivo, fuera del proceso principal) ----
    t0 = time.perf_counter()
    tareas = [
        (i, p.url, p.titulo, p.texto, req.chunk_size, req.chunk_overlap, req.coleccion_id)
        for i, p in enumerate(ok_pages)
    ]
    resultados = chunking_procesos(tareas, workers=req.concurrency_workers)
    filas = [fila for r in resultados for fila in r["filas"]]
    chunks_por_url: dict[str, int] = {}
    for r in resultados:
        chunks_por_url[r["url"]] = len(r["filas"])
    t_chunking = time.perf_counter() - t0

    # ---- Fase 3: embeddings (API externa, batching + rate limit) ----
    t0 = time.perf_counter()
    textos = [f["contenido"] for f in filas]
    vectores = generar_embeddings(textos, dry_run=req.dry_run)
    t_embeddings = time.perf_counter() - t0

    filas_completas = [{**f, "embedding": v} for f, v in zip(filas, vectores)]

    # ---- Fase 4: inserción en Supabase (sub-lotes + reintentos) ----
    t0 = time.perf_counter()
    insertadas = insertar_filas(filas_completas)
    t_insercion = time.perf_counter() - t0

    total = t_scraping + t_chunking + t_embeddings + t_insercion
    modo = (
        "secuencial (bucle simple, 1 worker)"
        if req.concurrency_workers <= 1
        else f"paralelo ({req.concurrency_workers} workers)"
    )

    return IngestaWebResponse(
        coleccion_id=req.coleccion_id,
        urls_totales=len(paginas),
        urls_ok=len(ok_pages),
        urls_fallidas=len(paginas) - len(ok_pages),
        chunks_insertados=insertadas,
        concurrency_workers=req.concurrency_workers,
        modo=modo,
        dry_run=req.dry_run,
        tiempos_s={
            "scraping_red": round(t_scraping, 3),
            "chunking_cpu": round(t_chunking, 3),
            "api_embeddings": round(t_embeddings, 3),
            "insercion_supabase": round(t_insercion, 3),
            "total": round(total, 3),
        },
        urls=[
            UrlResultado(
                url=p.url,
                ok=p.ok,
                status_code=p.status_code,
                chunks_generados=chunks_por_url.get(p.url, 0),
                error=p.error,
                duracion_descarga_s=round(p.duracion_s, 3),
            )
            for p in paginas
        ],
    )


@router.post(
    "/api/ingestar-web",
    response_model=IngestaWebResponse,
    summary="Ingesta concurrente de una lista de URLs en una colección",
)
def ingestar_web(req: IngestaWebRequest) -> IngestaWebResponse:
    """Recibe URLs + coleccion_id y ejecuta el pipeline concurrente completo.

    El scraping se resuelve con ThreadPoolExecutor y el chunking con
    ProcessPoolExecutor; los embeddings se envían por lotes con backoff
    exponencial ante 429 y las filas se insertan en sub-lotes, todo
    etiquetado con la colección solicitada.
    """
    return ejecutar_pipeline(req)
