from __future__ import annotations

import shutil
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "web" / "dist"
    target = repo_root / "src" / "pyroscope" / "web_dist"

    if not source.exists():
        raise SystemExit("web/dist does not exist; run the frontend build first")

    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)


if __name__ == "__main__":
    main()
