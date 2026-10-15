"""Benchmark experimental del pipeline de ingesta.

Compara la ingesta secuencial (1 worker, bucle simple) frente a la
concurrente (p ∈ {2, 4, 8} workers) sobre un conjunto de 10 URLs reales
de tamaño similar, y calcula:

    T_s  : tiempo de ingesta secuencial (base T_1)
    T_p  : tiempo con p workers
    S_p  : aceleración  S_p = T_1 / T_p
    E_p  : eficiencia   E_p = S_p / p

Además desglosa el porcentaje de tiempo por fase (scraping/red,
chunking/CPU, API de embeddings, inserción Supabase) y exporta
JSON/CSV/Markdown + gráficos PNG.

Uso:
    venv/bin/python -m benchmark.benchmark_ingesta                 # real (consume cuota Gemini)
    venv/bin/python -m benchmark.benchmark_ingesta --dry-run       # sin consumir cuota
    venv/bin/python -m benchmark.benchmark_ingesta --workers 1,2,4,8 --limpiar-final
"""
import argparse
import csv
import json
import pathlib
import sys
import time
from datetime import datetime

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

from pipeline.api_ingesta import IngestaWebRequest, ejecutar_pipeline
from pipeline.storage import purgar_coleccion

FASES = ["scraping_red", "chunking_cpu", "api_embeddings", "insercion_supabase"]
ETIQUETAS_FASES = ["Scraping/Red", "Chunking/CPU", "API Embeddings", "Inserción Supabase"]


def cargar_urls(ruta: pathlib.Path) -> list[str]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    urls = datos["urls"] if isinstance(datos, dict) else datos
    return [u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://"))]


def ejecutar_corrida(
    urls: list[str],
    workers: int,
    coleccion: str,
    chunk_size: int,
    chunk_overlap: int,
    dry_run: bool,
    timeout: float,
) -> dict:
    purgar_coleccion(coleccion)
    req = IngestaWebRequest(
        coleccion_id=coleccion,
        urls=urls,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        concurrency_workers=workers,
        dry_run=dry_run,
    )
    t0 = time.perf_counter()
    resp = ejecutar_pipeline(req)
    total_medido = time.perf_counter() - t0

    t = resp.tiempos_s
    fila = {
        "p": workers,
        "modo": resp.modo,
        "coleccion": coleccion,
        "total_s": t["total"],
        "total_wall_s": round(total_medido, 3),
        "scraping_red_s": t["scraping_red"],
        "chunking_cpu_s": t["chunking_cpu"],
        "api_embeddings_s": t["api_embeddings"],
        "insercion_supabase_s": t["insercion_supabase"],
        "chunks": resp.chunks_insertados,
        "urls_ok": resp.urls_ok,
        "urls_fallidas": resp.urls_fallidas,
    }
    for fase in FASES:
        fila[f"pct_{fase}"] = round(100 * t[fase] / t["total"], 2) if t["total"] else 0.0
    return fila


def calcular_metricas(filas: list[dict], p_base: int = 1) -> None:
    fila_base = next((f for f in filas if f["p"] == p_base), None)
    t1 = fila_base["total_s"] if fila_base else (filas[0]["total_s"] if filas else 0.0)
    for f in filas:
        f["speedup"] = round(t1 / f["total_s"], 3) if f["total_s"] else 0.0
        f["eficiencia_pct"] = round(100 * f["speedup"] / f["p"], 2)


def tabla_markdown(filas: list[dict], dry_run: bool) -> str:
    lineas = []
    lineas.append("# Resultados del benchmark de ingesta concurrente\n")
    lineas.append(f"- Modo embeddings: {'**dry-run** (vectores sintéticos)' if dry_run else '**real** (gemini-embedding-001)'}")
    lineas.append(f"- Fecha: {datetime.now().isoformat(timespec='seconds')}")
    lineas.append(f"- URLs: {filas[0]['urls_ok'] + filas[0]['urls_fallidas'] if filas else 0}\n")

    lineas.append("## Tiempos y aceleración\n")
    lineas.append("| p (workers) | Modo | T_p (s) | S_p = T1/T_p | E_p = S_p/p (%) | Chunks |")
    lineas.append("|---|---|---|---|---|---|")
    for f in filas:
        lineas.append(
            f"| {f['p']} | {f['modo']} | {f['total_s']:.2f} | {f['speedup']:.3f} | "
            f"{f['eficiencia_pct']:.1f} | {f['chunks']} |"
        )

    lineas.append("\n## Desglose temporal por fase\n")
    lineas.append("| p | Scraping/Red | Chunking/CPU | API Embeddings | Inserción Supabase |")
    lineas.append("|---|---|---|---|---|")
    for f in filas:
        lineas.append(
            f"| {f['p']} | {f['scraping_red_s']:.2f} s ({f['pct_scraping_red']:.1f}%) | "
            f"{f['chunking_cpu_s']:.2f} s ({f['pct_chunking_cpu']:.1f}%) | "
            f"{f['api_embeddings_s']:.2f} s ({f['pct_api_embeddings']:.1f}%) | "
            f"{f['insercion_supabase_s']:.2f} s ({f['pct_insercion_supabase']:.1f}%) |"
        )
    return "\n".join(lineas) + "\n"


def graficar(filas: list[dict], dir_salida: pathlib.Path, ts: str) -> list[pathlib.Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    generados = []
    ps = [f["p"] for f in filas]
    speedups = [f["speedup"] for f in filas]
    eficiencias = [f["eficiencia_pct"] for f in filas]

    # 1) Speedup vs workers
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(ps, ps, "--", color="#999999", label="Ideal (lineal)")
    ax.plot(ps, speedups, "o-", color="#1f77b4", label="Speedup medido")
    for x, y in zip(ps, speedups):
        ax.annotate(f"{y:.2f}x", (x, y), textcoords="offset points", xytext=(0, 8), ha="center")
    ax.set_xlabel("Workers (p)")
    ax.set_ylabel("S_p = T_1 / T_p")
    ax.set_title("Aceleración (Speedup) vs. número de workers")
    ax.set_xticks(ps)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    ruta = dir_salida / f"speedup_{ts}.png"
    fig.savefig(ruta, dpi=150)
    plt.close(fig)
    generados.append(ruta)

    # 2) Eficiencia vs workers
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar([str(p) for p in ps], eficiencias, color="#2ca02c", alpha=0.85)
    ax.axhline(100, color="#d62728", linestyle="--", label="Eficiencia ideal (100%)")
    for x, y in zip(range(len(ps)), eficiencias):
        ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points", xytext=(0, 4), ha="center")
    ax.set_xlabel("Workers (p)")
    ax.set_ylabel("E_p = S_p / p (%)")
    ax.set_title("Eficiencia paralela vs. número de workers")
    ax.set_ylim(0, max(110, max(eficiencias) * 1.2 if eficiencias else 110))
    ax.grid(alpha=0.3, axis="y")
    ax.legend()
    fig.tight_layout()
    ruta = dir_salida / f"eficiencia_{ts}.png"
    fig.savefig(ruta, dpi=150)
    plt.close(fig)
    generados.append(ruta)

    # 3) Desglose porcentual de fases (barras apiladas)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    colores = ["#4c72b0", "#dd8452", "#55a868", "#c44e52"]
    base = [0.0] * len(filas)
    for fase, etiqueta, color in zip(FASES, ETIQUETAS_FASES, colores):
        valores = [f[f"pct_{fase}"] for f in filas]
        ax.bar([f"p={p}" for p in ps], valores, bottom=base, label=etiqueta, color=color)
        for i, (v, b) in enumerate(zip(valores, base)):
            if v >= 5:
                ax.text(i, b + v / 2, f"{v:.0f}%", ha="center", va="center", color="white", fontsize=8)
        base = [b + v for b, v in zip(base, valores)]
    ax.set_ylabel("Porcentaje del tiempo total (%)")
    ax.set_title("Desglose temporal por fase (% del total)")
    ax.set_ylim(0, 100)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, fontsize=8)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    ruta = dir_salida / f"fases_{ts}.png"
    fig.savefig(ruta, dpi=150)
    plt.close(fig)
    generados.append(ruta)

    return generados


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark de ingesta secuencial vs concurrente")
    ap.add_argument("--urls", default=str(RAIZ / "scripts" / "urls_benchmark.json"))
    ap.add_argument("--workers", default="1,2,4,8", help="Lista de workers separada por comas")
    ap.add_argument("--prefix", default="bench", help="Prefijo de las colecciones de prueba")
    ap.add_argument("--chunk-size", type=int, default=1000)
    ap.add_argument("--chunk-overlap", type=int, default=200)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--dry-run", action="store_true", help="Embeddings sintéticos (no consume cuota)")
    ap.add_argument("--output-dir", default=str(RAIZ / "benchmark" / "resultados"))
    ap.add_argument("--pausa-entre-corridas", type=float, default=5.0)
    ap.add_argument("--limpiar-final", action="store_true", help="Elimina las colecciones de prueba al terminar")
    ap.add_argument("--no-graficos", action="store_true")
    args = ap.parse_args()

    lista_workers = [int(w) for w in args.workers.split(",") if w.strip()]
    urls = cargar_urls(pathlib.Path(args.urls))
    if not urls:
        print("[X] No hay URLs válidas en el archivo indicado.")
        return 1

    dir_salida = pathlib.Path(args.output_dir)
    dir_salida.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"[*] Benchmark de ingesta | URLs: {len(urls)} | workers: {lista_workers} | "
          f"modo: {'dry-run' if args.dry_run else 'real'}")
    print(f"[*] Chunking: size={args.chunk_size}, overlap={args.chunk_overlap}\n")

    filas: list[dict] = []
    for i, p in enumerate(lista_workers):
        coleccion = f"{args.prefix}_p{p}"
        print(f"[>] Corrida p={p} → colección '{coleccion}' ...")
        try:
            fila = ejecutar_corrida(
                urls, p, coleccion, args.chunk_size, args.chunk_overlap, args.dry_run, args.timeout
            )
            filas.append(fila)
            print(f"    [✓] T={fila['total_s']:.2f}s | chunks={fila['chunks']} | "
                  f"urls_ok={fila['urls_ok']}/{fila['urls_ok'] + fila['urls_fallidas']}")
        except Exception as e:
            print(f"    [X] Error en la corrida p={p}: {e}")
        if i < len(lista_workers) - 1 and args.pausa_entre_corridas > 0:
            time.sleep(args.pausa_entre_corridas)
        print()

    if len(filas) < 2:
        print("[X] Se necesitan al menos 2 corridas válidas para calcular métricas.")
        return 1

    calcular_metricas(filas)

    meta = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "urls": urls,
        "workers": lista_workers,
        "chunk_size": args.chunk_size,
        "chunk_overlap": args.chunk_overlap,
        "python": sys.version.split()[0],
    }
    salida = {"meta": meta, "corridas": filas}

    ruta_json = dir_salida / f"benchmark_{ts}.json"
    ruta_csv = dir_salida / f"benchmark_{ts}.csv"
    ruta_md = dir_salida / f"benchmark_{ts}.md"
    ruta_json.write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    ruta_md.write_text(tabla_markdown(filas, args.dry_run), encoding="utf-8")

    campos = list(filas[0].keys())
    with ruta_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=campos)
        writer.writeheader()
        writer.writerows(filas)

    print("[✓] Resultados guardados:")
    print(f"    {ruta_json}")
    print(f"    {ruta_csv}")
    print(f"    {ruta_md}")

    if not args.no_graficos:
        try:
            for ruta in graficar(filas, dir_salida, ts):
                print(f"    {ruta}")
        except Exception as e:
            print(f"    [X] No se pudieron generar los gráficos: {e}")

    print("\n=== RESUMEN ===")
    print(f"{'p':>3} | {'T_p (s)':>9} | {'S_p':>6} | {'E_p (%)':>8}")
    for f in filas:
        print(f"{f['p']:>3} | {f['total_s']:>9.2f} | {f['speedup']:>6.3f} | {f['eficiencia_pct']:>8.1f}")

    if args.limpiar_final:
        for f in filas:
            try:
                purgar_coleccion(f["coleccion"])
                print(f"[✓] Colección '{f['coleccion']}' eliminada.")
            except Exception as e:
                print(f"[X] No se pudo eliminar '{f['coleccion']}': {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
