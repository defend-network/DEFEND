"""DEFENDcoder model cost telemetry (versioned, centralized).

Prices are encoded as a versioned snapshot (source + effective_at) so they
can be updated without scattering rates. Estimates are derived from measured
provider usage only; nothing is fabricated. No secrets, no keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


def _usd(value: Decimal | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ModelPricing:
    model: str
    source: str
    effective_at: str
    input_per_1m: Decimal
    cached_input_per_1m: Decimal
    output_per_1m: Decimal

    def estimate(
        self,
        *,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> Decimal:
        uncached_input = max(0, int(input_tokens) - int(cached_input_tokens))
        cost = (
            uncached_input * self.input_per_1m
            + int(cached_input_tokens) * self.cached_input_per_1m
            + int(output_tokens) * self.output_per_1m
        ) / Decimal("1000000")
        return _usd(cost)


#: Current official snapshot (2026-08-22). Update via configuration/metadata;
#: do not scatter prices elsewhere.
DEEPSEEK_V4_FLASH_PRICING = ModelPricing(
    model="deepseek-v4-flash",
    source="deepseek",
    effective_at="2026-08-22",
    input_per_1m=Decimal("0.14"),
    cached_input_per_1m=Decimal("0.0028"),
    output_per_1m=Decimal("0.28"),
)

DEFAULT_PRICING: dict[str, ModelPricing] = {
    "deepseek-v4-flash": DEEPSEEK_V4_FLASH_PRICING,
}

_UNKNOWN = Decimal("0.000000")


def pricing_for(model: str) -> ModelPricing | None:
    return DEFAULT_PRICING.get(model)


def estimate_api_cost(
    model: str,
    *,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
) -> Decimal | None:
    """Estimated API cost in USD for one call, or None when unknown."""
    pricing = pricing_for(model)
    if pricing is None:
        return None
    return pricing.estimate(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
    )


def estimate_gpu_cost(hourly_rate: Decimal | str | None, seconds: int) -> Decimal | None:
    """Estimated compute cost for a GPU runtime (Next lane)."""
    if hourly_rate is None:
        return None
    rate = Decimal(str(hourly_rate))
    hours = Decimal(str(max(0, int(seconds)))) / Decimal("3600")
    return _usd(rate * hours)


@dataclass(frozen=True)
class CostSummary:
    model: str
    api_cost: Decimal | None
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    gpu_seconds: int
    gpu_cost: Decimal | None
    task_success: bool | None = None

    @property
    def total_cost(self) -> Decimal | None:
        parts = [part for part in (self.api_cost, self.gpu_cost) if part is not None]
        if not parts:
            return None
        return _usd(sum(parts))

    @property
    def cost_per_successful_task(self) -> Decimal | None:
        if self.task_success is not True:
            return None
        total = self.total_cost
        return total


def build_cost_summary(
    *,
    model: str,
    api_calls: list[dict[str, object]] | None = None,
    gpu_hourly_rate: Decimal | str | None = None,
    gpu_seconds: int = 0,
    task_success: bool | None = None,
) -> CostSummary:
    """Aggregate per-run cost from measured call usage records."""
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    api_cost = Decimal("0.000000")
    have_api_cost = False
    for call in api_calls or []:
        input_tokens += int(call.get("input_tokens") or 0)
        cached_input_tokens += int(call.get("cached_input_tokens") or 0)
        output_tokens += int(call.get("output_tokens") or 0)
        estimated = estimate_api_cost(
            model,
            input_tokens=int(call.get("input_tokens") or 0),
            cached_input_tokens=int(call.get("cached_input_tokens") or 0),
            output_tokens=int(call.get("output_tokens") or 0),
        )
        if estimated is not None:
            api_cost += estimated
            have_api_cost = True
    if not have_api_cost:
        api_cost = None
    return CostSummary(
        model=model,
        api_cost=_usd(api_cost) if api_cost is not None else None,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        gpu_seconds=max(0, int(gpu_seconds)),
        gpu_cost=estimate_gpu_cost(gpu_hourly_rate, int(gpu_seconds)),
        task_success=task_success,
    )
