"""Synchronize the manual and QGIS runtime. Offline by default; --fetch for releases.

python SharedHelp/sync.py                         # update local QGIS copies
python SharedHelp/sync.py --check                 # verify without modifying
python SharedHelp/sync.py --source ../other/SharedHelp
python SharedHelp/sync.py --fetch                 # fetch canonical released source
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CANONICAL = "https://raw.githubusercontent.com/roopepalom44/suomenvaylat/main/SharedHelp/"
RUNTIME = ("__init__.py", "index.html", "manifest.json", "Icons/help.svg")


def validate(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or not isinstance(manifest.get("revision"), int):
        raise ValueError("Invalid manual manifest")
    digest = hashlib.sha256((root / "index.html").read_bytes()).hexdigest()
    if manifest["sha256"] != digest:
        raise ValueError("Manual checksum mismatch: " + str(root))
    return manifest


def fetch(verify_only=False):
    def read(name, limit):
        request = urllib.request.Request(CANONICAL + name, headers={"User-Agent": "PaikkatietoOhje-Sync/1"})
        with urllib.request.urlopen(request, timeout=45) as response:
            content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Manual download exceeds size limit")
        return content
    # Read manifest first, and verify the page before changing either local file.
    raw = read("manifest.json", 16384)
    remote = json.loads(raw)
    if remote.get("schema") != 1 or not isinstance(remote.get("revision"), int):
        raise ValueError("Invalid remote manual manifest")
    page = read("index.html", 32 * 1024 * 1024)
    if hashlib.sha256(page).hexdigest() != remote["sha256"]:
        raise ValueError("Canonical manual changed during download; retry synchronization")
    local = validate(ROOT)
    if verify_only:
        if remote != local:
            raise ValueError("Manual differs from canonical source; run --fetch, synchronize and commit the manual before release")
        return
    if remote["revision"] < local["revision"]:
        raise ValueError("Canonical manual is older than local; publish the canonical source first")
    if remote["revision"] == local["revision"] and remote["sha256"] != local["sha256"]:
        raise ValueError("Different manuals have the same revision; increment the manual revision")
    (ROOT / "index.html").write_bytes(page)
    (ROOT / "manifest.json").write_bytes(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify-canonical", action="store_true")
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    if args.check and (args.fetch or args.source):
        parser.error("--check cannot modify files")
    if args.source:
        source = args.source.resolve()
        validate(source)
        if source != ROOT:
            shutil.copytree(source, ROOT, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if args.fetch:
        fetch()
    if args.verify_canonical:
        fetch(verify_only=True)
    manifest = validate(ROOT)
    plugins = sorted((REPO / "qgis_plugin").glob("*/metadata.txt"))
    if not plugins:
        raise ValueError("No QGIS plugin metadata found")
    for metadata in plugins:
        target = metadata.parent / "shared_help"
        for name in RUNTIME:
            expected = (ROOT / name).read_bytes()
            destination = target / name
            if args.check:
                if not destination.is_file() or destination.read_bytes() != expected:
                    raise ValueError("Shared help is out of sync: " + str(destination))
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(expected)
    print(f"Shared help {manifest['version']}: {len(plugins)} QGIS plugin(s), SHA-256 {manifest['sha256']}")


if __name__ == "__main__":
    main()
