
# adapters/base.py
import subprocess, time
from pathlib import Path


def _kill_containers_on_port(port: int):
    """Kill any Docker containers already bound to *port* so start() won't fail."""
    result = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"publish={port}"],
        capture_output=True, text=True,
    )
    for cid in result.stdout.split():
        subprocess.call(["docker", "rm", "-f", cid],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

class DBAdapter:
    """
    Minimal interface adapters implement.
    Each adapter encapsulates its own start/stop/connect logic.
    """

    NAME = "base"
    OVERRIDES = None  # set to a path for per-DB SQL overrides, else None

    def start(self):
        """Start the DB (docker run, custom script...). Return None."""
        pass

    def wait_ready(self, timeout=60):
        """Block until the DB is ready to accept connections; raise on timeout."""
        # Default: try to connect until success
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                conn, cur = self.new_connection()
                conn.close()
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"{self.NAME}: not ready after {timeout}s")

    def stop(self):
        """Stop the DB (docker rm -f, ...)."""
        pass

    # ---- client connection ----

    def new_connection(self):
        """Return a brand-new (conn, cur) for use in a single thread."""
        raise NotImplementedError

    def new_olap_connection(self):
        """Return a (conn, cur) optimised for read/analytics queries.
        Defaults to a regular connection; override for split OLTP/OLAP systems."""
        import psycopg
        conn, _ = self.new_connection()
        conn.cursor_factory = psycopg.ClientCursor
        conn.prepare_threshold = None
        return conn, conn.cursor()

    def after_prepare(self):
        """Hook called after the DB is prepared and seeded.
        Override to bootstrap derived/replicated databases (e.g. DuckDB ETL)."""
        pass


    # ---- SQL helpers ----
    def sql_path(self, filename: str) -> Path:
        """
        Pick override if present; else default reference SQL.
        Adapters can set OVERRIDES to a directory with per-DB tweaked SQL.
        """
        if self.OVERRIDES:
            p = Path(self.OVERRIDES) / filename
            if p.exists(): return p
        return SQL_DIR / filename

    def exec_sql_text(self, cur, sql: str):
        """Execute a (possibly multi-statement) SQL string."""
        # Most DB-API drivers can execute a full script if statements are separated by ';'
        cur.execute(sql)

    def exec_sql_file(self, cur, filename: str):
        path = self.sql_path(filename)
        with open(path, "r", encoding="utf8") as f:
            self.exec_sql_text(cur, f.read())

    def query_all(self, cur, sql: str, params=None):
        cur.execute(sql, params or ())
        return cur.fetchall()
