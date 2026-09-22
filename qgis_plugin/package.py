"""Build an installable QGIS plugin ZIP without caches or test artifacts."""

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "muuntaja_qgis"
VERSION = next(line.split("=", 1)[1].strip() for line in (PLUGIN / "metadata.txt").read_text(encoding="utf-8").splitlines()
               if line.startswith("version="))
OUTPUT = ROOT / "dist" / f"Muuntaja-QGIS-{VERSION}.zip"
OUTPUT.parent.mkdir(exist_ok=True)
ALLOWED = {".py", ".txt", ".png", ".json", ".gpkg"}
with ZipFile(OUTPUT, "w", ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(PLUGIN.rglob("*")):
        if path.is_file() and path.suffix.lower() in ALLOWED:
            archive.write(path, path.relative_to(ROOT))
with ZipFile(OUTPUT) as archive:
    assert f"{PLUGIN.name}/metadata.txt" in archive.namelist()
    assert f"{PLUGIN.name}/__init__.py" in archive.namelist()
print(OUTPUT)
