#!/usr/bin/env python3
"""Copy only build-manifest-listed GitHub Pages files into the repository root."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    site_dir = args.site_dir if args.site_dir.is_absolute() else ROOT / args.site_dir
    manifest = json.loads((site_dir / "build-manifest.json").read_text())
    copied = []
    for relative in manifest["siteFiles"]:
        source = site_dir / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        target = ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(relative)
    print(f"Copied {len(copied)} manifest-listed site files into {ROOT}.")


if __name__ == "__main__":
    main()
