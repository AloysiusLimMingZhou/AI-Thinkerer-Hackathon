"""Local development entry point."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "meeting_agent.api:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        access_log=False,  # OAuth codes and scoped media tokens must not enter logs.
    )
