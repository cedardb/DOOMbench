import subprocess, socket, time, psycopg, os, shutil
from .base import DBAdapter, _kill_containers_on_port

HOST_PORT = int(os.environ.get("CEDAR_HOST_PORT", "15432"))
IMAGE     = os.environ.get("CEDAR_IMAGE", "cedardb/cedardb:v2026-05-26")
DATA_DIR  = os.environ.get("CEDAR_DATA_DIR", "")

class Adapter(DBAdapter):
    NAME = "CedarDB"
    OVERRIDES = None  # reuse reference SQL

    def __init__(self):
        self.cid = None

    def start(self):
        _kill_containers_on_port(HOST_PORT)
        args = [
            "docker","run","-d","--rm",
            "-e","CEDAR_PASSWORD=postgres",
            "-e", "WAL_SYNC_METHOD=open_dsync",
            "-p", f"{HOST_PORT}:5432",
        ]
        if DATA_DIR:
            shutil.rmtree(DATA_DIR, ignore_errors=True)
            os.makedirs(DATA_DIR)
            args += ["-v", f"{DATA_DIR}:/var/lib/cedardb/data"]
        args.append(IMAGE)
        self.cid = subprocess.check_output(args, text=True).strip()

    def wait_ready(self, timeout=300):
        deadline = time.time()+timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("localhost", HOST_PORT), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        super().wait_ready(timeout=max(1, int(deadline-time.time())))

    def stop(self):
        if self.cid:
            subprocess.call(["docker","rm","-f", self.cid],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.cid = None

    def new_connection(self):
        conn = psycopg.connect(
            dbname="postgres", user="postgres", password="postgres",
            host="localhost", port=HOST_PORT,
        )
        conn.autocommit = True
        return conn, conn.cursor()
