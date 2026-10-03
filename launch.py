import argparse
import sys
import os
from pathlib import Path

root = Path(__file__).parent
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8800)
args = parser.parse_args()
os.chdir(root / "backend")
sys.path.insert(0, str(root / ".deps"))
sys.path.insert(0, str(root / "backend"))
import uvicorn
uvicorn.run("main:app", host="127.0.0.1", port=args.port)
