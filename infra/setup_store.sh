#!/bin/bash
# Set up the durable KV store on kv-store: a Redis server that LMCache on kv-gpu writes to
# (remote_url: "redis://kv-store:6379" in lmcache-remote.yaml).
#
# Why Redis and not an "LMCache server": lmcache 0.5.x dropped the old lm:// server; remote
# storage now goes through adapters for external stores (redis, valkey, s3, fs, ...).
# Redis also lets the emulator list and delete keys, which the policy shortcut needs.
#
# Usage (on kv-store): bash setup_store.sh
set -euo pipefail

sudo apt-get update -qq
sudo apt-get install -y -qq redis-server

IP=$(hostname -I | awk '{print $1}')   # internal VPC IP (10.128.0.10)
sudo tee /etc/redis/kv-store.conf >/dev/null <<EOF
# Only reachable inside the VPC (GCP's default firewall also blocks 6379 from outside).
bind 127.0.0.1 $IP
protected-mode no
port 6379
# Fail writes when full instead of silently evicting: eviction would corrupt
# the "cache preserved" and "storage used" measurements.
maxmemory 24gb
maxmemory-policy noeviction
# No disk persistence: the store must outlive kv-gpu, not itself, and snapshotting
# tens of GB would stall the server mid-run.
save ""
appendonly no
EOF
# Load our overrides after the distro defaults.
sudo grep -q "include /etc/redis/kv-store.conf" /etc/redis/redis.conf ||
  echo "include /etc/redis/kv-store.conf" | sudo tee -a /etc/redis/redis.conf >/dev/null

sudo systemctl enable --now redis-server
sudo systemctl restart redis-server
sleep 1
redis-cli -h "$IP" ping
redis-cli config get maxmemory | paste -sd' '   # expect 25769803776 (24 GB)
redis-cli config get bind | paste -sd' '
echo "Redis listening on $IP:6379"
