import pytest


@pytest.fixture
def plugins():
    return ["quetz-mamba_solve"]


def test_mamba_solve_endpoint(client):
    response = client.post(
        "/api/mamba/solve",
        json={
            "channels": ["conda-forge"],
            "subdir": "osx-64",
            "spec": ["xtensor>=0.21.0"],
        },
    )
    assert response.status_code == 200
    assert b"@EXPLICIT" in response.content
    assert response.content.startswith(b"# platform: osx-64")

    assert b"conda-forge/osx-64/libcxx-" in response.content
    assert b"conda-forge/osx-64/xtensor-" in response.content


@pytest.mark.parametrize(
    "error,status",
    [(ValueError("unsatisfiable"), 422), (RuntimeError("Pixi missing"), 503)],
)
def test_solver_failure_returns_http_error(client, mocker, error, status):
    solver = mocker.Mock()
    solver.solve.side_effect = error
    mocker.patch("quetz_mamba_solve.api.get_solver", return_value=solver)
    response = client.post(
        "/api/mamba/solve",
        json={"channels": ["conda-forge"], "subdir": "linux-64", "spec": ["missing"]},
    )
    assert response.status_code == status
    assert response.json()["detail"] == str(error)
