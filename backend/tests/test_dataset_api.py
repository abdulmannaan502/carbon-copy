import pytest
from fastapi.testclient import TestClient

from app.db.synthetic import TARGET_COUNTS

pytestmark = pytest.mark.usefixtures("seeded_app_database")


def test_dataset_stats_reports_target_counts(client: TestClient) -> None:
    body = client.get("/api/v1/system/dataset-stats").json()

    for key, expected in TARGET_COUNTS.items():
        assert body[key] == expected, key
    assert body["seeded"] is True
    assert body["donor_states"] == TARGET_COUNTS["donors"]
    assert body["coordination_attempts"] > 0
    assert body["failures"] > 0
    assert body["recovery_actions"] > 0
    assert body["learning_events"] > 0
    assert body["data_notice"] == "Synthetic demonstration data — not for clinical use."


def test_patients_are_paginated(client: TestClient) -> None:
    body = client.get("/api/v1/patients", params={"page": 2, "page_size": 5}).json()

    assert (body["page"], body["page_size"], body["total"], body["pages"]) == (2, 5, 80, 16)
    assert [p["patient_code"] for p in body["items"]] == [f"PAT-{n:04d}" for n in range(6, 11)]
    assert "id" not in body["items"][0]


def test_donors_include_state_snapshot(client: TestClient) -> None:
    body = client.get("/api/v1/donors", params={"page_size": 3}).json()

    assert body["total"] == TARGET_COUNTS["donors"]
    donor = body["items"][0]
    assert donor["donor_code"] == "DON-00001"
    assert donor["state_snapshot"]["eligibility_status"] in {"ELIGIBLE", "TEMPORARILY_DEFERRED", "INELIGIBLE"}


def test_requests_and_bridge_groups_are_listed(client: TestClient) -> None:
    requests = client.get("/api/v1/requests").json()
    groups = client.get("/api/v1/bridge-groups").json()

    assert requests["total"] == TARGET_COUNTS["blood_requests"]
    assert requests["items"][0]["patient_code"].startswith("PAT-")
    assert groups["total"] == TARGET_COUNTS["bridge_groups"]
    assert len(groups["items"]) == 20  # default page size


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
def test_invalid_pagination_is_rejected(client: TestClient, params: dict[str, int]) -> None:
    assert client.get("/api/v1/patients", params=params).status_code == 422
