"""Aplica scripts/schema.sql sobre Supabase/PostgreSQL.

Requiere SUPABASE_DB_URL en el .env:
    SUPABASE_DB_URL=postgresql://postgres:<clave>@<host>:5432/postgres

Si no está definida, imprime las instrucciones para ejecutar el SQL
manualmente en el SQL Editor de Supabase.
"""
import os
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv()

SCHEMA_PATH = pathlib.Path(__file__).with_name("schema.sql")


def main() -> int:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    db_url = os.getenv("SUPABASE_DB_URL")

    if not db_url:
        print("[!] SUPABASE_DB_URL no está definida en el entorno/.env.")
        print()
        print("    Opción A - Automática:")
        print("      Agregar en .env:")
        print("      SUPABASE_DB_URL=postgresql://postgres:<clave>@<host>:5432/postgres")
        print("      (Supabase → Project Settings → Database → Connection string)")
        print("      y luego: venv/bin/python scripts/aplicar_schema.py")
        print()
        print("    Opción B - Manual:")
        print("      Copiar el contenido de scripts/schema.sql y pegarlo en")
        print("      Supabase → SQL Editor → New query → Run.")
        return 1

    try:
        import psycopg
    except ImportError:
        print("[X] psycopg no está instalado.")
        print("    Ejecutar: venv/bin/python -m pip install \"psycopg[binary]\"")
        return 1

    try:
        with psycopg.connect(db_url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
    except Exception as e:
        print(f"[X] Error al aplicar el esquema: {e}")
        return 1

    print("[✓] schema.sql aplicado correctamente (columna coleccion_id, índice B-Tree y RPC match_normativa_coleccion).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
