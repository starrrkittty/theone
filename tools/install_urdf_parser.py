"""Install the verified pure-Python parser source into project-local dependencies."""
import hashlib
import io
from pathlib import Path
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = "https://files.pythonhosted.org/packages/a3/8b/9dd44781a4e87746a426c56c3368c3da64fd90a130f582340cbf74397f8e/urdf_parser_py-0.0.4.tar.gz"
HASH = "e983f637145fded67bcff6a542302069bb975b2edf1b18318c093abba1b794cc"

if __name__ == "__main__":
    with urlopen(URL, timeout=30) as response:
        blob = response.read(100_000)
    if hashlib.sha256(blob).hexdigest() != HASH:
        raise RuntimeError("Parser source checksum mismatch")
    target = ROOT / ".deps"
    with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
        for member in archive.getmembers():
            relative = Path(*Path(member.name).parts[1:])
            if not relative.parts or relative.parts[0] not in {"urdf_parser_py", "LICENSE"}:
                continue
            path = (target / relative).resolve()
            if not path.is_relative_to(target.resolve()) or member.issym() or member.islnk():
                raise RuntimeError("Unsafe parser source path")
            if member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(member).read())
    print("Installed urdf-parser-py 0.0.4 source locally; requires lxml and PyYAML")
