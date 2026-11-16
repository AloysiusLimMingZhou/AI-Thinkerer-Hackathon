"""Local development entry point."""

import sys

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "meeting_agent.api:app",
        host="127.0.0.1",
        port=8000,
        # Reload mode on Windows uses an event loop that cannot spawn child
        # processes, which stops the Discord voice worker from starting.
        reload=sys.platform != "win32",
        access_log=False,  # OAuth codes and scoped media tokens must not enter logs.
    )
