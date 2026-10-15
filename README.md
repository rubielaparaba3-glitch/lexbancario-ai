# 🏛️ Asistente Normativo RAG - ASFI / Banco Unión

Sistema RAG para consulta y análisis de normativa ASFI y Banco Unión, con
**pipeline de ingesta web concurrente** y **aislamiento vectorial multi-tenant**.

## Arquitectura
- Backend de consultas: FastAPI (`main.py`, puerto 8000)
- Servicio de scraping/ingesta: FastAPI (`scraper_service.py`, puerto 8001)
- Frontend: Streamlit (puerto 8501)
- Vector Store: Supabase / PostgreSQL + pgvector (768 dims)
- Modelos: gemini-flash (generación, `temperature=0.0`) y gemini-embedding-001
- Concurrencia: `ThreadPoolExecutor` (descarga) + `ProcessPoolExecutor` (chunking)
- Ingesta PDF legada: PyMuPDF + Tesseract OCR

## Aislamiento multi-tenant
- Tabla `normativa_bancaria` con columna `coleccion_id VARCHAR(50)` e índice B-Tree.
- RPC `match_normativa_coleccion(...)`: distancia coseno (`<=>`) evaluada
  **únicamente** sobre las tuplas de la colección solicitada (cero contaminación cruzada).
- RPC `match_normativa(...)`: se conserva por compatibilidad, sin filtro.

## Endpoints
- `POST /api/consultar` — consulta RAG (requiere `coleccion_id` obligatorio).
- `POST /api/ingestar-web` — ingesta concurrente de URLs en una colección
  (`coleccion_id`, `urls`, `chunk_size`, `chunk_overlap`, `concurrency_workers`).
- `GET /health` (servicio scraper) — verifica conectividad con Supabase.

## Despliegue con Docker (recomendado)
```bash
cp .env.example .env   # completar claves
docker compose up --build
```
- Backend: http://localhost:8000
- Scraper: http://localhost:8001/health
- Frontend: http://localhost:8501

## Despliegue local
```bash
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
cp .env.example .env   # completar SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY

# 1) Aplicar el esquema (columna coleccion_id + índice + RPC)
venv/bin/python scripts/aplicar_schema.py   # o pegar scripts/schema.sql en Supabase SQL Editor

# 2) Levantar servicios
venv/bin/uvicorn main:app --reload --port 8000           # backend
venv/bin/uvicorn scraper_service:app --reload --port 8001 # scraper
venv/bin/streamlit run app_streamlit.py                   # frontend
```

## Ejemplo de ingesta
```bash
curl -X POST http://localhost:8001/api/ingestar-web \
  -H "Content-Type: application/json" \
  -d '{
    "coleccion_id": "tributaria_bolivia_2026",
    "urls": ["https://sitio1.com/norma1", "https://sitio2.com/norma2"],
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "concurrency_workers": 4
  }'
```

## Métricas de rendimiento paralelo
```bash
# Benchmark real (consume cuota Gemini): T_s, T_p, S_p, E_p y gráficos
venv/bin/python -m benchmark.benchmark_ingesta

# Benchmark sin consumir cuota (vectores sintéticos deterministas)
venv/bin/python -m benchmark.benchmark_ingesta --dry-run
```
Salidas en `benchmark/resultados/` (JSON, CSV, Markdown y gráficos PNG):
speedup vs. workers, eficiencia y desglose porcentual por fase.

## Prueba de aislamiento (cero contaminación cruzada)
```bash
venv/bin/python scripts/test_aislamiento.py
```
