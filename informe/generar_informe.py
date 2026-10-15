"""Genera el informe final (Markdown + PDF) a partir de un benchmark.

Uso:
    venv/bin/python informe/generar_informe.py                    # último benchmark real
    venv/bin/python informe/generar_informe.py --json <ruta>      # benchmark específico
    venv/bin/python informe/generar_informe.py --solo-md          # sin PDF
"""
import argparse
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
PLANTILLA = pathlib.Path(__file__).parent / "plantilla_informe.md"
RESULTADOS = RAIZ / "benchmark" / "resultados"


def ultimo_benchmark() -> pathlib.Path:
    candidatos = sorted(RESULTADOS.glob("benchmark_*.json"))
    if not candidatos:
        raise SystemExit("[X] No hay benchmarks en benchmark/resultados/")
    return candidatos[-1]


def tabla_rendimiento(corridas: list[dict]) -> str:
    lineas = [
        "| p (workers) | Modo | T_p (s) | S_p = T1/T_p | E_p = S_p/p (%) | Chunks |",
        "|---|---|---|---|---|---|",
    ]
    for f in corridas:
        lineas.append(
            f"| {f['p']} | {f['modo']} | {f['total_s']:.2f} | {f['speedup']:.3f} | "
            f"{f['eficiencia_pct']:.1f} | {f['chunks']} |"
        )
    return "\n".join(lineas)


def tabla_fases(corridas: list[dict]) -> str:
    lineas = [
        "| p | Scraping/Red | Chunking/CPU | API Embeddings | Inserción Supabase |",
        "|---|---|---|---|---|",
    ]
    for f in corridas:
        lineas.append(
            f"| {f['p']} | {f['scraping_red_s']:.2f} s ({f['pct_scraping_red']:.1f}%) | "
            f"{f['chunking_cpu_s']:.2f} s ({f['pct_chunking_cpu']:.1f}%) | "
            f"{f['api_embeddings_s']:.2f} s ({f['pct_api_embeddings']:.1f}%) | "
            f"{f['insercion_supabase_s']:.2f} s ({f['pct_insercion_supabase']:.1f}%) |"
        )
    return "\n".join(lineas)


def imagen(ruta: pathlib.Path, ancho: str = "90%") -> str:
    if not ruta.exists():
        return f"_(gráfico no disponible: {ruta.name})_"
    return f"![{ruta.stem}]({ruta}|width={ancho})"


def analisis_amdahl(corridas: list[dict]) -> str:
    emb = max((f["pct_api_embeddings"] for f in corridas), default=0.0)
    scr = max((f["pct_scraping_red"] for f in corridas), default=0.0)
    mejor_speedup = max((f["speedup"] for f in corridas), default=0.0)
    return (
        f"El desglose evidencia que la fase de **API de embeddings** concentra hasta "
        f"el **{emb:.1f}%** del tiempo total y que el **scraping/red** representa hasta "
        f"el **{scr:.1f}%**. Como la fase de embeddings se ejecuta de forma serializada "
        f"(por el límite de tasa del proveedor externo), su tiempo es una fracción "
        f"no paralelizable *f* que domina el denominador de la Ley de Amdahl:\n\n"
        f"> S(p) = 1 / ((1 - f) + f / p)\n\n"
        f"Aunque el scraping y el chunking escalen casi linealmente con *p*, el Speedup "
        f"observado se estabiliza en torno a **{mejor_speedup:.2f}x** porque el cuello de "
        f"botella es la E/S externa (rate limits / latencia de la API de embeddings) y no "
        f"la capacidad de cómputo local. La eficiencia E_p = S_p/p decae en consecuencia "
        f"al aumentar los workers, confirmando que la aceleración no puede crecer de forma "
        f"sostenida mientras la fase serial permanezca constante. La medición complementaria "
        f"en modo *dry-run* (embeddings sintéticos) permite aislar el paralelismo puro de "
        f"red/CPU del límite impuesto por el tercero."
    )


def construir_md(datos: dict) -> tuple[str, list[str]]:
    meta = datos["meta"]
    corridas = datos["corridas"]
    marca = sorted(RESULTADOS.glob("speedup_*.png"))

    usadas: list[str] = []
    imgs = {}
    if marca:
        base = marca[-1].stem.replace("speedup_", "")
        for nombre, clave in [
            ("speedup", "IMG_SPEEDUP"),
            ("eficiencia", "IMG_EFICIENCIA"),
            ("fases", "IMG_FASES"),
        ]:
            p = RESULTADOS / f"{nombre}_{base}.png"
            imgs[clave] = imagen(p)
            if p.exists():
                usadas.append(str(p))

    md = PLANTILLA.read_text(encoding="utf-8")
    reemplazos = {
        "{{NUM_URLS}}": str(len(meta["urls"])),
        "{{MODO_EMBEDDINGS}}": (
            "vectores sintéticos deterministas (--dry-run)"
            if meta["dry_run"]
            else "real (gemini-embedding-001)"
        ),
        "{{TABLA_RENDIMIENTO}}": tabla_rendimiento(corridas),
        "{{TABLA_FASES}}": tabla_fases(corridas),
        "{{IMG_SPEEDUP}}": imgs.get("IMG_SPEEDUP", "_(sin gráfico)_"),
        "{{IMG_EFICIENCIA}}": imgs.get("IMG_EFICIENCIA", "_(sin gráfico)_"),
        "{{IMG_FASES}}": imgs.get("IMG_FASES", "_(sin gráfico)_"),
        "{{ANALISIS_AMDAHL}}": analisis_amdahl(corridas),
    }
    for clave, valor in reemplazos.items():
        md = md.replace(clave, valor)
    return md, usadas


# --------------------------------------------------------------------------
# Render de Markdown -> PDF con reportlab (subconjunto controlado)
# --------------------------------------------------------------------------
def construir_pdf(md: str, salida: pathlib.Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    base = getSampleStyleSheet()
    estilos = {
        "titulo": ParagraphStyle("titulo", parent=base["Title"], fontSize=16, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=11, spaceBefore=8, spaceAfter=3),
        "p": ParagraphStyle("p", parent=base["BodyText"], fontSize=9, leading=12, alignment=TA_JUSTIFY, spaceAfter=4),
        "bullet": ParagraphStyle("bullet", parent=base["BodyText"], fontSize=9, leading=12, leftIndent=12, bulletIndent=2, spaceAfter=2),
        "code": ParagraphStyle("code", parent=base["Code"], fontSize=7.5, leading=9, textColor=colors.HexColor("#333333")),
    }

    def inline(t: str) -> str:
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", t)
        t = re.sub(r"`(.+?)`", r"<font name=Courier>\1</font>", t)
        return t

    flujo = []
    lineas = md.splitlines()
    i = 0
    ancho_disp = A4[0] - 3.4 * cm

    while i < len(lineas):
        ln = lineas[i].rstrip()
        if not ln.strip():
            i += 1
            continue

        if ln.startswith("```"):
            i += 1
            codigo = []
            while i < len(lineas) and not lineas[i].startswith("```"):
                codigo.append(lineas[i])
                i += 1
            flujo.append(Paragraph("<br/>".join(
                l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(" ", "&nbsp;")
                for l in codigo), estilos["code"]))
            flujo.append(Spacer(1, 4))
            i += 1
            continue

        m_img = re.match(r"!\[.*?\]\((.+?)(?:\|width=(.+?))?\)", ln)
        if m_img:
            ruta = pathlib.Path(m_img.group(1))
            if ruta.exists():
                ancho = m_img.group(2) or "85%"
                fraccion = float(ancho.rstrip("%")) / 100 if ancho.endswith("%") else 0.85
                img = Image(str(ruta))
                img.drawWidth = ancho_disp * fraccion
                img.drawHeight = img.drawHeight * (img.drawWidth / img.imageWidth)
                flujo.append(img)
                flujo.append(Spacer(1, 6))
            i += 1
            continue

        if ln.startswith("|") and i + 1 < len(lineas) and set(lineas[i + 1].replace("|", "").strip()) <= {"-", ":", " "}:
            filas = []
            encabezado = [c.strip() for c in ln.strip("|").split("|")]
            filas.append([Paragraph(f"<b>{inline(c)}</b>", estilos["p"]) for c in encabezado])
            i += 2
            while i < len(lineas) and lineas[i].startswith("|"):
                filas.append([Paragraph(inline(c.strip()), estilos["p"]) for c in lineas[i].strip("|").split("|")])
                i += 1
            tabla = Table(filas, repeatRows=1)
            tabla.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aab4c4")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            flujo.append(tabla)
            flujo.append(Spacer(1, 6))
            continue

        if ln.startswith("# "):
            flujo.append(Paragraph(inline(ln[2:]), estilos["titulo"]))
        elif ln.startswith("## "):
            flujo.append(Paragraph(inline(ln[3:]), estilos["h2"]))
        elif ln.startswith("### "):
            flujo.append(Paragraph(inline(ln[4:]), estilos["h3"]))
        elif ln.startswith("> "):
            flujo.append(Paragraph(f"<i>{inline(ln[2:])}</i>", estilos["p"]))
        elif ln.lstrip().startswith("- "):
            flujo.append(Paragraph(inline(ln.lstrip()[2:]), estilos["bullet"], bulletText="•"))
        else:
            flujo.append(Paragraph(inline(ln), estilos["p"]))
        i += 1

    doc = SimpleDocTemplate(
        str(salida),
        pagesize=A4,
        leftMargin=1.7 * cm, rightMargin=1.7 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title="Informe Pipeline RAG Multi-Dominio",
    )
    doc.build(flujo)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="Ruta al benchmark JSON")
    ap.add_argument("--solo-md", action="store_true", help="No generar PDF")
    args = ap.parse_args()

    ruta_json = pathlib.Path(args.json) if args.json else ultimo_benchmark()
    datos = json.loads(ruta_json.read_text(encoding="utf-8"))
    print(f"[i] Usando benchmark: {ruta_json.name} (dry_run={datos['meta']['dry_run']})")

    md, _ = construir_md(datos)
    salida_md = pathlib.Path(__file__).parent / "informe_pipeline_rag.md"
    salida_md.write_text(md, encoding="utf-8")
    print(f"[✓] Markdown: {salida_md}")

    if not args.solo_md:
        salida_pdf = pathlib.Path(__file__).parent / "informe_pipeline_rag.pdf"
        try:
            construir_pdf(md, salida_pdf)
            print(f"[✓] PDF: {salida_pdf}")
        except Exception as e:
            print(f"[X] No se pudo generar el PDF: {e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
