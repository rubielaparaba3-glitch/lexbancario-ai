"""Microservicio de ingesta web concurrente (servicio 'scraper' del docker-compose).

Expone POST /api/ingestar-web en el puerto 8001 y /health como sonda
de salud que verifica la conectividad con Supabase.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pipeline.api_ingesta import router as ingesta_router

app = FastAPI(
    title="Scraper Concurrente - Pipeline RAG Multi-Dominio",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingesta_router)


@app.get("/")
def raiz():
    return {
        "servicio": "scraper-concurrente",
        "endpoints": ["POST /api/ingestar-web", "GET /health"],
    }


@app.get("/health")
def health():
    """Sonda de salud: verifica credenciales y conectividad con Supabase."""
    import os

    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=503, detail="Falta GEMINI_API_KEY")
    try:
        from pipeline.storage import get_supabase

        get_supabase().table("normativa_bancaria").select("id").limit(1).execute()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Supabase no responde: {e}")
    return {"status": "ok", "supabase": "ok"}
