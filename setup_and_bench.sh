#!/usr/bin/env bash
# provision a fresh Ubuntu EC2 instance and run doombench
# Usage: sudo bash setup_and_bench.sh [adapter ...]
# Omit adapters to run all discovered adapters.
set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "\n${GRN}▶${NC}  $*"; }
warn() { echo -e "${YLW}▲${NC}  $*"; }
die()  { echo -e "${RED}✗${NC}  $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root:  sudo bash $0"

BENCH_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
log "doombench root: $BENCH_DIR"


# ── 1. System packages ───────────────────────────────────────────────────────
log "Installing system packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get -qq update
apt-get -qq install -y \
    ca-certificates curl gnupg \
    python3 python3-venv \
    ffmpeg \
    nvme-cli \
    xfsprogs \
    mdadm


# ── 2. Docker CE ─────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    log "Installing Docker CE…"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    . /etc/os-release
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get -qq update
    apt-get -qq install -y \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
else
    log "Docker already installed: $(docker --version)"
fi


# ── 3. Instance-store NVMe detection ────────────────────────────────────────
log "Scanning for instance-store NVMe devices…"
INSTANCE_DEVS=()
for dev in /dev/nvme*n1; do
    [[ -b "$dev" ]] || continue
    if nvme id-ctrl "$dev" 2>/dev/null | grep -qi "instance storage"; then
        INSTANCE_DEVS+=("$dev")
        log "  found: $dev"
    fi
done

SSD_DEV=""
SSD_MOUNT=""

if [[ ${#INSTANCE_DEVS[@]} -eq 0 ]]; then
    warn "No instance-store NVMe found, Docker will use the root EBS volume."
elif [[ ${#INSTANCE_DEVS[@]} -eq 1 ]]; then
    SSD_DEV="${INSTANCE_DEVS[0]}"
else
    if [[ -b /dev/md0 ]]; then
        log "RAID-0 array /dev/md0 already exists, skipping creation."
        SSD_DEV=/dev/md0
    else
        log "Striping ${#INSTANCE_DEVS[@]} instance stores with RAID-0…"
        for dev in "${INSTANCE_DEVS[@]}"; do
            mdadm --zero-superblock --force "$dev" 2>/dev/null || true
        done
        mdadm --create /dev/md0 --level=0 \
            --raid-devices="${#INSTANCE_DEVS[@]}" \
            --force --run "${INSTANCE_DEVS[@]}"
        SSD_DEV=/dev/md0
    fi
fi

SSD_MOUNT=/mnt/ssd

if [[ -n "$SSD_DEV" ]]; then
    if mountpoint -q "$SSD_MOUNT" 2>/dev/null; then
        log "$SSD_MOUNT already mounted, skipping format."
    else
        log "Formatting $SSD_DEV (XFS) and mounting at $SSD_MOUNT…"
        mkfs.xfs -f "$SSD_DEV"
        mkdir -p "$SSD_MOUNT"
        mount "$SSD_DEV" "$SSD_MOUNT"
    fi

    # Point each adapter at its own subdirectory on the SSD.
    # Adapters clean and recreate these on every start() call.
    export CEDAR_DATA_DIR="$SSD_MOUNT/cedardb"
    export PG_DATA_DIR="$SSD_MOUNT/postgres"
    export ALLOYDB_DATA_DIR="$SSD_MOUNT/alloydb"
    export PG_DUCKDB_DATA_DIR="$SSD_MOUNT/pg_duckdb"
    export PG_CLICKHOUSE_DATA_DIR="$SSD_MOUNT/pg_clickhouse"
    export PG_ETL_DATA_DIR="$SSD_MOUNT/pg_to_duckdb_etl"
    export CRDB_DATA_DIR="$SSD_MOUNT/cockroachdb"
else
    SSD_MOUNT=""
fi


# ── 4. Docker data-root on SSD ───────────────────────────────────────────────
if [[ -n "$SSD_MOUNT" ]]; then
    DOCKER_ROOT="$SSD_MOUNT/docker"
    if grep -qs "\"data-root\": \"$DOCKER_ROOT\"" /etc/docker/daemon.json 2>/dev/null; then
        log "Docker already configured for $DOCKER_ROOT"
    else
        log "Configuring Docker data-root → $DOCKER_ROOT…"
        systemctl stop docker 2>/dev/null || true
        mkdir -p "$DOCKER_ROOT"
        cat > /etc/docker/daemon.json <<JSON
{
    "data-root": "$DOCKER_ROOT"
}
JSON
        systemctl start docker
        systemctl enable docker --quiet
    fi
else
    [[ -f /etc/docker/daemon.json ]] || echo '{}' > /etc/docker/daemon.json
fi


# ── 5. Python venv + dependencies ────────────────────────────────────────────
log "Setting up Python environment…"
VENV="$BENCH_DIR/.venv"
python3 -m venv "$VENV"
"$VENV/bin/pip" -q install --upgrade pip
"$VENV/bin/pip" -q install -r "$BENCH_DIR/requirements.txt"



# ── 6. Run benchmark ──────────────────────────────────────────────────────────
log "Starting doombench…"
cd "$BENCH_DIR"
"$VENV/bin/python" benchmark.py "$@"

log "Done. Results in $BENCH_DIR/results/"
ls -lh "$BENCH_DIR/results/"
