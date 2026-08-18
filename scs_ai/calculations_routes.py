from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import calculations


class CalculationRequest(BaseModel):
    calculation: str = Field(min_length=1, max_length=64)
    inputs: dict[str, Any] = Field(default_factory=dict)


def build_calculations_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v1/calculations")
    def list_calculations() -> dict[str, object]:
        return {"ok": True, "items": calculations.schema()}

    @router.post("/v1/calculations")
    def run_calculation(request: CalculationRequest) -> dict[str, Any]:
        return calculations.calculate(request.calculation, request.inputs)

    return router