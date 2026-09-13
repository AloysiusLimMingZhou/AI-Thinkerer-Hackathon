"""Explicit live provider smoke test; uses a little OpenAI/ElevenLabs credit.

No meeting bot is created. Credentials are loaded locally and never printed.
"""

from pathlib import Path

import httpx

from meeting_agent.config import Settings


def main():
    settings = Settings.from_env()
    with httpx.Client(
        base_url="http://127.0.0.1:8000",
        timeout=90,
        headers={"Authorization": "Bearer " + settings.backend_api_token},
    ) as client:
        session = client.post(
            "/sessions",
            json={
                "title": "Provider preflight (synthetic demo)",
                "owner_name": "Aloy",
                "agent_name": "Alloy",
            },
        )
        session.raise_for_status()
        sid = session.json()["id"]
        result = client.post(
            f"/sessions/{sid}/context",
            json={
                "notes": [
                    {
                        "source": "synthetic-demo",
                        "title": "Demo launch",
                        "content": "These are fictional demo facts. The demo launch is Friday. Jamie owns the checklist. The budget has not been decided.",
                    }
                ]
            },
        )
        result.raise_for_status()
        result = client.post(
            f"/sessions/{sid}/utterances",
            json={"speaker": "Tester", "text": "Alloy, when is the demo launch?"},
        )
        if result.status_code != 200:
            print("OpenAI preflight failed: HTTP", result.status_code)
            print("Backend diagnostic:", result.json().get("detail"))
            return
        decision = result.json()
        print("OpenAI decision:", decision["action"])
        print("Answer:", decision.get("answer"))
        if decision["action"] != "answer" or not decision.get("answer"):
            raise SystemExit("No answer produced; stop before joining a meeting")
        result = client.post(
            f"/sessions/{sid}/speak", json={"text": decision["answer"]}
        )
        if result.status_code != 200:
            print("ElevenLabs preflight failed: HTTP", result.status_code)
            print("Backend diagnostic:", result.json().get("detail"))
            return
        output = Path("data/provider-preflight.mp3")
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(result.content)
        print("ElevenLabs produced", len(result.content), "MP3 bytes")
        print("Audio saved locally:", output.resolve())
        print("Preflight session:", sid)


if __name__ == "__main__":
    main()
