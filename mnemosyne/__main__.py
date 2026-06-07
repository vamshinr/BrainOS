"""Run the API: ``python -m mnemosyne`` (defaults to port 8090)."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "mnemosyne.api.app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8090")),
        reload=False,
    )


if __name__ == "__main__":
    main()
