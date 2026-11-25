# tag::download-test-packages[]
"""Download the xtensor example packages used in the getting started guide."""

import argparse
import shutil
from pathlib import Path
from urllib.request import urlopen

PACKAGES = {
    "linux-64": "xtensor-0.24.3-h924138e_1.tar.bz2",
    "osx-64": "xtensor-0.24.3-h1b54a9f_1.tar.bz2",
    "osx-arm64": "xtensor-0.24.3-hf86a087_1.tar.bz2",
}


def download(directory):
    for platform, filename in PACKAGES.items():
        destination = directory / platform / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".part")
        try:
            with urlopen(
                f"https://conda.anaconda.org/conda-forge/{platform}/{filename}",
                timeout=60,
            ) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("xtensor"))
    args = parser.parse_args()
    download(args.directory)
# end::download-test-packages[]
