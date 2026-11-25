# tag::render-docs[]
"""Build the AsciiDoc site while preserving its existing page paths."""

import argparse
import runpy
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/build/html"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    source = root / "docs/source"
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = runpy.run_path(str(root / "quetz/_version.py"))["__version__"]
    documents = sorted(
        path
        for path in source.rglob("*.adoc")
        if not any(part.startswith("_") for part in path.relative_to(source).parts)
    )
    subprocess.run(
        [
            "asciidoctor",
            "--failure-level",
            "WARN",
            "-a",
            "reproducible",
            "-a",
            f"revnumber={version}",
            "-R",
            str(source),
            "-D",
            str(output),
            *map(str, documents),
        ],
        check=True,
    )
    shutil.copytree(source / "_static", output / "_static", dirs_exist_ok=True)
    print(f"Rendered {len(documents)} AsciiDoc pages to {output}")


if __name__ == "__main__":
    main()
# end::render-docs[]
