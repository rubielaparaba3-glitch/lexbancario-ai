"""Ejecuta el benchmark real cuando la cuota diaria de Gemini se restablece.

Lanza en segundo plano:
    setsid venv/bin/python -u scripts/agendar_benchmark_real.py > benchmark/agendado.log 2>&1 < /dev/null &

No usa un ping de sondeo (un ping exitoso consume cuota y puede gastar el
último request del día). En su lugar intenta el benchmark real completo con
caché de embeddings (``--cache-embeddings``) y, si falla por 429, espera y
reintenta hasta la fecha límite. Solo si el benchmark termina bien regenera el
informe (a partir del JSON real) y hace commit + push de los artefactos.
"""
import json
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

MAX_ESPERA_H = 8.0
INTERVALO_MIN = 20


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def intentar_benchmark(py: str) -> bool:
    """Ejecuta el benchmark real con caché; True si termina correctamente."""
    r = subprocess.run(
        [py, "-u", "-m", "benchmark.benchmark_ingesta", "--cache-embeddings"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    print(r.stdout, end="", flush=True)
    if r.returncode != 0:
        cola = (r.stderr or "")[-1500:]
        log(f"benchmark falló (rc={r.returncode}); cola de stderr:")
        print(cola, end="", flush=True)
        return False
    return True


def main() -> int:
    log(f"=== scheduler iniciado (PID {os.getpid()}) ===")
    py = sys.executable
    intentos = max(1, int(MAX_ESPERA_H * 60 / INTERVALO_MIN))

    completado = False
    for i in range(intentos):
        log(f"intento de benchmark real ({i + 1}/{intentos})")
        if intentar_benchmark(py):
            completado = True
            break
        if i < intentos - 1:
            log(f"reintento en {INTERVALO_MIN} min (cuota probablemente agotada)")
            time.sleep(INTERVALO_MIN * 60)

    if not completado:
        log("TIMEOUT: no se completó el benchmark real en el tiempo máximo. No se commitea.")
        return 1

    dir_res = RAIZ / "benchmark" / "resultados"
    jsons = sorted(dir_res.glob("benchmark_*.json"))
    if not jsons:
        log("no se encontró ningún JSON de resultados; se aborta.")
        return 1
    ruta_json = jsons[-1]

    try:
        meta = json.loads(ruta_json.read_text(encoding="utf-8")).get("meta", {})
    except (OSError, json.JSONDecodeError):
        meta = {}
    if meta.get("dry_run", True):
        log(f"el JSON {ruta_json.name} es dry-run; se aborta el commit.")
        return 1
    log(f"benchmark real OK -> {ruta_json.name}")

    log("=== regenerando informe ===")
    r2 = subprocess.run(
        [py, str(RAIZ / "informe" / "generar_informe.py"), "--json", str(ruta_json)],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
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
            "data: benchmark real (embeddings cacheados) + informe regenerado",
        ],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    print(r3.stdout, end="", flush=True)
    print(r3.stderr, end="", flush=True)
    env_push = {
        **os.environ,
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=30",
        "GIT_TERMINAL_PROMPT": "0",
    }
    r4 = subprocess.run(
        ["git", "push"], cwd=RAIZ, capture_output=True, text=True, env=env_push, check=False
    )
    print(r4.stdout, end="", flush=True)
    print(r4.stderr, end="", flush=True)

    log("=== proceso completado ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
