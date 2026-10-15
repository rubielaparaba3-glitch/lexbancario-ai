"""Fase 4 - Inserción en Supabase por lotes con reintentos.

Todas las filas llevan coleccion_id (aislamiento multi-tenant).
Las inserciones se agrupan en sub-lotes para no saturar PostgREST.
"""
import os
import time
from collections.abc import Sequence

from supabase import Client, create_client

TABLA = "normativa_bancaria"
INSERT_BATCH_SIZE = int(os.getenv("INSERT_BATCH_SIZE", "100"))
MAX_RETRIES = 4

_cliente: Client | None = None


def get_supabase() -> Client:
    global _cliente
    if _cliente is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("Faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY en .env")
        _cliente = create_client(url, key)
    return _cliente


def _es_error_transitorio(e: Exception) -> bool:
    s = str(e).lower()
    return any(
        k in s
        for k in (
            "429", "rate limit", "timeout", "temporarily", "connection",
            "503", "resource_exhausted", "quota", "gateway",
        )
    )


def insertar_filas(
    filas: Sequence[dict],
    batch_size: int | None = None,
) -> int:
    """Inserta filas en sub-lotes con backoff ante errores transitorios."""
    if not filas:
        return 0
    batch_size = batch_size or INSERT_BATCH_SIZE
    sb = get_supabase()
    insertadas = 0
    for i in range(0, len(filas), batch_size):
        lote = list(filas[i : i + batch_size])
        intento = 0
        while True:
            try:
                sb.table(TABLA).insert(lote).execute()
                insertadas += len(lote)
                break
            except Exception as e:
                if _es_error_transitorio(e) and intento < MAX_RETRIES:
                    intento += 1
                    time.sleep(2 ** intento)
                    continue
                raise
    return insertadas


def contar_coleccion(coleccion_id: str) -> int:
    """Devuelve el número de filas de una colección."""
    res = (
        get_supabase()
        .table(TABLA)
        .select("id", count="exact")
        .eq("coleccion_id", coleccion_id)
        .limit(1)
        .execute()
    )
    return int(getattr(res, "count", 0) or 0)


def purgar_coleccion(coleccion_id: str) -> None:
    """Elimina todas las filas de una colección (para re-ejecuciones/benchmark)."""
    get_supabase().table(TABLA).delete().eq("coleccion_id", coleccion_id).execute()


def fetch_coleccion(coleccion_id: str, limit: int = 5) -> list[dict]:
    res = (
        get_supabase()
        .table(TABLA)
        .select("id, documento_origen, coleccion_id")
        .eq("coleccion_id", coleccion_id)
        .limit(limit)
        .execute()
    )
    return res.data or []
