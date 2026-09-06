#!/usr/bin/env python
"""
SkillTwin OpenAPI Specification Generator
Extracts and writes the OpenAPI schema JSON from the FastAPI application.
Serves as the contract source of truth for Flutter client generation.
"""

import json
import sys
from pathlib import Path

# Add backend directory to sys.path so app can be imported
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app


def export_openapi(output_path: Path):
    openapi_schema = app.openapi()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2)
    print(f"OpenAPI specification successfully exported to: {output_path}")


if __name__ == "__main__":
    out_file = backend_dir / "openapi.json"
    export_openapi(out_file)
