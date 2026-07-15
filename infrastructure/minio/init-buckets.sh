#!/bin/sh
# Creates the four RoadVisionAI buckets (TechStack §7) — idempotent.
set -e
mc alias set local http://minio:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
for b in road-images annotated-images reports models; do
  mc mb --ignore-existing "local/$b"
done
echo "MinIO buckets ready."
