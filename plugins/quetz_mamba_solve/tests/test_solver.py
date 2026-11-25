import subprocess
from pathlib import Path

import pytest

from quetz_mamba_solve.solver import PixiSolver


def test_solve_exports_without_installing(mocker):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True
        if "conda-explicit-spec" in command:
            output = Path(command[-1])
            output.mkdir()
            (output / "default_osx-64_conda_spec.txt").write_text(
                "# platform: osx-64\n@EXPLICIT\nhttps://example.org/xtensor.conda#abc\n"
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    mocker.patch("shutil.which", return_value="/bin/pixi")
    mocker.patch("subprocess.run", side_effect=run)
    result = PixiSolver(["conda-forge"], "osx-64").solve(["xtensor>=0.21"])
    assert "@EXPLICIT" in result
    assert "https://example.org/xtensor.conda#abc" in result
    assert commands[0][1] == "add"
    assert "--no-install" in commands[0]
    assert commands[0][-2:] == ["--", "xtensor>=0.21"]
    assert "conda-explicit-spec" in commands[1]
    assert not Path(commands[0][commands[0].index("--manifest-path") + 1]).exists()


def test_solve_failure_does_not_exit_server(mocker):
    mocker.patch("shutil.which", return_value="/bin/pixi")
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "pixi", stderr="unsatisfiable"),
    )
    with pytest.raises(ValueError, match="unsatisfiable"):
        PixiSolver(["conda-forge"], "osx-64").solve(["missing-package"])


def test_solver_requires_pixi(mocker):
    mocker.patch("shutil.which", return_value=None)
    with pytest.raises(RuntimeError, match="Pixi"):
        PixiSolver(["conda-forge"], "osx-64").solve(["xtensor"])
