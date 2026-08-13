from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from admin_auth import AdminPrincipal, require_admin
from defend_data.admin_rag import (
    MAX_PERMANENT_BATCH_FILES,
    MAX_PERMANENT_FILE_BYTES,
    PermanentRagFile,
    PermanentRagService,
    PermanentRagValidationError,
)


def build_admin_rag_router(service: PermanentRagService | Any) -> APIRouter:
    router = APIRouter(prefix="/api/admin/rag", tags=["admin-rag"])

    @router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
    async def ingest(
        files: list[UploadFile] = File(...),
        principal: AdminPrincipal = Depends(require_admin),
    ):
        if not files:
            raise HTTPException(status_code=400, detail="Choose at least one PDF or DOCX file")
        if len(files) > MAX_PERMANENT_BATCH_FILES:
            raise HTTPException(status_code=400, detail="Permanent RAG accepts at most 20 files per batch")
        inputs: list[PermanentRagFile] = []
        for upload in files:
            data = await upload.read(MAX_PERMANENT_FILE_BYTES + 1)
            inputs.append(
                PermanentRagFile(
                    name=upload.filename or "document",
                    data=data,
                    content_type=upload.content_type,
                )
            )
        try:
            return await service.create_job(inputs, requested_by=principal.account_id)
        except PermanentRagValidationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None

    @router.get("/jobs/{job_id}")
    async def job_status(
        job_id: str,
        _principal: AdminPrincipal = Depends(require_admin),
    ):
        result = service.get_job(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="RAG job not found")
        return result

    @router.get("/documents")
    async def documents(
        _principal: AdminPrincipal = Depends(require_admin),
    ):
        return {"documents": service.list_documents()}

    return router
