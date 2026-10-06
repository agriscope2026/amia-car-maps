"""Upload export files to Cloudflare R2 or Supabase Storage (when configured). Otherwise files stay in OUTPUT_DIR.

R2 (preferred when R2_* is set): objects go to ``<R2_BUCKET>/exports/<prefix>/<file>``.
Supabase: objects go to ``<EXPORTS_BUCKET>/<prefix>/<file>``.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = os.environ.get("EXPORTS_BUCKET", "exports")

R2_ACCOUNT = os.environ.get("R2_ACCOUNT_ID", "")
R2_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET") or "amia-car-maps"

mimetypes.add_type("application/geo+json", ".geojson")
mimetypes.add_type("application/geopackage+sqlite3", ".gpkg")


def r2_enabled() -> bool:
    return bool(R2_ACCOUNT and R2_KEY_ID and R2_SECRET)


def enabled() -> bool:
    return r2_enabled() or bool(SUPABASE_URL and SERVICE_KEY)


def _files(local: Path):
    for p in sorted(local.rglob("*")):
        if p.is_file():
            yield p, p.relative_to(local).as_posix()


def _upload_r2(local: Path, prefix: str) -> dict[str, str]:
    import boto3
    from botocore.config import Config
    s3 = boto3.client("s3", endpoint_url=f"https://{R2_ACCOUNT}.r2.cloudflarestorage.com",
                      aws_access_key_id=R2_KEY_ID, aws_secret_access_key=R2_SECRET, region_name="auto",
                      config=Config(signature_version="s3v4", retries={"max_attempts": 4}))
    out = {}
    for p, rel in _files(local):
        key = f"exports/{prefix.strip('/')}/{rel}"
        s3.upload_file(str(p), R2_BUCKET, key,
                       ExtraArgs={"ContentType": mimetypes.guess_type(p.name)[0] or "application/octet-stream"})
        out[rel] = key
    return out


def upload_dir(local: Path, prefix: str) -> dict[str, str]:
    """Upload every file under ``local``. Returns {relative path: object key}."""
    if r2_enabled():
        return _upload_r2(local, prefix)
    import httpx
    out = {}
    with httpx.Client(timeout=120) as c:
        for p, rel in _files(local):
            obj = f"{prefix.strip('/')}/{rel}"
            r = c.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{obj}", content=p.read_bytes(),
                       headers={"Authorization": f"Bearer {SERVICE_KEY}", "apikey": SERVICE_KEY, "x-upsert": "true",
                                "Content-Type": mimetypes.guess_type(p.name)[0] or "application/octet-stream"})
            r.raise_for_status()
            out[rel] = obj
    return out
