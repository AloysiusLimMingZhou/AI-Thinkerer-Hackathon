"""Local-only HTTP smoke test. Does not launch a bot or call paid model APIs.

Start a backend against a temporary MEETING_AGENT_DB on port 8011 first.
"""

from pathlib import Path

import httpx
from dotenv import dotenv_values


def main():
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    with httpx.Client(base_url="http://127.0.0.1:8011", timeout=10) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/sessions").status_code == 401
        client.headers["Authorization"] = "Bearer " + env["BACKEND_API_TOKEN"]
        status = client.get("/recall/status")
        assert status.status_code == 200
        session = client.post(
            "/sessions",
            json={
                "title": "Local smoke test",
                "owner_name": "Tester",
                "agent_name": "Alloy",
            },
        )
        assert session.status_code == 201
        sid = session.json()["id"]
        response = client.post(
            f"/sessions/{sid}/utterances",
            json={"speaker": "Tester", "text": "General project update."},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "stay_silent"
        assert len(client.get(f"/sessions/{sid}/transcript").json()) == 1
        assert client.get(f"/sessions/{sid}/events").json()
        assert (
            client.post(
                "/webhooks/recall", json={"event": "transcript.data", "data": {}}
            ).status_code
            == 401
        )
        print(
            "PASS: real HTTP health, auth, session, gate, transcript, events, unsigned webhook rejection"
        )
        print("Missing live configuration:", ", ".join(status.json()["missing"]))


if __name__ == "__main__":
    main()
