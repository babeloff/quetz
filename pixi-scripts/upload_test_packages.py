# tag::upload-test-packages[]
"""Upload downloaded example packages using QUETZ_API_KEY and QUETZ_SERVER_URL."""

import argparse
import os
from contextlib import ExitStack
from pathlib import Path

import requests


def upload(directory, channel):
    packages = sorted(directory.glob("*/*.tar.bz2"))
    if not packages:
        raise ValueError(
            f"No example packages found under {directory}; run download-test-packages first"
        )
    server = os.environ.get("QUETZ_SERVER_URL", "http://localhost:8000").rstrip("/")
    with ExitStack() as stack:
        response = requests.post(
            f"{server}/api/channels/{channel}/packages/xtensor/files/",
            headers={"X-API-Key": os.environ["QUETZ_API_KEY"]},
            files=[
                ("files", (path.name, stack.enter_context(path.open("rb"))))
                for path in packages
            ],
            timeout=60,
        )
        response.raise_for_status()
        print(response.text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("xtensor"))
    parser.add_argument("--channel", default="channel0")
    args = parser.parse_args()
    upload(args.directory, args.channel)
# end::upload-test-packages[]
