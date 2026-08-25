from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.config import DATABASE_URL, MYSQL_DB
from app.db import engine
from app.models import Base


def ensure_database_exists() -> None:
    if not DATABASE_URL.startswith("mysql"):
        return

    server_url = DATABASE_URL.rsplit("/", 1)[0] + "/?charset=utf8mb4"
    try:
        server_engine = create_engine(server_url, future=True)
        with server_engine.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            conn.commit()
        print(f"[ok] database `{MYSQL_DB}` is present")
    except OperationalError as exc:
        print("\n[error] could not reach MySQL.")
        print("  Check the MySQL service is running and .env credentials are correct.")
        print(f"  driver said: {exc.orig}\n")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    ensure_database_exists()

    if args.reset:
        confirm = input(f"This will DROP every table in `{MYSQL_DB}`. Type 'yes' to continue: ")
        if confirm.strip().lower() != "yes":
            print("aborted")
            return
        Base.metadata.drop_all(engine)
        print("[ok] existing tables dropped")

    Base.metadata.create_all(engine)

    table_names = sorted(Base.metadata.tables.keys())
    print(f"[ok] {len(table_names)} tables ready:")
    for name in table_names:
        print(f"       - {name}")
    print("\nNext:  python -m scripts.generate_data")


if __name__ == "__main__":
    main()