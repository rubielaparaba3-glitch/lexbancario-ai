"""Demostración de aislamiento vectorial multi-tenant (Requerimiento 1).

Ingesta dos colecciones temáticas distintas y verifica que las consultas
quedan estrictamente confinadas a la colección solicitada:

  T1: toda fila devuelta por la RPC filtrada pertenece a la colección pedida.
  T2: ídem para la segunda colección.
  T3: una consulta de un dominio NO recupera filas de otro dominio.
  T4: una colección inexistente devuelve cero filas.
  T5: el endpoint /api/consultar declara explícitamente la ausencia de
      antecedentes sin invocar al LLM cuando la colección está vacía.

Además imprime una sonda comparativa con la RPC antigua SIN filtro
(match_normativa) para evidenciar la contaminación que el filtro evita.
"""
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

from pipeline.api_ingesta import IngestaWebRequest, ejecutar_pipeline
from pipeline.embeddings import generar_embeddings
from pipeline.storage import contar_coleccion, get_supabase

COLECCION_BANCARIA = "demo_bancaria"
COLECCION_TRIBUTARIA = "demo_tributaria"
URLS_BANCARIA = [
    "https://es.wikipedia.org/wiki/Encaje_bancario",
    "https://es.wikipedia.org/wiki/Banca",
]
URLS_TRIBUTARIA = [
    "https://es.wikipedia.org/wiki/Derecho_tributario",
    "https://es.wikipedia.org/wiki/Impuesto",
]
THRESHOLD = 0.35
TOP_K = 5

resultados: list[tuple[str, bool, str]] = []


def registrar(nombre: str, ok: bool, detalle: str) -> None:
    resultados.append((nombre, ok, detalle))
    print(f"  [{'PASS' if ok else 'FAIL'}] {nombre}: {detalle}")


def rpc_coleccion(vector, coleccion: str, threshold: float = THRESHOLD, count: int = TOP_K):
    res = get_supabase().rpc(
        "match_normativa_coleccion",
        {
            "query_embedding": vector,
            "match_threshold": threshold,
            "match_count": count,
            "p_coleccion_id": coleccion,
        },
    ).execute()
    return res.data or []


def rpc_sin_filtro(vector, threshold: float = THRESHOLD, count: int = TOP_K):
    res = get_supabase().rpc(
        "match_normativa",
        {
            "query_embedding": vector,
            "match_threshold": threshold,
            "match_count": count,
        },
    ).execute()
    return res.data or []


def ingestar_si_vacia(coleccion: str, urls: list[str]) -> None:
    if contar_coleccion(coleccion) > 0:
        print(f"  [i] Colección '{coleccion}' ya poblada; se omite la ingesta.")
        return
    print(f"  [i] Ingestando {len(urls)} URLs en '{coleccion}' (embeddings reales)...")
    resp = ejecutar_pipeline(
        IngestaWebRequest(coleccion_id=coleccion, urls=urls, concurrency_workers=4)
    )
    print(f"      {resp.chunks_insertados} chunks insertados, "
          f"urls_ok={resp.urls_ok}/{resp.urls_totales}")


def main() -> int:
    print("=" * 72)
    print("TEST DE AISLAMIENTO VECTORIAL MULTI-TENANT")
    print("=" * 72)

    # 0) Verificar que la RPC filtrada existe
    print("\n[0] Verificando existencia de la RPC match_normativa_coleccion...")
    try:
        rpc_coleccion([0.0] * 768, "__ping__", threshold=2.0, count=1)
    except Exception as e:
        print(f"  [X] La RPC no existe o falló: {e}")
        print("      Ejecuta scripts/schema.sql en Supabase antes de correr este test.")
        return 1
    print("  [✓] RPC disponible.")

    # 1) Poblar colecciones
    print("\n[1] Preparando colecciones de prueba...")
    ingestar_si_vacia(COLECCION_BANCARIA, URLS_BANCARIA)
    ingestar_si_vacia(COLECCION_TRIBUTARIA, URLS_TRIBUTARIA)
    n_a = contar_coleccion(COLECCION_BANCARIA)
    n_b = contar_coleccion(COLECCION_TRIBUTARIA)
    print(f"  [i] Filas: {COLECCION_BANCARIA}={n_a}, {COLECCION_TRIBUTARIA}={n_b}")

    # 2) Embeddings de dos consultas de dominios distintos
    print("\n[2] Generando embeddings de consultas...")
    consulta_bancaria = "¿Qué es el encaje bancario y cómo funciona la banca?"
    consulta_tributaria = "¿Qué es el derecho tributario y cómo se aplican los impuestos?"
    vec_bancaria, vec_tributaria = generar_embeddings([consulta_bancaria, consulta_tributaria])

    # 3) Test de aislamiento T1-T4
    print("\n[3] Verificando aislamiento (la RPC solo debe devolver la colección pedida):")

    res_a = rpc_coleccion(vec_bancaria, COLECCION_BANCARIA)
    registro_ok = all(r.get("coleccion_id") == COLECCION_BANCARIA for r in res_a)
    registrar(
        "T1 consulta bancaria en demo_bancaria",
        bool(res_a) and registro_ok,
        f"{len(res_a)} filas, todas de '{COLECCION_BANCARIA}': {registro_ok}",
    )

    res_b = rpc_coleccion(vec_tributaria, COLECCION_TRIBUTARIA)
    registro_ok = all(r.get("coleccion_id") == COLECCION_TRIBUTARIA for r in res_b)
    registrar(
        "T2 consulta tributaria en demo_tributaria",
        bool(res_b) and registro_ok,
        f"{len(res_b)} filas, todas de '{COLECCION_TRIBUTARIA}': {registro_ok}",
    )

    res_cruzado = rpc_coleccion(vec_tributaria, COLECCION_BANCARIA)
    contaminadas = [r for r in res_cruzado if r.get("coleccion_id") != COLECCION_BANCARIA]
    registrar(
        "T3 consulta tributaria dentro de demo_bancaria (sin contaminación)",
        len(contaminadas) == 0,
        f"{len(res_cruzado)} filas devueltas, {len(contaminadas)} de otro dominio",
    )

    res_inexistente = rpc_coleccion(vec_bancaria, "coleccion_que_no_existe")
    registrar(
        "T4 colección inexistente",
        len(res_inexistente) == 0,
        f"{len(res_inexistente)} filas devueltas (esperado 0)",
    )

    # 4) Sonda comparativa con la RPC SIN filtro (demuestra la contaminación evitada)
    print("\n[4] Sonda comparativa con la RPC antigua SIN filtro:")
    sin_filtro = rpc_sin_filtro(vec_tributaria)
    por_coleccion: dict[str, int] = {}
    for r in sin_filtro:
        cid = r.get("coleccion_id", "sin_columna")
        por_coleccion[cid] = por_coleccion.get(cid, 0) + 1
    print(f"  [i] match_normativa (sin filtro) devolvió {len(sin_filtro)} filas de: {por_coleccion}")
    if len(por_coleccion) > 1:
        print("  [i] Esto evidencia la contaminación cruzada que match_normativa_coleccion elimina.")
    else:
        print("  [i] En este corpus la RPC sin filtro no mezcló dominios en el top-k.")

    # 5) Prueba a nivel de API: sin antecedentes → declaración explícita, sin LLM
    print("\n[5] Prueba del endpoint /api/consultar con colección vacía...")
    try:
        from fastapi.testclient import TestClient

        from main import app

        cliente = TestClient(app)
        resp = cliente.post(
            "/api/consultar",
            json={
                "pregunta": "¿Qué regula la ley completamente inexistente?",
                "coleccion_id": "coleccion_vacia_test",
                "top_k": 3,
                "match_threshold": THRESHOLD,
            },
        )
        cuerpo = resp.json()
        respuesta = cuerpo.get("respuesta", "").lower()
        ok = (
            resp.status_code == 200
            and not cuerpo.get("fuentes")
            and ("información suficiente" in respuesta or "no contiene" in respuesta)
        )
        registrar(
            "T5 /api/consultar declara ausencia de antecedentes",
            ok,
            f"status={resp.status_code}, fuentes={len(cuerpo.get('fuentes', []))}, "
            f"respuesta='{cuerpo.get('respuesta', '')[:80]}...'",
        )
    except Exception as e:
        registrar("T5 endpoint /api/consultar", False, f"error: {e}")

    # Resumen
    print("\n" + "=" * 72)
    fallos = [n for n, ok, _ in resultados if not ok]
    print(f"RESUMEN: {len(resultados) - len(fallos)}/{len(resultados)} pruebas superadas")
    for nombre, ok, detalle in resultados:
        print(f"  {'✓' if ok else '✗'} {nombre}")
    print("=" * 72)
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
