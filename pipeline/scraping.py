"""Fase 1 - Descarga HTTP concurrente y limpieza de HTML.

Primitiva de paralelismo: ThreadPoolExecutor (I/O intensivo).
Cada URL se resuelve de forma independiente: una URL caída o lenta
no aborta el lote (control de excepciones por URL).
"""
import re
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; LexBancarioRAG/1.0)"
MAX_RETRIES = 3
BACKOFF_BASE_S = 1.5
MIN_TEXTO = 100


@dataclass
class PaginaDescargada:
    url: str
    ok: bool
    texto: str = ""
    titulo: str = ""
    status_code: int | None = None
    bytes_html: int = 0
    error: str | None = None
    duracion_s: float = 0.0


def limpiar_html(html: str) -> tuple[str, str]:
    """Extrae título y texto visible, eliminando ruido de navegación/publicidad."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(
        ["script", "style", "noscript", "svg", "iframe", "nav", "header",
         "footer", "aside", "form", "button", "figure"]
    ):
        tag.decompose()
    raiz = soup.find("main") or soup.find("article") or soup.body or soup
    titulo = soup.title.get_text(strip=True) if soup.title else ""
    lineas = [ln.strip() for ln in raiz.get_text(separator="\n").splitlines()]
    texto = "\n".join(ln for ln in lineas if ln)
    return titulo, re.sub(r"\n{3,}", "\n\n", texto)


def descargar_url(url: str, client: httpx.Client, timeout: float = 20.0) -> PaginaDescargada:
    """Descarga una URL con reintentos/backoff ante 5xx y timeouts."""
    inicio = time.perf_counter()
    ultimo_error = "sin intento"
    for intento in range(MAX_RETRIES):
        try:
            resp = client.get(url, timeout=timeout)
            if resp.status_code >= 500 and intento < MAX_RETRIES - 1:
                ultimo_error = f"HTTP {resp.status_code}"
                time.sleep(BACKOFF_BASE_S * (2 ** intento))
                continue
            resp.raise_for_status()
            titulo, texto = limpiar_html(resp.text)
            if len(texto) < MIN_TEXTO:
                raise ValueError(f"texto extraible insuficiente ({len(texto)} caracteres)")
            return PaginaDescargada(
                url=url,
                ok=True,
                texto=texto,
                titulo=titulo,
                status_code=resp.status_code,
                bytes_html=len(resp.content),
                duracion_s=time.perf_counter() - inicio,
            )
        except Exception as e:
            ultimo_error = f"{type(e).__name__}: {e}"
            if intento < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE_S * (2 ** intento))
    return PaginaDescargada(
        url=url,
        ok=False,
        error=ultimo_error,
        duracion_s=time.perf_counter() - inicio,
    )


def descargar_todas(
    urls: Sequence[str],
    workers: int = 4,
    timeout: float = 20.0,
) -> list[PaginaDescargada]:
    """Descarga las URLs con ThreadPoolExecutor (o en bucle simple si workers <= 1).

    No hay estado compartido mutable: cada worker devuelve su resultado y el
    hilo principal los colecta con as_completed (sin race conditions).
    """
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(follow_redirects=True, headers=headers) as client:
        if workers <= 1:
            return [descargar_url(u, client, timeout=timeout) for u in urls]

        resultados: dict[str, PaginaDescargada] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futuros = {
                executor.submit(descargar_url, u, client, timeout): u for u in urls
            }
            for futuro in as_completed(futuros):
                url = futuros[futuro]
                try:
                    resultados[url] = futuro.result()
                except Exception as e:
                    resultados[url] = PaginaDescargada(
                        url=url, ok=False, error=f"error en worker: {e}"
                    )
        return [resultados[u] for u in urls]
