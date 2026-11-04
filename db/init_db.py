"""Crea la base de datos SQLite a partir de schema.sql.

Uso:
    python db/init_db.py            # crea db/microcreditos.db si no existe
    python db/init_db.py --reset    # borra y vuelve a crear la base de datos
"""
import argparse
import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DB_DIR / "schema.sql"
DB_PATH = DB_DIR / "microcreditos.db"


def init_db(reset: bool = False) -> Path:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema)
    return DB_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicializa la base de datos de microcréditos")
    parser.add_argument("--reset", action="store_true", help="borra la base de datos existente")
    args = parser.parse_args()

    path = init_db(reset=args.reset)
    with sqlite3.connect(path) as conn:
        tablas = [
            fila[0]
            for fila in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
    print(f"Base de datos lista en {path}")
    print("Tablas:", ", ".join(tablas))


if __name__ == "__main__":
    main()
