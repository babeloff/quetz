import shutil
import subprocess
import tempfile
from pathlib import Path

import toml


class PixiSolver:
    def __init__(self, channels, platform):
        self.channels = channels
        self.platform = platform

    def solve(self, specs):
        """Resolve specs and export package URLs without installing an environment."""
        pixi = shutil.which("pixi")
        if pixi is None:
            raise RuntimeError("Pixi is required for solving package specifications.")
        with tempfile.TemporaryDirectory(prefix="quetz-solve-") as directory:
            root = Path(directory)
            manifest = root / "pixi.toml"
            manifest.write_text(
                toml.dumps(
                    {
                        "workspace": {
                            "name": "quetz-solve",
                            "channels": self.channels,
                            "platforms": [self.platform],
                        },
                    }
                )
            )
            try:
                subprocess.run(
                    [
                        pixi,
                        "add",
                        "--manifest-path",
                        str(manifest),
                        "--no-install",
                        "--",
                        *specs,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                output = root / "export"
                subprocess.run(
                    [
                        pixi,
                        "workspace",
                        "export",
                        "conda-explicit-spec",
                        "--manifest-path",
                        str(manifest),
                        "--locked",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise ValueError(
                    f"Pixi could not solve the specifications: {exc.stderr}"
                ) from exc
            exports = list(output.glob("*.txt"))
            if len(exports) != 1:
                raise RuntimeError("Pixi did not produce one explicit specification.")
            exported = exports[0].read_text()
            if "@EXPLICIT\n" not in exported:
                raise RuntimeError("Pixi returned an invalid explicit specification.")
            packages = exported.split("@EXPLICIT\n", 1)[1]
            return f"# platform: {self.platform}\n\n@EXPLICIT\n\n{packages}"
