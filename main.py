"""Local development entry point."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "meeting_agent.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
