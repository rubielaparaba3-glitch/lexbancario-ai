"""Genera la GUÍA DE PRÁCTICA en PDF (formato oficial) a partir del benchmark.

Uso:
    venv/bin/python informe/generar_guia.py \
        --nombre "Nombre Apellido" --ru "E123456" --ci "1234567"

Sin --nombre/--ru/--ci usa placeholders entre corchetes.
"""
import argparse
import io
import json
import pathlib

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

RAIZ = pathlib.Path(__file__).resolve().parents[1]
RES = RAIZ / "benchmark" / "resultados"

s = getSampleStyleSheet()
TITULO = ParagraphStyle("t", parent=s["Title"], fontSize=15, leading=19, spaceAfter=6)
H1 = ParagraphStyle("h1", parent=s["Heading1"], fontSize=13, leading=16, spaceBefore=12, spaceAfter=6,
                    textColor=colors.HexColor("#123a6b"))
H2 = ParagraphStyle("h2", parent=s["Heading2"], fontSize=11.5, leading=14, spaceBefore=8, spaceAfter=4,
                    textColor=colors.HexColor("#1f4e79"))
BODY = ParagraphStyle("b", parent=s["BodyText"], fontSize=10, leading=14.5, alignment=TA_JUSTIFY, spaceAfter=6)
CENT = ParagraphStyle("c", parent=s["BodyText"], fontSize=11, leading=16, alignment=TA_CENTER)
CENTB = ParagraphStyle("cb", parent=CENT, fontName="Helvetica-Bold")
BULLET = ParagraphStyle("bu", parent=BODY, leftIndent=14, bulletIndent=4, spaceAfter=3)
CAP = ParagraphStyle("cap", parent=s["BodyText"], fontSize=8.5, leading=11, alignment=TA_CENTER,
                     textColor=colors.HexColor("#555555"), spaceBefore=3, spaceAfter=8)
MONO = ParagraphStyle("mono", parent=BODY, fontName="Courier", fontSize=8, leading=11,
                      backColor=colors.HexColor("#f4f4f4"), borderPadding=5)


def barra():
    return HRFlowable(width="100%", thickness=1, color=colors.HexColor("#123a6b"),
                      spaceBefore=2, spaceAfter=8)


def tabla(datos, anchos, header_bg="#123a6b"):
    t = Table(datos, colWidths=anchos, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef3f9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def imagen(nombre, ancho=15.5):
    ruta = RES / nombre
    if not ruta.exists():
        return Paragraph(f"[Gráfico no disponible: {nombre}]", CAP)
    from PIL import Image as PILImage

    w, h = PILImage.open(ruta).size
    return Image(str(ruta), width=ancho * cm, height=ancho * cm * h / w)


def qr_imagen(url, ancho_cm=3.0):
    """Genera un código QR del enlace del repositorio."""
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=ancho_cm * cm, height=ancho_cm * cm)


def cargar_corridas(ruta_json):
    datos = json.loads(pathlib.Path(ruta_json).read_text(encoding="utf-8"))
    return datos["meta"], datos["corridas"]


def portada(story, args):
    story.append(Spacer(1, 1.0 * cm))
    story.append(Paragraph("FACULTAD DE INGENIERIA DE RECURSOS NATURALES Y TECNOLOGIA", CENTB))
    story.append(Paragraph("CARRERA DE INGENIERIA INFORMATICA", CENTB))
    story.append(Spacer(1, 1.2 * cm))
    story.append(Paragraph("GUÍA DE PRÁCTICA", ParagraphStyle("g", parent=CENT, fontSize=20, leading=24, fontName="Helvetica-Bold")))
    story.append(Spacer(1, 1.4 * cm))
    story.append(Paragraph("ESTUDIANTES:", CENTB))
    story.append(Paragraph(f"&bull; {args.nombre} &nbsp; RU: {args.ru} &nbsp; CI: {args.ci}", CENT))
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph("MATERIA:", CENTB))
    story.append(Paragraph(args.materia, CENT))
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("DOCENTE:", CENTB))
    story.append(Paragraph(args.docente, CENT))
    story.append(Spacer(1, 1.6 * cm))
    story.append(Paragraph(
        "PRÁCTICA DE LABORATORIO: DESPLIEGUE DOCKERIZADO E INGESTA<br/>"
        "CONCURRENTE DE NORMATIVA RAG",
        ParagraphStyle("tt", parent=CENT, fontSize=13.5, leading=18, fontName="Helvetica-Bold"),
    ))
    story.append(Spacer(1, 1.0 * cm))
    story.append(Paragraph(
        f'Repositorio GitHub: <a href="{args.repo}" color="#1155cc"><u>{args.repo}</u></a>',
        ParagraphStyle("repo", parent=CENT, fontSize=10, leading=13),
    ))
    story.append(PageBreak())


def seccion_objetivo(story):
    story.append(Paragraph("1. Objetivo", H1))
    story.append(barra())
    story.append(Paragraph(
        "Desplegar una arquitectura de Recuperación Aumentada de Generación (RAG) mediante "
        "microservicios en Docker, midiendo el impacto computacional del preprocesamiento "
        "documental (chunking/troceado) y la paralelización de lotes (batches) de embeddings "
        "frente a los límites de tasa del proveedor externo.", BODY))
    story.append(Paragraph(
        "Objetivos específicos: (i) garantizar cero contaminación cruzada entre dominios "
        "mediante aislamiento vectorial multi-tenant; (ii) desacoplar las fases de E/S y CPU "
        "con paralelismo (ThreadPoolExecutor + ProcessPoolExecutor); (iii) controlar el batching "
        "y el rate limiting de la API de embeddings; y (iv) evaluar el Speedup, la Eficiencia y "
        "el techo de la Ley de Amdahl.", BODY))


def seccion_evidencias(story):
    story.append(Paragraph("2. Evidencias del Desarrollo", H1))
    story.append(barra())
    story.append(Paragraph("Evidencia 1: Consulta al asistente normativo (Streamlit)", H2))
    story.append(Paragraph(
        "Interfaz Streamlit &laquo;Control Normativo&raquo; (http://localhost:8501) realizando una "
        "consulta sobre normativa bancaria. La respuesta del asistente cita las fuentes recuperadas "
        "(fragmentos con su similitud coseno) exclusivamente de la colección consultada, evidenciando "
        "la trazabilidad y el aislamiento por <font face='Courier'>coleccion_id</font>.", BODY))
    story.append(Paragraph("Evidencia 2: Estructura del proyecto y configuración del entorno", H2))
    story.append(Paragraph(
        "Estructura de <font face='Courier'>lexbancario-ai</font>: entorno virtual, servicios FastAPI "
        "(<font face='Courier'>main.py</font> :8000 y <font face='Courier'>scraper_service.py</font> "
        ":8001), frontend Streamlit, esquema de base de datos "
        "(<font face='Courier'>scripts/schema.sql</font>), pipeline de ingesta "
        "(<font face='Courier'>pipeline/</font>), benchmark "
        "(<font face='Courier'>benchmark/benchmark_ingesta.py</font>) y orquestación "
        "(<font face='Courier'>Dockerfile</font>, <font face='Courier'>docker-compose.yml</font>).", BODY))
    story.append(Paragraph("Evidencia 3: Documentación interactiva de la API REST", H2))
    story.append(Paragraph(
        "Documentación OpenAPI/Swagger generada por FastAPI en http://localhost:8000/docs. Expone "
        "<font face='Courier'>GET /</font> (estado), <font face='Courier'>POST /api/consultar</font> "
        "(consulta RAG filtrada por colección) y, en el servicio scraper, "
        "<font face='Courier'>POST /api/ingestar-web</font> y "
        "<font face='Courier'>GET /health</font>.", BODY))


def seccion_arquitectura(story):
    story.append(Paragraph("3. Arquitectura del flujo concurrente", H1))
    story.append(barra())
    story.append(Paragraph(
        "El endpoint <font face='Courier'>/api/ingestar-web</font> es síncrono (<font face='Courier'>def</font>): "
        "FastAPI lo ejecuta en su threadpool, de modo que el <i>event loop</i> permanece libre durante las "
        "pausas de rate limiting. Sus cuatro fases se cronometran por separado:", BODY))
    filas = [
        ["Fase", "Naturaleza", "Mecanismo", "Métrica"],
        ["1. Scraping / Descarga", "I/O de red", "ThreadPoolExecutor(p)", "scraping_red"],
        ["2. Chunking", "CPU", "ProcessPoolExecutor(p)", "chunking_cpu"],
        ["3. Embeddings", "Red / externo", "batching + backoff (429)", "api_embeddings"],
        ["4. Inserción", "I/O Supabase", "sub-lotes + reintentos", "insercion_supabase"],
    ]
    story.append(tabla(filas, [4.2 * cm, 3.0 * cm, 5.3 * cm, 3.5 * cm]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Con <font face='Courier'>concurrency_workers = 1</font> las fases 1 y 2 se ejecutan en bucle "
        "simple (línea base secuencial T<sub>1</sub>); con p &isin; {2,4,8} se activan los pools. Cada fila "
        "insertada lleva su <font face='Courier'>coleccion_id</font>, y la consulta usa la RPC "
        "<font face='Courier'>match_normativa_coleccion</font>, que evalúa la distancia coseno "
        "(<font face='Courier'>&lt;=&gt;</font>) solo sobre la colección solicitada.", BODY))


def seccion_metricas(story, meta, corridas, ts):
    story.append(Paragraph("4. Métricas de Rendimiento y Paralelización de Lotes", H1))
    story.append(barra())
    story.append(Paragraph("4.1 Análisis de concurrencia vs. rate limiting", H2))
    story.append(Paragraph(
        "La fase de descarga se paraleliza con un ThreadPoolExecutor limitado a "
        "<font face='Courier'>concurrency_workers</font> (1–32; por defecto 4) y el chunking con un "
        "ProcessPoolExecutor. El control de cuota real reside del lado cliente hacia Gemini: los "
        "embeddings se envían en lotes de <font face='Courier'>EMBED_BATCH_SIZE</font> (10) con una "
        "pausa de <font face='Courier'>EMBED_BATCH_PAUSE_S</font> (1 s) y backoff exponencial "
        "(2 s &rarr; 60 s, hasta 6 reintentos) ante 429/RESOURCE_EXHAUSTED.", BODY))
    story.append(Paragraph(
        f"Serie A medida — {len(meta['urls'])} URLs reales, chunk_size={meta['chunk_size']}, "
        f"overlap={meta['chunk_overlap']}, modo embeddings: "
        f"{'sintético (dry-run)' if meta.get('dry_run') else 'real'}:", BODY))
    cab = ["c/p", "T total (s)", "Descarga (s)", "Chunking (s)", "Inserción (s)", "Speedup", "Eficiencia"]
    filas = [cab]
    for c in corridas:
        filas.append([
            str(c["p"]), f"{c['total_s']:.3f}", f"{c['scraping_red_s']:.3f}",
            f"{c['chunking_cpu_s']:.3f}", f"{c['insercion_supabase_s']:.3f}",
            f"{c['speedup']:.3f}", f"{c['eficiencia_pct'] / 100:.3f}",
        ])
    story.append(tabla(filas, [1.5 * cm, 2.6 * cm, 2.6 * cm, 2.5 * cm, 2.6 * cm, 2.0 * cm, 2.2 * cm]))
    story.append(Spacer(1, 6))

    p1 = next((c for c in corridas if c["p"] == 1), corridas[0])
    pmax = max(corridas, key=lambda c: c["p"])
    desc_mejora = p1["scraping_red_s"] / max(min(c["scraping_red_s"] for c in corridas), 1e-9)
    ins_prom = sum(c["insercion_supabase_s"] for c in corridas) / len(corridas)
    f_serial = ins_prom / (sum(c["total_s"] for c in corridas) / len(corridas))
    for txt in [
        f"La descarga (paralelizable) mejora hasta <b>{desc_mejora:.2f}&times;</b> al pasar de 1 a p workers.",
        f"La <b>inserción en Supabase</b> es prácticamente serial y constante (media {ins_prom:.2f} s), "
        f"definiendo una fracción serial medida <b>f &asymp; {f_serial:.2f}</b>.",
        f"El Speedup observado se estabiliza en <b>{pmax['speedup']:.2f}&times;</b> a p={pmax['p']}, muy por "
        f"debajo del ideal lineal ({pmax['p']}&times;), por el cuello de botella de E/S externa.",
        f"La eficiencia E<sub>p</sub> = S<sub>p</sub>/p cae de 1.00 a <b>{pmax['eficiencia_pct'] / 100:.2f}</b> "
        "porque la fracción serial domina al aumentar p.",
        "Aislamiento: las pruebas T1–T5 confirman <b>0 cruces</b> entre colecciones y la ausencia de "
        "antecedentes se declara explícitamente.",
    ]:
        story.append(Paragraph(txt, BULLET, bulletText="\u2022"))

    story.append(Paragraph("4.2 Gráficos", H2))
    story.append(imagen(f"speedup_{ts}.png"))
    story.append(imagen(f"eficiencia_{ts}.png"))
    story.append(imagen(f"fases_{ts}.png"))

    story.append(Paragraph("4.3 Paralelización de lotes (batches) de embeddings", H2))
    for txt in [
        "Embeddings por lotes de 10 fragmentos, modelo <font face='Courier'>models/gemini-embedding-001</font>, "
        "dimensión 768 (pgvector).",
        "Cadencia cliente con backoff exponencial (2 s &rarr; 60 s, jitter, 6 intentos); ante cuota diaria "
        "agotada se aborta la corrida para no invalidar la medición.",
        "Caché de embeddings <b>SHA-256(texto)</b>: con el corpus ya vectorizado, las corridas repetidas "
        "resuelven <b>0 peticiones</b> a la API (pre-warm único, fuera de la ventana T<sub>p</sub>).",
        "Chunking en paralelo con ProcessPoolExecutor, ventana deslizante chunk_size=1000 / overlap=200.",
        "Inserción de resultados por sub-lotes con reintentos ante errores transitorios.",
        "Los embeddings son I/O-bound: paralelizarlos choca con el rate limiting del proveedor, por lo que "
        "conviene procesarlos secuencialmente con cadencia (ver §5).",
    ]:
        story.append(Paragraph(txt, BULLET, bulletText="\u2022"))


def seccion_cpu(story):
    story.append(Paragraph("5. Métricas de Rendimiento (CPU y Memoria)", H1))
    story.append(barra())
    story.append(Paragraph(
        "La ingesta se ejecuta en caliente dentro del contenedor (servicio <i>scraper</i>), mientras se "
        "monitorea el consumo con <font face='Courier'>docker stats lexbancario_scraper lexbancario_backend</font>. "
        "Valores medidos durante una ingesta concurrente (10 URLs, 8 workers):", BODY))
    filas = [
        ["Servicio / fase", "CPU %", "Mem (MiB)", "Observación"],
        ["scraper (ingesta)", "12.99 (pico 70.77)", "99.89 (pico 112.60)", "Threads de red + procesos de chunking"],
        ["backend (reposo)", "0.15", "73.38", "Solo atiende consultas RAG"],
    ]
    story.append(tabla(filas, [4.2 * cm, 3.6 * cm, 3.6 * cm, 4.6 * cm]))
    story.append(Spacer(1, 4))
    for txt in [
        "El servicio <i>backend</i> no define límites de CPU/memoria en docker-compose.yml; el pico de CPU "
        "lo marca la fase de chunking (ProcessPoolExecutor) y la inserción por red.",
        "Los embeddings son <b>I/O-bound</b>: el consumo de CPU es bajo y el proceso queda limitado por la "
        "cuota del proveedor, no por el hardware.",
        "El chunking (CPU) escala con el número de procesos; la descarga lo hace con el número de hilos de red.",
    ]:
        story.append(Paragraph(txt, BULLET, bulletText="\u2022"))


def seccion_fases(story, repo):
    story.append(Paragraph("6. Desarrollo por Fases (1-4)", H1))
    story.append(barra())
    story.append(Paragraph("Fase 1: Clonación y configuración del entorno", H2))
    story.append(Paragraph(
        f"<font face='Courier'>git clone <a href=\"{repo}\" color=\"#1155cc\">{repo}.git</a>"
        " &amp;&amp; cd lexbancario-ai</font>; "
        "<font face='Courier'>cp .env.example .env</font> definiendo "
        "<font face='Courier'>SUPABASE_URL</font>, <font face='Courier'>SUPABASE_SERVICE_ROLE_KEY</font> y "
        "<font face='Courier'>GEMINI_API_KEY</font>.", BODY))
    story.append(Paragraph("Fase 2: Orquestación con Docker", H2))
    story.append(Paragraph(
        "<font face='Courier'>Dockerfile</font> basado en <font face='Courier'>python:3.12-slim</font> con "
        "dependencias de OCR (tesseract-ocr, tesseract-ocr-spa, poppler-utils, libmupdf-dev, gcc). "
        "<font face='Courier'>docker-compose.yml</font> levanta <b>backend</b> (uvicorn main:app :8000), "
        "<b>scraper</b> (uvicorn scraper_service:app :8001) y <b>frontend</b> (streamlit :8501) sobre la red "
        "interna <font face='Courier'>rag_net</font>. Construcción y arranque: "
        "<font face='Courier'>docker compose up --build -d</font>; verificación: backend y scraper en estado "
        "<i>healthy</i> y frontend HTTP 200.", BODY))
    story.append(Paragraph("Fase 3: Ingesta en caliente dentro del contenedor", H2))
    story.append(Paragraph(
        "<font face='Courier'>docker compose exec scraper bash</font> y, dentro del contenedor, ejecución del "
        "pipeline (<font face='Courier'>POST /api/ingestar-web</font>) o del benchmark "
        "(<font face='Courier'>python -m benchmark.benchmark_ingesta</font>). Con Supabase operativo, la "
        "ingesta concurrente se validó de extremo a extremo (10 URLs &rarr; 336 fragmentos descargados, "
        "troceados, vectorizados y insertados).", BODY))
    story.append(Paragraph("Fase 4: Tareas de sistemas paralelos", H2))
    for txt in [
        "<b>Métricas de rendimiento:</b> monitoreo de núcleos y memoria con docker stats (§5).",
        "<b>Concurrencia vs. rate limiting:</b> identificación del cuello de botella entre el cómputo local "
        "de CPU (chunking) y el I/O hacia la API externa (embeddings) / Supabase.",
        "<b>Paralelización de lotes:</b> uso de ThreadPoolExecutor y ProcessPoolExecutor respetando los "
        "intervalos de pausa para no exceder las cuotas de red.",
    ]:
        story.append(Paragraph(txt, BULLET, bulletText="\u2022"))


def seccion_conclusiones(story):
    story.append(Paragraph("7. Conclusiones", H1))
    story.append(barra())
    for txt in [
        "El despliegue dockerizado con red interna aísla backend, scraper y frontend, y reproduce el "
        "entorno de OCR (Tesseract/Poppler) sin instalación local.",
        "La concurrencia acelera las fases de red/CPU: la descarga disminuye con el número de workers y "
        "el chunking con el número de procesos.",
        "La <b>inserción serial</b> y la <b>API de embeddings</b> (rate-limited) acotan la ganancia global "
        "del pipeline (Ley de Amdahl): el Speedup se estabiliza y la eficiencia decae al aumentar p.",
        "Paralelizar no siempre ayuda: los embeddings empeoran con concurrencia porque chocan con el rate "
        "limiting del proveedor; conviene procesarlos secuencialmente con cadencia o con caché.",
        "El aislamiento por <font face='Courier'>coleccion_id</font> evita fugas entre dominios: 0 cruces "
        "en las pruebas de aislamiento (T1–T5).",
        "El chunking es la fase de mayor costo de CPU y el principal candidato a paralelizar respetando "
        "las pausas de cuota.",
    ]:
        story.append(Paragraph(txt, BULLET, bulletText="\u2022"))


def seccion_referencias(story):
    story.append(Paragraph("8. Referencias", H1))
    story.append(barra())
    refs = [
        "Docker Compose. https://docs.docker.com/compose/",
        "FastAPI. https://fastapi.tiangolo.com/",
        "Streamlit. https://docs.streamlit.io/",
        "pgvector (HNSW). https://github.com/pgvector/pgvector",
        "Tesseract OCR. https://github.com/tesseract-ocr/tesseract",
        "PyMuPDF. https://pymupdf.readthedocs.io/",
        "Google Gemini API (embeddings). https://ai.google.dev/",
        "Supabase. https://supabase.com/docs",
        "G. M. Amdahl, Validity of the single processor approach to achieving large-scale computing "
        "capabilities (1967).",
    ]
    for i, r in enumerate(refs, 1):
        story.append(Paragraph(f"{i}. {r}", ParagraphStyle("r", parent=BODY, fontSize=9, leading=12, spaceAfter=2)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(RES / "benchmark_20261015_133100.json"))
    ap.add_argument("--nombre", default="[NOMBRE COMPLETO]")
    ap.add_argument("--ru", default="[RU]")
    ap.add_argument("--ci", default="[CI]")
    ap.add_argument("--materia", default="Sistemas Paralelos")
    ap.add_argument("--docente", default="Ing. Elias Cassal Baldiviezo")
    ap.add_argument("--repo", default="https://github.com/rubielaparaba3-glitch/lexbancario-ai")
    ap.add_argument("--out", default=str(RAIZ / "informe" / "Guia_Practica_RAG.pdf"))
    args = ap.parse_args()

    meta, corridas = cargar_corridas(args.json)
    ts = pathlib.Path(args.json).stem.replace("benchmark_", "")

    doc = SimpleDocTemplate(args.out, pagesize=A4,
                            leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            topMargin=2.0 * cm, bottomMargin=2.0 * cm,
                            title="Guía de Práctica RAG")
    story = []
    portada(story, args)
    seccion_objetivo(story)
    seccion_evidencias(story)
    seccion_arquitectura(story)
    seccion_metricas(story, meta, corridas, ts)
    story.append(PageBreak())
    seccion_cpu(story)
    seccion_fases(story, args.repo)
    seccion_conclusiones(story)
    seccion_referencias(story)

    def pie(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#1155cc"))
        texto = f"Repositorio: {args.repo}"
        ancho = canvas.stringWidth(texto, "Helvetica", 7.5)
        x = A4[0] / 2
        y = 1.0 * cm
        canvas.drawCentredString(x, y, texto)
        canvas.linkURL(
            args.repo, (x - ancho / 2, y - 2, x + ancho / 2, y + 8), relative=0
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=pie, onLaterPages=pie)
    print(f"[✓] PDF: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
