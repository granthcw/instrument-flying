"""Append-only raw object storage in Supabase Storage.

Uses the REST endpoint directly so the job has no Supabase SDK dependency.
Objects are written with x-upsert: false, so a repeated key is rejected by the
server rather than silently overwritten -- the brief's append-only requirement
enforced at the storage layer, not just by convention.
"""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_BUCKET = "kjyo-forecast-raw"


def put_object(key: str, blob: bytes, bucket: str | None = None) -> str:
    url_base = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url_base or not service_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set, or set "
            "RAW_STORAGE_DIR to write raw payloads locally."
        )
    bucket = bucket or os.environ.get("SUPABASE_RAW_BUCKET", DEFAULT_BUCKET)
    url = f"{url_base.rstrip('/')}/storage/v1/object/{bucket}/{key}"
    req = urllib.request.Request(url, data=blob, method="POST", headers={
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/gzip",
        "x-upsert": "false",
    })
    try:
        with urllib.request.urlopen(req, timeout=60):
            return key
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            # Already present. Append-only means we keep the original.
            log.warning("raw object already exists, keeping original: %s", key)
            return key
        raise
