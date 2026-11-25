# tag::test-plugins[]
"""Install and test each bundled plugin, reporting failure after testing them all."""

import subprocess
import sys
from pathlib import Path


def test_plugins(root):
    failed = False
    command = ["pixi", "run", "--locked", "-e", "dev"]
    for plugin in sorted((root / "plugins").glob("quetz_*")):
        if not plugin.is_dir():
            continue
        path = plugin.relative_to(root).as_posix()
        print(f"::group::Testing plugin {path}", flush=True)
        try:
            installed = subprocess.run(
                [*command, "quetz", "plugin", "install", path], cwd=root, check=False
            )
            if installed.returncode:
                failed = True
                continue
            tested = subprocess.run(
                [*command, "pytest", "-v", path], cwd=root, check=False
            )
            failed = bool(tested.returncode) or failed
        finally:
            print("::endgroup::", flush=True)
    return int(failed)


if __name__ == "__main__":
    sys.exit(test_plugins(Path(__file__).resolve().parents[1]))
# end::test-plugins[]
