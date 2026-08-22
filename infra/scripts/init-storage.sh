#!/bin/sh
# Create the Matchly buckets in the local MinIO instance.
#
# Two buckets, not one: originals are large, write-once and expire on the venue's
# retention policy; derived clips are small and are kept much longer. Both stay
# private — every read goes through a short-lived signed URL.
set -eu

MINIO_ALIAS=local
MINIO_URL=${MINIO_URL:-http://minio:9000}

echo "Waiting for MinIO at ${MINIO_URL} ..."
until mc alias set "${MINIO_ALIAS}" "${MINIO_URL}" "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" >/dev/null 2>&1; do
  sleep 1
done

for bucket in matchly-originals matchly-derived; do
  if mc ls "${MINIO_ALIAS}/${bucket}" >/dev/null 2>&1; then
    echo "bucket ${bucket} already exists"
  else
    mc mb "${MINIO_ALIAS}/${bucket}"
    echo "created bucket ${bucket}"
  fi
  # Private by design: no anonymous access, ever.
  mc anonymous set none "${MINIO_ALIAS}/${bucket}" >/dev/null
done

echo "Storage ready."
