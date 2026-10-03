"""Memory-safe resumable range downloader for selected Zenodo record files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BUFFER_BYTES = 1024 * 1024


def record_files(record_id: str) -> dict[str, dict[str, object]]:
    with urllib.request.urlopen(
        f"https://zenodo.org/api/records/{record_id}", timeout=60
    ) as response:
        record = json.load(response)
    return {item["key"]: item for item in record["files"]}


def download_range(url: str, path: Path, start: int, end: int) -> None:
    expected = end - start + 1
    if path.is_file() and path.stat().st_size == expected:
        return
    temporary = path.with_suffix(path.suffix + ".downloading")
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != 206:
            raise RuntimeError(f"Server ignored byte range {start}-{end}: HTTP {response.status}")
        with temporary.open("wb") as output:
            while block := response.read(BUFFER_BYTES):
                output.write(block)
    if temporary.stat().st_size != expected:
        raise IOError(
            f"Incomplete range {start}-{end}: got {temporary.stat().st_size}, expected {expected}"
        )
    os.replace(temporary, path)


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while block := handle.read(BUFFER_BYTES):
            digest.update(block)
    return digest.hexdigest()


def download_file(item: dict[str, object], output: Path, connections: int) -> None:
    key = str(item["key"])
    size = int(item["size"])
    checksum = str(item["checksum"]).removeprefix("md5:")
    url = str(item["links"]["self"])
    destination = output / key
    if destination.is_file():
        if destination.stat().st_size == size and md5(destination) == checksum:
            print(f"already complete: {destination}")
            return
        raise FileExistsError(
            f"Refusing to overwrite partial or invalid file: {destination}. "
            "Move it aside or finish it with curl --continue-at -."
        )

    part_dir = output / f".{key}.parts"
    part_dir.mkdir(parents=True, exist_ok=True)
    chunk_size = (size + connections - 1) // connections
    jobs: list[tuple[Path, int, int]] = []
    for index in range(connections):
        start = index * chunk_size
        if start >= size:
            break
        end = min(size - 1, start + chunk_size - 1)
        jobs.append((part_dir / f"part-{index:03d}", start, end))

    with ThreadPoolExecutor(max_workers=connections) as pool:
        futures = {
            pool.submit(download_range, url, path, start, end): (path, start, end)
            for path, start, end in jobs
        }
        for future in as_completed(futures):
            path, start, end = futures[future]
            future.result()
            print(f"downloaded {key} bytes {start}-{end}")

    assembled = output / f".{key}.assembling"
    with assembled.open("wb") as target:
        for path, _, _ in jobs:
            with path.open("rb") as source:
                shutil.copyfileobj(source, target, BUFFER_BYTES)
    if assembled.stat().st_size != size:
        raise IOError(f"Assembled size mismatch for {key}")
    actual = md5(assembled)
    if actual != checksum:
        raise IOError(f"Checksum mismatch for {key}: {actual} != {checksum}")
    os.replace(assembled, destination)
    for path, _, _ in jobs:
        path.unlink()
    part_dir.rmdir()
    print(f"verified {destination} ({size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--files", nargs="+", required=True)
    parser.add_argument("--connections", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.connections <= 8:
        raise ValueError("--connections must be between 1 and 8")
    args.output.mkdir(parents=True, exist_ok=True)
    available = record_files(args.record)
    for key in args.files:
        if key not in available:
            raise KeyError(f"{key} is not present in Zenodo record {args.record}")
        download_file(available[key], args.output, args.connections)


if __name__ == "__main__":
    main()
