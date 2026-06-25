"""FastAPI entrypoint for the ticket-sorter service."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, status

from classifier import classify_ticket
from models import HealthResponse, SortTicketRequest, SortTicketResponse

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("ticket-sorter")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown hook. Nothing to validate — classification is local."""
    yield


app = FastAPI(
    title="Ticket Sorter",
    version="0.1.0",
    description="Rule-based CRM ticket classifier for a digital finance company.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse()


@app.post(
    "/sort-ticket",
    response_model=SortTicketResponse,
    status_code=status.HTTP_200_OK,
    tags=["tickets"],
)
def sort_ticket(payload: SortTicketRequest) -> SortTicketResponse:
    """Classify a customer support ticket using local keyword rules."""
    try:
        return classify_ticket(payload)
    except Exception as exc:  # noqa: BLE001 — last-resort guard
        logger.exception(
            "unexpected error while classifying ticket %s", payload.ticket_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal classification error.",
        ) from exc
