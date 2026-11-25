"""Select current package versions with Rattler's package-spec matching."""

from collections import defaultdict
from copy import deepcopy

from rattler import BuildString, MatchSpec, PackageRecord

from quetz.versionorder import VersionOrder


def build_current_repodata(subdir, repodata):
    """Keep latest builds, dependency backfills, and featureless alternatives."""
    entries = {}
    versions = {}
    by_name = defaultdict(list)
    modern = repodata.get("packages.conda", {})
    for section in ("packages", "packages.conda"):
        for filename, data in repodata.get(section, {}).items():
            if (
                section == "packages"
                and filename.removesuffix(".tar.bz2") + ".conda" in modern
            ):
                continue
            track_features = data.get("track_features", [])
            if isinstance(track_features, str):
                track_features = track_features.replace(",", " ").split()
            record = PackageRecord(
                name=data["name"],
                version=data["version"],
                build=BuildString(data["build"]),
                build_number=data["build_number"],
                subdir=data.get("subdir", subdir),
                features=data.get("features"),
                track_features=track_features,
            )
            versions[filename] = VersionOrder(data["version"])
            entries[filename] = (section, data, record)
            by_name[data["name"]].append(filename)

    def order(filename):
        data = entries[filename][1]
        return (
            versions[filename],
            data["build_number"],
            data.get("timestamp", 0),
            data["build"],
        )

    selected = set()
    for filenames in by_name.values():
        filenames.sort(key=order, reverse=True)
        latest = versions[filenames[0]]
        selected.update(f for f in filenames if versions[f] == latest)

    dependencies = {
        dependency
        for filename in selected
        for dependency in entries[filename][1].get("depends", [])
    }
    for dependency in sorted(dependencies):
        spec = MatchSpec(dependency)
        candidates = by_name.get(spec.name.normalized, [])
        if any(f in selected and spec.matches(entries[f][2]) for f in candidates):
            continue
        matches = [f for f in candidates if spec.matches(entries[f][2])]
        if not matches:
            continue
        newest = max(matches, key=order)
        data = entries[newest][1]
        selected.update(
            f for f in by_name[data["name"]] if versions[f] == versions[newest]
        )

    for filenames in by_name.values():
        current = [f for f in filenames if f in selected]
        if not any(
            entries[f][1].get("features") or entries[f][1].get("track_features")
            for f in current
        ):
            continue
        for filename in filenames:
            data = entries[filename][1]
            if not data.get("features") and not data.get("track_features"):
                selected.add(filename)
                break

    result = {
        k: deepcopy(v)
        for k, v in repodata.items()
        if k not in ("packages", "packages.conda")
    }
    result.update({"packages": {}, "packages.conda": {}})
    for filename in sorted(selected):
        section, data, _ = entries[filename]
        data = deepcopy(data)
        if section == "packages.conda":
            legacy = filename.removesuffix(".conda") + ".tar.bz2"
            data["legacy_bz2_md5"] = (
                repodata.get("packages", {}).get(legacy, {}).get("md5")
            )
        result[section][filename] = data
    return result
