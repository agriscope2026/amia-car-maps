"""Upload export files to Supabase Storage (when configured). Otherwise files stay in OUTPUT_DIR."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = os.environ.get("EXPORTS_BUCKET", "exports")

mimetypes.add_type("application/geo+json", ".geojson")
mimetypes.add_type("application/geopackage+sqlite3", ".gpkg")


def enabled() -> bool:
    return bool(SUPABASE_URL and SERVICE_KEY)


def upload_dir(local: Path, prefix: str) -> dict[str, str]:
    """Upload every file under ``local`` to ``<bucket>/<prefix>/…``. Returns {relative path: object path}."""
    import httpx
    out = {}
    with httpx.Client(timeout=120) as c:
        for p in sorted(local.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(local).as_posix()
            obj = f"{prefix.strip('/')}/{rel}"
            r = c.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{obj}", content=p.read_bytes(),
                       headers={"Authorization": f"Bearer {SERVICE_KEY}", "apikey": SERVICE_KEY, "x-upsert": "true",
                                "Content-Type": mimetypes.guess_type(p.name)[0] or "application/octet-stream"})
            r.raise_for_status()
            out[rel] = obj
    return out
