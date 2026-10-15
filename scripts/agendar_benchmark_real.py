"""Ejecuta el benchmark real cuando la cuota diaria de Gemini se restablece.

Lanza en segundo plano:
    setsid venv/bin/python -u scripts/agendar_benchmark_real.py > benchmark/agendado.log 2>&1 < /dev/null &

Sondea la cuota cada 15 min (pings rechazados no consumen cuota). Cuando la
cuota está disponible, ejecuta el benchmark real, regenera el informe y hace
commit + push de los artefactos.
"""
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RAIZ / ".env")

import httpx  # noqa: E402

URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-embedding-001:embedContent"
)
MAX_ESPERA_H = 8.0
INTERVALO_MIN = 15


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def cuota_ok() -> bool:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log("Falta GEMINI_API_KEY en .env")
        return False
    try:
        r = httpx.post(
            URL,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "content": {"parts": [{"text": "ping agendado"}]},
                "outputDimensionality": 768,
            },
            timeout=30,
        )
        if r.status_code == 200:
            return True
        log(f"cuota agotada (HTTP {r.status_code})")
        return False
    except Exception as e:
        log(f"error de red en sondeo: {type(e).__name__}")
        return False


def main() -> int:
    log(f"=== scheduler iniciado (PID {os.getpid()}) ===")
    py = sys.executable
    intentos = int(MAX_ESPERA_H * 60 / INTERVALO_MIN)

    for i in range(intentos):
        if cuota_ok():
            log("cuota disponible -> lanzando benchmark real")
            break
        log(f"esperando reset de cuota ({i + 1}/{intentos}); reintento en {INTERVALO_MIN} min")
        time.sleep(INTERVALO_MIN * 60)
    else:
        log("TIMEOUT: la cuota no se restableció en el tiempo máximo.")
        return 1

    log("=== benchmark real (embeddings gemini-embedding-001) ===")
    r1 = subprocess.run(
        [py, "-u", "-m", "benchmark.benchmark_ingesta"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    print(r1.stdout, end="", flush=True)
    if r1.returncode != 0:
        log("benchmark devolvió error; stderr:")
        print(r1.stderr, end="", flush=True)

    log("=== regenerando informe ===")
    r2 = subprocess.run(
        [py, str(RAIZ / "informe" / "generar_informe.py")],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    print(r2.stdout, end="", flush=True)
    print(r2.stderr, end="", flush=True)

    log("=== commit + push de artefactos ===")
    subprocess.run(["git", "add", "benchmark/resultados"], cwd=RAIZ, check=False)
    subprocess.run(["git", "add", "informe"], cwd=RAIZ, check=False)
    subprocess.run(
        ["git", "add", "-f", "informe/informe_pipeline_rag.pdf"], cwd=RAIZ, check=False
    )
    r3 = subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "data: benchmark real con embeddings gemini-embedding-001 + informe regenerado",
        ],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    print(r3.stdout, end="", flush=True)
    print(r3.stderr, end="", flush=True)
    r4 = subprocess.run(["git", "push"], cwd=RAIZ, capture_output=True, text=True)
    print(r4.stdout, end="", flush=True)
    print(r4.stderr, end="", flush=True)

    log("=== proceso completado ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
