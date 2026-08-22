"""Market comparison helpers.

Market metrics must report NOT_AVAILABLE (never 0) when valid TT prices are
absent, and post-commence observations are never accepted as a true close.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def is_valid_close(observed_at: Any, commence_at: Any) -> bool:
    observed = parse_dt(observed_at)
    commence = parse_dt(commence_at)
    if observed is None or commence is None:
        return False
    return observed < commence


def market_metrics_status(price_observation_count: int) -> str:
    return "AVAILABLE" if price_observation_count > 0 else "NOT_AVAILABLE"
