from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.registry.loader import CapabilityRegistryLoader


def create_app() -> FastAPI:
    app = FastAPI(
        title="Capability Service",
        version="0.1.0",
        description="Standalone capability execution service for TianAI runtime.",
    )

    capabilities_dir = Path(__file__).resolve().parent / "capabilities"
    loader = CapabilityRegistryLoader(capabilities_dir=capabilities_dir)
    definitions = loader.load_definitions()
    loader.register_routes(app=app, definitions=definitions)
    app.state.capability_definitions = definitions

    @app.get("/")
    async def root() -> dict[str, object]:
        return {
            "service": "capability-service",
            "status": "ok",
            "capability_count": len(definitions),
        }

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "capabilities": [item.manifest.name for item in definitions],
        }

    @app.get("/capabilities")
    async def list_capabilities() -> dict[str, object]:
        return {
            "items": [
                {
                    "name": item.manifest.name,
                    "kind": item.manifest.kind,
                    "description": item.manifest.description,
                    "method": item.manifest.method,
                    "path": item.manifest.path,
                    "supports_progress": item.manifest.supports_progress,
                }
                for item in definitions
            ]
        }

    return app


app = create_app()

