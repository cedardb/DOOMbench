# DOOMbench

A database benchmark that runs a DOOM-like raycasting game engine entirely in SQL. All client logic is implemented inside the database (wall rendering, mob AI, player movement, hit detection) and measures real-world HTAP performance: FPS, tick rate, and input latency under concurrent read/write load.

Each benchmark run produces a replay video and a `index.html` dashboard comparing all tested systems.

## Quick start on EC2 (recommended)

For reproducible results on a fresh Ubuntu instance with ephemeral NVMe SSDs:

```bash
# On the EC2 instance (run once; idempotent)
sudo bash setup_and_bench.sh

# Or benchmark only specific adapters
sudo bash setup_and_bench.sh cedardb postgres
```

`setup_and_bench.sh` installs Docker, detects and mounts instance-store NVMe drives (RAID-0 if multiple), configures Docker's data-root on the SSD, sets up a Python venv, and runs the benchmark. All database data directories are placed on the SSD automatically.

### Remote deployment

To sync the repo to an EC2 instance and run the benchmark from your laptop:

```bash
bash deploy.sh <ip> <path/to/key.pem> [adapter ...]
```

Results are synced back to `results/` when the run completes.

## Local prerequisites

- **Docker**: Each adapter spins up its own container; your user must be in the `docker` group (or run with `sudo`)
- **Python 3.9+**
- **ffmpeg**: For encoding replay MP4s (`apt install ffmpeg` / `brew install ffmpeg`)
- Python packages: `pip install -r requirements.txt`

## Local installation

```bash
git clone <repo>
cd doombench
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

### Benchmark all adapters

```bash
python benchmark.py
```

### Benchmark specific adapters

```bash
python benchmark.py cedardb postgres
```

### Generate replay videos from existing results (no benchmark)

```bash
python benchmark.py --replay
python benchmark.py --replay cedardb postgres
```

### Render results dashboard

```bash
python render.py
```

Opens `results/index.html` with FPS charts, tick latency graphs, and replay video players.

## Adapters

| Name | Docker image |
|------|-------------|
| `cedardb` | *(internal image)* |
| `postgres` | `postgres:18` |
| `alloydb` | `google/alloydbomni:latest` (PostgreSQL 16.8) |
| `pg_duckdb` | `pgduckdb/pgduckdb:17-main` (PostgreSQL 17.9) |
| `pg_clickhouse` | `ghcr.io/clickhouse/pg_clickhouse:18` (PostgreSQL 18.3) |
| `pg_to_duckdb_etl` | `postgres:18` (+ in-process DuckDB latest, 1.5.2 as of writing) |
| `cockroachdb` | `cockroachdb/cockroach:v23.2.28` |

Adapters run sequentially; any leftover container on a port is killed before starting the next run.

### pg_to_duckdb_etl

Writes game state to Postgres and runs analytics queries against an in-memory DuckDB database that is periodically refreshed via ETL. The refresh interval (default 1 s) is controlled by `ETL_INTERVAL`. This deliberately exposes the HTAP blind spot of the ETL architecture.

### alloydb / DeWitt clause

AlloyDB Omni is subject to a benchmarking clause in its terms of service. The results dashboard redacts numeric metrics for this adapter; replay videos are displayed without restriction.

## Output

Results are written to `results/` (gitignored) and `index.html`:

| File | Description |
|------|-------------|
| `results/<adapter>.json` | Raw benchmark metrics |
| `results/<adapter>_replay.mp4` | Replay video with keyboard overlay and performance graphs |
| `index.html` | Interactive dashboard (open in browser) |

## Adding an adapter

1. Create `adapters/<name>.py` implementing the `DBAdapter` interface (see `adapters/base.py`).
2. Place any SQL overrides in `overrides/<name>/`. Files there take precedence over the reference SQL in `sql/`.
3. Run `python benchmark.py <name>` to test it.

The benchmark discovers adapters automatically; no registration needed.
