# tag::clean-docs[]
"""Remove generated documentation while preserving its sources."""

import shutil
from pathlib import Path


def clean(root):
    build = root / "docs/build"
    if build.exists():
        shutil.rmtree(build)


if __name__ == "__main__":
    clean(Path(__file__).resolve().parents[1])
# end::clean-docs[]
