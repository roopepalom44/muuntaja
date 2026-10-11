"""Build QGIS plugin ZIPs with a pinned, redistributable LibreDWG converter."""

import hashlib
import tarfile
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / "muuntaja_qgis"
VERSION = next(line.split("=", 1)[1].strip() for line in (PLUGIN / "metadata.txt").read_text(encoding="utf-8").splitlines()
               if line.startswith("version="))
OUTPUT = ROOT / "dist" / f"Muuntaja-QGIS-{VERSION}.zip"
OUTPUT.parent.mkdir(exist_ok=True)
ALLOWED = {".py", ".txt", ".png", ".json", ".gpkg"}

LIBREDWG_VERSION = "0.14"
ASSETS = {
    "libredwg-0.14-win64.zip": "1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8",
    "libredwg-0.14.tar.xz": "62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275",
}
CACHE = ROOT / ".cache"
CACHE.mkdir(exist_ok=True)


def asset(name):
    path = CACHE / name
    expected = ASSETS[name]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        url = f"https://github.com/LibreDWG/libredwg/releases/download/{LIBREDWG_VERSION}/{name}"
        with urlopen(url, timeout=60) as response, path.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"LibreDWG-tiedoston tarkistussumma ei täsmää: {name}")
    return path


binary = asset("libredwg-0.14-win64.zip")
source = asset("libredwg-0.14.tar.xz")


def build(output, windows_installer):
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(PLUGIN.rglob("*")):
            if path.is_file() and path.suffix.lower() in ALLOWED:
                archive.write(path, path.relative_to(ROOT))
        with ZipFile(binary) as upstream:
            for name in ("dwg2dxf.exe", "libredwg-0.dll", "README.txt"):
                archive.writestr(f"{PLUGIN.name}/libredwg/{name}", upstream.read(name))
        with tarfile.open(source, "r:xz") as upstream:
            license_file = upstream.extractfile("libredwg-0.14/COPYING")
            archive.writestr(f"{PLUGIN.name}/libredwg/COPYING", license_file.read())
        archive.write(source, f"{PLUGIN.name}/libredwg/libredwg-0.14.tar.xz")
        if windows_installer:
            archive.write(ROOT / "install_windows.bat", "install_windows.bat")
            archive.write(ROOT / "install_windows.ps1", "install_windows.ps1")
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert f"{PLUGIN.name}/metadata.txt" in archive.namelist()
        assert f"{PLUGIN.name}/libredwg/dwg2dxf.exe" in archive.namelist()
    print(output)


build(OUTPUT, False)

WINDOWS_OUTPUT = ROOT / "dist" / f"Muuntaja-QGIS-{VERSION}-Windows.zip"
build(WINDOWS_OUTPUT, True)
