import json
from pathlib import Path

import quetz
from quetz.utils import add_temp_static_file

from .current_repodata import build_current_repodata


@quetz.hookimpl
def post_package_indexing(tempdir: Path, channel_name, subdirs, files, packages):
    for subdir in subdirs:
        with open(tempdir / channel_name / subdir / "repodata.json") as f:
            repodata = json.load(f)

        current_repodata = build_current_repodata(subdir, repodata)

        current_repodata_string = json.dumps(current_repodata, indent=2, sort_keys=True)

        add_temp_static_file(
            current_repodata_string,
            channel_name,
            subdir,
            "current_repodata.json",
            tempdir,
            files,
        )
