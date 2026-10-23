"""Build one self-contained HTML file; images stay embedded for offline use."""
from pathlib import Path
import base64
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent


def build():
    source = (ROOT / "manual.html").read_text(encoding="utf-8")
    def embed(match):
        path = ROOT / "Images" / match.group(1)
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    result = re.sub(r"\{\{image:([\w.-]+)\}\}", embed, source)
    data = result.encode("utf-8")
    (ROOT / "index.html").write_bytes(data)
    manifest = {"schema": 1, "revision": 2026102401, "version": "2026.10.24.1", "date": "2026-10-24",
                "sha256": hashlib.sha256(data).hexdigest()}
    (ROOT / "manifest.json").write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(f"Manual: {len(data):,} bytes; SHA-256 {manifest['sha256']}")


if __name__ == "__main__":
    build()
