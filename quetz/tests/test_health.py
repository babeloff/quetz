from fastapi.testclient import TestClient


def test_get_health_ready(client: TestClient):
    response = client.get("/health/ready")
    assert response.status_code == 200


def test_get_health_live(client: TestClient):
    response = client.get("/health/live")
    assert response.status_code == 200


def test_ready_reports_database_outage_without_details(client, db, mocker):
    from sqlalchemy.exc import OperationalError

    execute = mocker.patch.object(
        db, "execute", side_effect=OperationalError("sensitive database URL", {}, None)
    )
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
    assert execute.call_count == 1


def test_liveness_does_not_query_database(client, db, mocker):
    execute = mocker.patch.object(db, "execute", side_effect=RuntimeError("offline"))
    response = client.get("/health/live")
    assert response.status_code == 200
    execute.assert_not_called()
