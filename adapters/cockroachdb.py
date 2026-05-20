import subprocess, socket, time, psycopg, os, shutil
from pathlib import Path
from .base import DBAdapter, _kill_containers_on_port

HOST_PORT = int(os.environ.get("CRDB_HOST_PORT", "26257"))
IMAGE     = os.environ.get("CRDB_IMAGE", "cockroachdb/cockroach:v23.2.28")
DATA_DIR  = os.environ.get("CRDB_DATA_DIR", "")

class Adapter(DBAdapter):
    NAME      = "CockroachDB"
    OVERRIDES = str(Path(__file__).resolve().parent.parent / "overrides" / "cockroachdb")

    def __init__(self):
        self.cid = None

    def start(self):
        _kill_containers_on_port(HOST_PORT)
        args = [
            "docker","run","-d","--rm",
            "-e","COCKROACH_DATABASE=postgres",
            "-e","COCKROACH_USER=postgres",
            "-e","COCKROACH_PASSWORD=postgres",
            "-p", f"{HOST_PORT}:26257",
        ]
        if DATA_DIR:
            shutil.rmtree(DATA_DIR, ignore_errors=True)
            os.makedirs(DATA_DIR)
            args += ["-v", f"{DATA_DIR}:/cockroach/cockroach-data"]
        args += [IMAGE, "start-single-node"]
        self.cid = subprocess.check_output(args, text=True).strip()

    def wait_ready(self, timeout=300):
        # wait for TCP
        deadline = time.time()+timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("localhost", HOST_PORT), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        # then try SQL
        super().wait_ready(timeout=max(1, int(deadline-time.time())))

    def stop(self):
        if self.cid:
            subprocess.call(["docker","rm","-f", self.cid],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def new_connection(self):
        conn = psycopg.connect(
            dbname="postgres", user="postgres", password="postgres",
            host="localhost", port=HOST_PORT,
        )
        conn.autocommit = True
        return conn, conn.cursor()
