#!/usr/bin/env bash
# Usage: bash deploy.sh <ip> <"path/to/key.pem"> [adapter ...]
set -euo pipefail

IP="${1:?Usage: bash deploy.sh <ip> <key.pem>}"
KEY="${2:?Usage: bash deploy.sh <ip> <key.pem>}"

SSH="ssh -i '$KEY' -o StrictHostKeyChecking=no"

RSYNC="rsync -av -e \"ssh -i '$KEY' -o StrictHostKeyChecking=no\""

echo "Syncing repo to ubuntu@$IP:~/doombench/ …"
eval "$RSYNC" \
    --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' --exclude='*.pyc' --exclude='results/' \
    "$(dirname "${BASH_SOURCE[0]}")/" "ubuntu@$IP:~/doombench/"

echo "Running setup …"
ssh -t -i "$KEY" -o StrictHostKeyChecking=no ubuntu@"$IP" "sudo bash ~/doombench/setup_and_bench.sh ${*:3}"

echo "Syncing results back …"
eval "$RSYNC" "ubuntu@$IP:~/doombench/results/" "$(dirname "${BASH_SOURCE[0]}")/results/"
