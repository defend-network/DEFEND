from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .office.toolkit import OfficeToolkit


class WorkbookReadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    sheet: str = Field(min_length=1, max_length=64)
    range: str = Field(min_length=1, max_length=64)


class WorkbookWriteRequest(WorkbookReadRequest):
    values: list[list[Any]] = Field(min_length=1)


class WorkbookFormulaRequest(WorkbookReadRequest):
    cell: str = Field(min_length=1, max_length=16)
    formula: str = Field(min_length=2, max_length=1024)


class WorkbookFormatRequest(WorkbookReadRequest):
    bold: bool | None = None
    fill: str | None = Field(default=None, max_length=16)
    number_format: str | None = Field(default=None, max_length=64)


class DocumentReadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class DocumentCreateRequest(DocumentReadRequest):
    title: str | None = Field(default=None, max_length=256)
    paragraphs: list[str] = Field(default_factory=list, max_length=200)


class DocumentEditRequest(DocumentReadRequest):
    replacements: dict[str, str] = Field(default_factory=dict, max_length=100)
    append_paragraph: str | None = Field(default=None, max_length=4000)


class ExportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=1024)


def _not_configured(operation: str) -> dict[str, Any]:
    return {
        "success": False,
        "state": "not_configured",
        "operation": operation,
        "detail": "SCS AI office workspace is not configured",
        "warnings": [],
        "changed": {"ranges": [], "sections": []},
        "data": {},
    }


def build_office_router(toolkit: OfficeToolkit | None) -> APIRouter:
    router = APIRouter(prefix="/v1/office")

    @router.get("/schema")
    def office_schema() -> dict[str, Any]:
        if toolkit is None:
            return {"ok": False, "state": "not_configured", "items": []}
        return {"ok": True, "state": "ready", "items": toolkit.schema()}

    @router.post("/workbook/inspect")
    def workbook_inspect(request: DocumentReadRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("workbook.inspect")
        return toolkit.workbook_inspect(request.path)

    @router.post("/workbook/read")
    def workbook_read(request: WorkbookReadRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("workbook.read")
        return toolkit.workbook_read_range(request.path, sheet=request.sheet, range=request.range)

    @router.post("/workbook/write")
    def workbook_write(request: WorkbookWriteRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("workbook.write_range")
        return toolkit.workbook_write_range(
            request.path, sheet=request.sheet, range=request.range, values=request.values
        )

    @router.post("/workbook/formula")
    def workbook_formula(request: WorkbookFormulaRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("workbook.set_formula")
        return toolkit.workbook_set_formula(
            request.path, sheet=request.sheet, cell=request.cell, formula=request.formula
        )

    @router.post("/workbook/format")
    def workbook_format(request: WorkbookFormatRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("workbook.format_range")
        return toolkit.workbook_format_range(
            request.path,
            sheet=request.sheet,
            range=request.range,
            bold=request.bold,
            fill=request.fill,
            number_format=request.number_format,
        )

    @router.post("/workbook/add-sheet")
    def workbook_add_sheet(request: WorkbookReadRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("workbook.add_sheet")
        return toolkit.workbook_add_sheet(request.path, sheet=request.sheet)

    @router.post("/workbook/export")
    def workbook_export(request: ExportRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("workbook.export")
        return toolkit.workbook_export(request.path, destination=request.destination)

    @router.post("/document/inspect")
    def document_inspect(request: DocumentReadRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("document.inspect")
        return toolkit.document_inspect(request.path)

    @router.post("/document/read")
    def document_read(request: DocumentReadRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("document.read")
        return toolkit.document_read(request.path)

    @router.post("/document/create")
    def document_create(request: DocumentCreateRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("document.create")
        return toolkit.document_create(
            request.path, title=request.title, paragraphs=request.paragraphs
        )

    @router.post("/document/edit")
    def document_edit(request: DocumentEditRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("document.edit")
        return toolkit.document_edit(
            request.path,
            replacements=request.replacements,
            append_paragraph=request.append_paragraph,
        )

    @router.post("/document/export")
    def document_export(request: ExportRequest) -> dict[str, Any]:
        if toolkit is None:
            return _not_configured("document.export")
        return toolkit.document_export(request.path, destination=request.destination)

    return router