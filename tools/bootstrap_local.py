"""Install pinned pure Python wheels locally when pip subprocesses are restricted.

Uses the host Python's existing numpy/scipy/pydantic/settings dependencies.
Normal installations should use setup.cmd instead.
"""
import hashlib
import argparse
import io
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {"fastapi":"0.115.14", "starlette":"0.46.2", "uvicorn":"0.34.3",
            "websockets":"15.0.1", "aiofiles":"24.1.0", "python-multipart":"0.0.20",
            "anyio":"4.9.0", "click":"8.1.8", "h11":"0.16.0",
            "sniffio":"1.3.1", "idna":"3.10"}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-deps", action="store_true")
    args = parser.parse_args()
    if args.test_deps:
        PACKAGES = {"pytest-asyncio":"0.26.0"}
    target = ROOT / ".deps"
    target.mkdir(exist_ok=True)
    for name, version in PACKAGES.items():
        with urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
            metadata = json.load(response)
        wheel = next(item for item in metadata["urls"] if item["filename"].endswith("py3-none-any.whl"))
        with urlopen(wheel["url"], timeout=30) as response:
            blob = response.read()
        if hashlib.sha256(blob).hexdigest() != wheel["digests"]["sha256"]:
            raise RuntimeError(f"Hash mismatch: {name}")
        with ZipFile(io.BytesIO(blob)) as archive:
            for member in archive.infolist():
                destination = (target / member.filename).resolve()
                if not destination.is_relative_to(target.resolve()):
                    raise RuntimeError("Unsafe wheel path")
            archive.extractall(target)
        print(f"Installed {name} {version}", flush=True)
