"""Fase 2 - Particionamiento de texto (chunking) en ProcessPoolExecutor.

Primitiva de paralelismo: ProcessPoolExecutor (cómputo intensivo / CPU).
`procesar_documento` es una función de nivel de módulo con argumentos
picklables para poder ejecutarse en procesos hijos.
"""
import re
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import urlparse


def chunk_text(texto: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> list[str]:
    """Divide el texto en fragmentos de ~chunk_size caracteres con solape.

    Corta en fronteras naturales (párrafo → línea → palabra) dentro de la
    mitad final de la ventana para no partir oraciones cuando hay solape.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size debe ser mayor que 0")
    texto = re.sub(r"\n{3,}", "\n\n", texto or "").strip()
    if not texto:
        return []
    # El solape se limita a la mitad del tamaño de ventana para garantizar
    # avance estricto en cada iteración (sin bucles infinitos).
    chunk_overlap = max(0, min(chunk_overlap, chunk_size // 2))
    if len(texto) <= chunk_size:
        return [texto]

    cierres = [m.end() for m in re.finditer(r"\n\n", texto)]
    cierres += [m.end() for m in re.finditer(r"\n", texto)]
    cierres.append(len(texto))

    chunks: list[str] = []
    inicio = 0
    while inicio < len(texto):
        limite = min(inicio + chunk_size, len(texto))
        if limite >= len(texto):
            corte = len(texto)
        else:
            # preferir corte dentro de la mitad final de la ventana
            zona_corte = inicio + chunk_size // 2
            corte = next(
                (c for c in cierres if zona_corte <= c <= limite),
                None,
            )
            if corte is None:
                corte = texto.rfind(" ", zona_corte, limite) + 1
                if corte <= zona_corte:
                    corte = limite
        trozo = texto[inicio:corte].strip()
        if trozo:
            chunks.append(trozo)
        if corte >= len(texto):
            break
        inicio = max(corte - chunk_overlap, inicio + 1)
    return chunks


def procesar_documento(tarea: tuple[int, str, str, str, int, int, str]) -> dict:
    """Genera los fragmentos (filas de tabla) de una página descargada.

    Ejecutable en procesos hijos (argumentos y retorno picklables).
    Tarea = (indice, url, titulo, texto, chunk_size, chunk_overlap, coleccion_id)
    """
    indice, url, titulo, texto, chunk_size, chunk_overlap, coleccion_id = tarea
    dominio = urlparse(url).netloc or "desconocido"
    fragmentos = chunk_text(texto, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    base_titulo = titulo or url
    filas = [
        {
            "coleccion_id": coleccion_id,
            "documento_origen": url,
            "organismo": dominio,
            "tipo_norma": "Contenido Web",
            "jerarquia": "NoNormativa",
            "articulo_ref": f"{base_titulo} :: fragmento {i + 1}",
            "contenido": trozo,
        }
        for i, trozo in enumerate(fragmentos)
    ]
    return {"indice": indice, "url": url, "ok": True, "filas": filas}


def chunking_procesos(
    tareas: Sequence[tuple],
    workers: int,
) -> list[dict]:
    """Ejecuta el chunking de todos los documentos en paralelo (o en bucle si workers <= 1)."""
    if not tareas:
        return []
    if workers <= 1 or len(tareas) == 1:
        return [procesar_documento(t) for t in tareas]
    with ProcessPoolExecutor(max_workers=min(workers, len(tareas))) as executor:
        return list(executor.map(procesar_documento, tareas, chunksize=1))
