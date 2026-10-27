import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path():
    return Path(os.environ.get("VET_DATABASE", "data/vet.db"))


@contextmanager
def db():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS farms (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL, town TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            herd_type TEXT NOT NULL DEFAULT 'mleczne', notes TEXT NOT NULL DEFAULT '',
            is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS animals (
            id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL REFERENCES farms(id),
            ear_tag TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '', breed TEXT NOT NULL DEFAULT '',
            sex TEXT NOT NULL, birth_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'healthy',
            notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL REFERENCES farms(id),
            animal_id INTEGER REFERENCES animals(id), scheduled_at TEXT NOT NULL,
            reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned',
            notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS treatments (
            id INTEGER PRIMARY KEY, animal_id INTEGER NOT NULL REFERENCES animals(id),
            diagnosis TEXT NOT NULL, medication TEXT NOT NULL, dose TEXT NOT NULL,
            vet TEXT NOT NULL, treated_at TEXT NOT NULL, milk_until TEXT NOT NULL,
            meat_until TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL, category TEXT NOT NULL, source_name TEXT NOT NULL,
            source_url TEXT NOT NULL UNIQUE, source_kind TEXT NOT NULL,
            verification TEXT NOT NULL DEFAULT 'unverified', observed_at TEXT NOT NULL,
            published_at TEXT, review_note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS collection_runs (
            id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, status TEXT NOT NULL,
            added INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, action TEXT NOT NULL, entity TEXT NOT NULL,
            entity_id INTEGER, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_animals_farm ON animals(farm_id);
        CREATE INDEX IF NOT EXISTS idx_visits_date ON visits(scheduled_at);
        CREATE INDEX IF NOT EXISTS idx_treatments_animal ON treatments(animal_id);
        """)


def rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def audit(c, action, entity, entity_id=None):
    c.execute("INSERT INTO audit(action,entity,entity_id,created_at) VALUES(?,?,?,?)",
              (action, entity, entity_id, now()))
