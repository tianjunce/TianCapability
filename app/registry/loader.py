from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml
from fastapi import Body, FastAPI, status
from fastapi.responses import JSONResponse
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate
from pydantic import ValidationError as PydanticValidationError

from app.schemas.common import (
    CapabilityError,
    CapabilityExecuteRequest,
    CapabilityExecutionError,
    CapabilityManifest,
    CapabilityMeta,
    CapabilityResponse,
)


LOGGER = logging.getLogger(__name__)
HandlerFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class CapabilityDefinition:
    manifest: CapabilityManifest
    handler: HandlerFn
    directory: Path


class CapabilityRegistryLoader:
    def __init__(self, *, capabilities_dir: Path) -> None:
        self.capabilities_dir = capabilities_dir

    def load_definitions(self) -> list[CapabilityDefinition]:
        if not self.capabilities_dir.exists():
            return []

        definitions: list[CapabilityDefinition] = []
        for capability_dir in sorted(self.capabilities_dir.iterdir()):
            if not capability_dir.is_dir():
                continue
            manifest_path = capability_dir / "manifest.yaml"
            handler_path = capability_dir / "handler.py"
            if not manifest_path.exists():
                continue
            if not handler_path.exists():
                raise RuntimeError(f"missing handler.py for capability: {capability_dir.name}")

            manifest = self._load_manifest(manifest_path=manifest_path)
            handler = self._load_handler(capability_dir=capability_dir, manifest=manifest)
            definitions.append(
                CapabilityDefinition(
                    manifest=manifest,
                    handler=handler,
                    directory=capability_dir,
                )
            )
        return definitions

    def register_routes(self, *, app: FastAPI, definitions: list[CapabilityDefinition]) -> None:
        for definition in definitions:
            self._register_route(app=app, definition=definition)

    def _register_route(self, *, app: FastAPI, definition: CapabilityDefinition) -> None:
        async def endpoint(body: Any = Body(...)) -> JSONResponse:
            started_at = time.perf_counter()

            try:
                request = CapabilityExecuteRequest.model_validate(body)
            except PydanticValidationError as exc:
                return self._error_response(
                    http_status=status.HTTP_400_BAD_REQUEST,
                    capability=definition.manifest.name,
                    duration_ms=self._duration_ms(started_at),
                    code="invalid_request",
                    message=self._format_pydantic_error(exc),
                )

            try:
                self._validate_json_schema(
                    schema=definition.manifest.input_schema,
                    payload=request.input,
                )
            except JsonSchemaValidationError as exc:
                return self._error_response(
                    http_status=status.HTTP_400_BAD_REQUEST,
                    capability=definition.manifest.name,
                    duration_ms=self._duration_ms(started_at),
                    code="invalid_input",
                    message=self._format_jsonschema_error(exc),
                )

            try:
                result = definition.handler(
                    request.input,
                    request.context.model_dump(mode="json", exclude_none=True),
                )
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(
                        result,
                        timeout=definition.manifest.timeout_seconds,
                    )
                if not isinstance(result, dict):
                    raise CapabilityExecutionError(
                        code="invalid_output",
                        message="capability handler must return an object",
                    )
                self._validate_json_schema(
                    schema=definition.manifest.output_schema,
                    payload=result,
                )
            except asyncio.TimeoutError:
                return self._error_response(
                    http_status=status.HTTP_504_GATEWAY_TIMEOUT,
                    capability=definition.manifest.name,
                    duration_ms=self._duration_ms(started_at),
                    code="capability_timeout",
                    message=f"capability timed out after {definition.manifest.timeout_seconds}s",
                )
            except JsonSchemaValidationError as exc:
                LOGGER.exception("Output schema validation failed for %s", definition.manifest.name)
                return self._error_response(
                    http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    capability=definition.manifest.name,
                    duration_ms=self._duration_ms(started_at),
                    code="invalid_output",
                    message=self._format_jsonschema_error(exc),
                )
            except CapabilityExecutionError as exc:
                return self._error_response(
                    http_status=self._http_status_for_error_code(exc.code),
                    capability=definition.manifest.name,
                    duration_ms=self._duration_ms(started_at),
                    code=exc.code,
                    message=exc.message,
                )
            except Exception:
                LOGGER.exception("Unhandled error while running capability %s", definition.manifest.name)
                return self._error_response(
                    http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    capability=definition.manifest.name,
                    duration_ms=self._duration_ms(started_at),
                    code="internal_error",
                    message="internal server error",
                )

            return self._success_response(
                capability=definition.manifest.name,
                duration_ms=self._duration_ms(started_at),
                data=result,
            )

        endpoint.__name__ = f"{definition.manifest.name}_endpoint"
        app.add_api_route(
            path=definition.manifest.path,
            endpoint=endpoint,
            methods=[definition.manifest.method],
            tags=["capabilities"],
            summary=definition.manifest.description,
        )

    def _load_manifest(self, *, manifest_path: Path) -> CapabilityManifest:
        raw_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw_data, dict):
            raise RuntimeError(f"manifest must be an object: {manifest_path}")
        return CapabilityManifest.model_validate(raw_data)

    def _load_handler(
        self,
        *,
        capability_dir: Path,
        manifest: CapabilityManifest,
    ) -> HandlerFn:
        module_name = f"app.capabilities.{manifest.name}.handler"
        handler_path = capability_dir / "handler.py"
        spec = importlib.util.spec_from_file_location(module_name, handler_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load handler for capability: {manifest.name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        handler = getattr(module, "handle", None)
        if not callable(handler):
            raise RuntimeError(f"capability handler missing callable 'handle': {manifest.name}")
        return handler

    def _validate_json_schema(self, *, schema: dict[str, Any], payload: dict[str, Any]) -> None:
        if not schema:
            return
        jsonschema_validate(instance=payload, schema=schema)

    def _error_response(
        self,
        *,
        http_status: int,
        capability: str,
        duration_ms: int,
        code: str,
        message: str,
    ) -> JSONResponse:
        payload = CapabilityResponse(
            status="error",
            data=None,
            error=CapabilityError(code=code, message=message),
            meta=CapabilityMeta(capability=capability, duration_ms=duration_ms),
        )
        return JSONResponse(
            status_code=http_status,
            content=payload.model_dump(mode="json"),
        )

    def _success_response(
        self,
        *,
        capability: str,
        duration_ms: int,
        data: dict[str, Any],
    ) -> JSONResponse:
        payload = CapabilityResponse(
            status="success",
            data=data,
            error=None,
            meta=CapabilityMeta(capability=capability, duration_ms=duration_ms),
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=payload.model_dump(mode="json"),
        )

    def _duration_ms(self, started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1000)

    def _format_jsonschema_error(self, exc: JsonSchemaValidationError) -> str:
        location = ".".join(str(part) for part in exc.absolute_path)
        if location:
            return f"{location}: {exc.message}"
        return exc.message

    def _format_pydantic_error(self, exc: PydanticValidationError) -> str:
        first_error = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first_error.get("loc", []))
        message = str(first_error.get("msg") or "invalid request")
        return f"{location}: {message}" if location else message

    def _http_status_for_error_code(self, code: str) -> int:
        if code in {"invalid_request", "invalid_input"}:
            return status.HTTP_400_BAD_REQUEST
        if code in {"internal_error", "invalid_output"}:
            return status.HTTP_500_INTERNAL_SERVER_ERROR
        if code == "capability_timeout":
            return status.HTTP_504_GATEWAY_TIMEOUT
        return status.HTTP_200_OK
