from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Python worker for a Tauri target")
    parser.add_argument(
        "--target", required=True, help="Rust target triple, for example x86_64-pc-windows-msvc"
    )
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    output = ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        f"medical-deid-worker-{args.target}",
        "--distpath",
        str(output),
        "--workpath",
        str(ROOT / ".build" / "pyinstaller" / args.target),
        "--specpath",
        str(ROOT / ".build" / "pyinstaller"),
        "--paths",
        str(ROOT / "src"),
        "--paths",
        str(ROOT / "packages" / "python-core" / "src"),
        "--collect-submodules",
        "surya",
        "--collect-data",
        "surya",
        str(ROOT / "packages" / "desktop-worker" / "src" / "medical_deid_worker" / "main.py"),
    ]
    if args.clean:
        command.insert(3, "--clean")
    env = {**os.environ, "PYINSTALLER_CONFIG_DIR": str(ROOT / ".build" / "pyinstaller" / "cache")}
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
