"""
Postgres (OLTP) + DuckDB (OLAP) ETL adapter.

Architecture:
  - Postgres handles all game writes (ticks, inputs, mobs updates).
  - An in-memory DuckDB database is refreshed from Postgres every ETL_INTERVAL
    seconds (configurable via the ETL_INTERVAL env var).
  - Render/analytics queries run against DuckDB

Environment variables:
  PG_ETL_HOST_PORT  Postgres host port (default 55432)
  PG_ETL_IMAGE      Docker image (default postgres:latest)
  ETL_INTERVAL      Seconds between ETL snapshots (default 1.0)
"""

import os, re, socket, subprocess, threading, time
import duckdb, psycopg
from pathlib import Path
from .base import DBAdapter, SQL_DIR, _kill_containers_on_port

_DUCK_OVERRIDES = Path(__file__).resolve().parent.parent / "overrides" / "duckdb"

PG_PORT      = int(os.environ.get("PG_ETL_HOST_PORT", "55432"))
PG_IMAGE     = os.environ.get("PG_ETL_IMAGE",      "postgres:18")
PG_DATA_DIR  = os.environ.get("PG_ETL_DATA_DIR",   "")
ETL_INTERVAL = float(os.environ.get("ETL_INTERVAL", "1.0"))

_STATIC_TABLES = ("map", "config", "settings", "sprites", "sprite_pixels")
_LIVE_TABLES   = ("mobs", "players")


def _pg_conn():
    c = psycopg.connect(dbname="postgres", user="postgres", password="postgres",
                        host="localhost", port=PG_PORT,
                        cursor_factory=psycopg.ClientCursor)
    c.autocommit = True
    return c


def _duck_split(sql: str):
    # Strip -- line comments first so semicolons inside comments don't split statements
    no_comments = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _duck_schema_sql() -> str:
    """Base schema with FK references and GENERATED ALWAYS AS IDENTITY stripped."""
    p = _DUCK_OVERRIDES / "schema.sql"
    if not p.exists():
        p = SQL_DIR / "schema.sql"
    sql = p.read_text(encoding="utf8")
    sql = re.sub(r"\s+GENERATED ALWAYS AS IDENTITY", "", sql)
    return sql


class _DuckCursor:
    """Thin wrapper that translates psycopg2-style %s → DuckDB-style ? placeholders."""

    def __init__(self, duck_conn):
        self._c = duck_conn
        self.description = None

    def execute(self, sql, params=None):
        if params is not None:
            sql = sql.replace("%s", "?")
        self._c.execute(sql, params)
        self.description = self._c.description

    def fetchall(self):
        return self._c.fetchall()

    def close(self):
        try:
            self._c.close()
        except Exception:
            pass


class Adapter(DBAdapter):
    NAME      = "PostgreSQL + DuckDB ETL"
    OVERRIDES = None   # Postgres uses standard SQL

    def __init__(self):
        self.cid         = None
        self._duck_db    = None   # shared in-memory DuckDB database
        self._etl_stop   = threading.Event()
        self._etl_thread = None

    # ---- lifecycle ----

    def start(self):
        _kill_containers_on_port(PG_PORT)
        import shutil
        args = [
            "docker", "run", "-d", "--rm",
            "-e", "POSTGRES_PASSWORD=postgres",
            "-p", f"{PG_PORT}:5432",
        ]
        if PG_DATA_DIR:
            shutil.rmtree(PG_DATA_DIR, ignore_errors=True)
            os.makedirs(PG_DATA_DIR)
            args += ["-v", f"{PG_DATA_DIR}:/var/lib/postgresql"]
        args.append(PG_IMAGE)
        self.cid = subprocess.check_output(args, text=True).strip()

    def wait_ready(self, timeout=300):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("localhost", PG_PORT), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        super().wait_ready(timeout=max(1, int(deadline - time.time())))

    def stop(self):
        self._etl_stop.set()
        if self._etl_thread:
            self._etl_thread.join(timeout=5)
            self._etl_thread = None
        if self._duck_db:
            try:
                self._duck_db.close()
            except Exception:
                pass
            self._duck_db = None
        if self.cid:
            subprocess.call(["docker", "rm", "-f", self.cid],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.cid = None

    # ---- connections ----

    def new_connection(self):
        """Postgres connection for OLTP (game ticks, writes)."""
        conn = _pg_conn()
        return conn, conn.cursor()

    def new_olap_connection(self):
        """DuckDB read connection for OLAP (render / analytics queries)."""
        duck_conn = self._duck_db.cursor()
        cur = _DuckCursor(duck_conn)
        return duck_conn, cur

    # ---- after_prepare hook ----

    def after_prepare(self):
        """Bootstrap in-memory DuckDB from Postgres and launch the ETL thread."""
        self._duck_db = duckdb.connect(":memory:")
        self._bootstrap_duck()
        self._etl_stop.clear()
        self._etl_thread = threading.Thread(
            target=self._etl_loop, daemon=True, name="pg-duckdb-etl"
        )
        self._etl_thread.start()
        print(f"  [ETL] DuckDB bootstrapped; syncing every {ETL_INTERVAL}s")

    # ---- DuckDB bootstrap ----

    def _duck_sql(self, fname: str) -> str:
        """Load SQL for DuckDB, preferring the duckdb override if one exists."""
        override = _DUCK_OVERRIDES / fname
        if override.exists():
            return override.read_text(encoding="utf8")
        return (SQL_DIR / fname).read_text(encoding="utf8")

    def _bootstrap_duck(self):
        cur = self._duck_db

        for stmt in _duck_split(_duck_schema_sql()):
            try:
                cur.execute(stmt)
            except Exception as e:
                raise RuntimeError(f"DuckDB schema error:\n{stmt!r}") from e

        for fname in ("sprites/player.sql", "sprites/slug.sql", "renderer.sql"):
            for stmt in _duck_split(self._duck_sql(fname)):
                try:
                    cur.execute(stmt)
                except Exception as e:
                    raise RuntimeError(f"DuckDB {fname} error:\n{stmt[:200]!r}") from e

        self._copy_tables(_STATIC_TABLES + _LIVE_TABLES, transactional=False)

    def _copy_tables(self, tables, transactional=True):
        pg  = _pg_conn()
        pgc = pg.cursor()
        cur = self._duck_db
        try:
            if transactional:
                cur.execute("BEGIN")
            for table in tables:
                pgc.execute(f"SELECT * FROM {table}")
                rows = pgc.fetchall()
                cols = [d[0] for d in pgc.description]
                cur.execute(f"DELETE FROM {table}")
                if rows:
                    placeholders = ", ".join("?" * len(cols))
                    cur.executemany(
                        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                        rows,
                    )
            if transactional:
                cur.execute("COMMIT")
        except Exception:
            if transactional:
                try:
                    cur.execute("ROLLBACK")
                except Exception:
                    pass
        finally:
            pg.close()

    # ---- ETL loop ----

    def _etl_loop(self):
        while not self._etl_stop.wait(ETL_INTERVAL):
            self._copy_tables(_LIVE_TABLES, transactional=True)
