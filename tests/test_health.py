from fastapi.testclient import TestClient
from server.api.main import app

client = TestClient(app)

def test_health_does_not_claim_analysis_ready():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["analysis_ready"] is False
    assert response.json()["analysis_pipeline_available"] is True
    assert response.json()["readiness_verified"] is False

def test_unimplemented_analysis_is_not_success():
    # The route now exists in PH07, but invalid/unconfigured input must never return fake success.
    assert client.post("/api/datasets/demo/baseline").status_code >= 400
