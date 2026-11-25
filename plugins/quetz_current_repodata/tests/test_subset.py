from copy import deepcopy

from quetz_current_repodata.current_repodata import build_current_repodata


def package(name, version, build="0", **extra):
    return {
        "name": name,
        "version": version,
        "build": build,
        "build_number": 0,
        "depends": [],
        "subdir": "linux-64",
        **extra,
    }


def test_latest_versions_keep_builds_and_backfill_dependencies():
    records = {
        "app-2-0.tar.bz2": package("app", "2", depends=["lib >=1,<2 py*"]),
        "lib-1-py_0.tar.bz2": package("lib", "1", "py_0"),
        "lib-1-py_1.tar.bz2": package("lib", "1", "py_1"),
        "lib-2-py_0.tar.bz2": package("lib", "2", "py_0"),
        "lib-0-py_0.tar.bz2": package("lib", "0", "py_0"),
    }
    result = build_current_repodata("linux-64", {"packages": records})
    assert set(result["packages"]) == set(records) - {"lib-0-py_0.tar.bz2"}


def test_conda_format_preference_and_legacy_hash_without_mutation():
    data = {
        "info": {"subdir": "linux-64"},
        "repodata_version": 1,
        "removed": ["old"],
        "packages": {"lib-2-0.tar.bz2": package("lib", "2", md5="a" * 32)},
        "packages.conda": {"lib-2-0.conda": package("lib", "2")},
    }
    original = deepcopy(data)
    result = build_current_repodata("linux-64", data)
    assert result["packages"] == {}
    assert result["packages.conda"]["lib-2-0.conda"]["legacy_bz2_md5"] == "a" * 32
    assert result["info"] == data["info"]
    assert result["removed"] == ["old"]
    assert data == original


def test_features_preserve_a_featureless_alternative():
    records = {
        "lib-3-0.tar.bz2": package("lib", "3", track_features="accelerated"),
        "lib-2-0.tar.bz2": package("lib", "2"),
        "lib-1-0.tar.bz2": package("lib", "1"),
    }
    result = build_current_repodata("linux-64", {"packages": records})
    assert set(result["packages"]) == {"lib-3-0.tar.bz2", "lib-2-0.tar.bz2"}


def test_missing_virtual_dependencies_and_empty_repodata():
    records = {"lib-1-0.tar.bz2": package("lib", "1", depends=["__glibc >=2.17"])}
    assert (
        build_current_repodata("linux-64", {"packages": records})["packages"] == records
    )
    assert build_current_repodata("linux-64", {}) == {
        "packages": {},
        "packages.conda": {},
    }


def test_equivalent_version_spellings_keep_all_builds():
    records = {
        "lib-1.0-0.tar.bz2": package("lib", "1.0"),
        "lib-1.0.0-1.tar.bz2": package("lib", "1.0.0", "1"),
        "lib-0.9-0.tar.bz2": package("lib", "0.9"),
    }
    result = build_current_repodata("linux-64", {"packages": records})
    assert set(result["packages"]) == {"lib-1.0-0.tar.bz2", "lib-1.0.0-1.tar.bz2"}
