"""The fixed-quote estimate engine — exact port of design/app/Get Started.dc.html.

    rate  = rate_base + rate_coeff * exp(-sqft / rate_decay_sqft)   # $/sf
    base  = round(sqft * rate / round_to) * round_to
    mult  = multiplier_floor + (score / 100) * multiplier_span
    total = (base + selected addon prices) * mult
    range = total ± range_pct%

Constants live in catalog.EstimateConfig (owner-tunable); addon prices in
catalog.Addon. Floats mirror the design's JS arithmetic; results are quantized
to cents only when persisted.
"""

import math
from dataclasses import dataclass, field

from apps.catalog.models import Addon, EstimateConfig
from apps.jurisdictions.models import State


@dataclass
class EstimateResult:
    sqft: int
    rate: float
    base: float
    addon_total: float
    addons: dict[str, bool]
    multiplier: float
    total: float
    low: float
    high: float
    jurisdiction: dict = field(default_factory=dict)


def compute_estimate(*, sqft: int, state: State, addon_keys: list[str]) -> EstimateResult:
    config = EstimateConfig.get_solo()

    rate = config.rate_base + config.rate_coeff * math.exp(-sqft / config.rate_decay_sqft)
    base = round((sqft * rate) / config.round_to) * config.round_to

    all_addons = {addon.key: addon for addon in Addon.objects.all()}
    selected = {key: (key in addon_keys) for key in all_addons}
    addon_total = float(sum(all_addons[key].price for key in addon_keys if key in all_addons))

    multiplier = config.multiplier_floor + (state.complexity_score / 100) * config.multiplier_span
    total = (base + addon_total) * multiplier
    spread = config.range_pct / 100

    return EstimateResult(
        sqft=sqft,
        rate=rate,
        base=base,
        addon_total=addon_total,
        addons=selected,
        multiplier=multiplier,
        total=total,
        low=total * (1 - spread),
        high=total * (1 + spread),
        jurisdiction={
            "code": state.code,
            "name": state.name,
            "score": state.complexity_score,
            "band": state.band_label,
            "multiplier": round(multiplier, 3),
            "factors": state.factors,
        },
    )
