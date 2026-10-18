"""Publish the existing /static URLs through Vercel's public directory.

This build step never imports the app, connects to a database, or seeds data.
"""

from pathlib import Path
from shutil import copytree

ROOT = Path(__file__).resolve().parents[1]


def build(root: Path = ROOT) -> None:
    copytree(root / "webapp" / "static", root / "public" / "static", dirs_exist_ok=True)


if __name__ == "__main__":
    build()
    print("Published static assets to public/static")
