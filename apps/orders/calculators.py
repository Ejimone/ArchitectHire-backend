"""Order price calculators — exact ports of the design's order-flow math.

Render (Order Render.dc.html):
    sub  = unit_price(deliverable, tier) × qty        (qty 1–10)
    rush = +25% of sub                                 ("Rush · 48h (+25%)")

Drafting (Order Drafting.dc.html):
    cad_drafting | redline_cleanup : base = hours × hourly_rate
    asbuilt                        : base = max(minimum, round(sqft × per_sf / 50) × 50)
    pdf_to_cad                     : base = sheets × per_sheet
    stamp                          : +stamp_fee flat ("matched separately")
    rush                           : +25% of (base + stamp)

All constants live in owner-editable models (RenderDeliverable, DraftingConfig).
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.catalog.models import DraftingConfig, RenderDeliverable

RENDER_TIERS = ("Conceptual", "Professional", "Photoreal")
DRAFTING_SERVICES = ("cad_drafting", "asbuilt", "pdf_to_cad", "redline_cleanup")


@dataclass
class Quote:
    kind: str
    config: dict
    subtotal: Decimal
    stamp_amount: Decimal
    rush_amount: Decimal
    total: Decimal

    def as_dict(self):
        return {
            "kind": self.kind,
            "config": self.config,
            "subtotal": str(self.subtotal),
            "stamp_amount": str(self.stamp_amount),
            "rush_amount": str(self.rush_amount),
            "total": str(self.total),
        }


def _round50(value: Decimal) -> Decimal:
    # Mirrors JS Math.round(x/50)*50 (half away from zero on .5 boundaries)
    from decimal import ROUND_HALF_UP

    return (value / 50).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 50


def render_quote(*, deliverable: str, tier: str, qty: int, rush: bool) -> Quote:
    if tier not in RENDER_TIERS:
        raise ValueError(f"Unknown tier '{tier}'")
    if not 1 <= qty <= 10:
        raise ValueError("Quantity must be 1–10")
    try:
        row = RenderDeliverable.objects.get(name=deliverable)
    except RenderDeliverable.DoesNotExist:
        raise ValueError(f"Unknown deliverable '{deliverable}'") from None

    unit = row.price_for(tier)
    subtotal = unit * qty
    rush_amount = (subtotal * Decimal("0.25")).quantize(Decimal("0.01")) if rush else Decimal("0")
    return Quote(
        kind="render",
        config={
            "deliverable": deliverable,
            "tier": tier,
            "qty": qty,
            "unit": row.unit,
            "rush": rush,
        },
        subtotal=subtotal,
        stamp_amount=Decimal("0"),
        rush_amount=rush_amount,
        total=subtotal + rush_amount,
    )


def drafting_quote(*, service: str, size: int, stamp: bool, rush: bool) -> Quote:
    if service not in DRAFTING_SERVICES:
        raise ValueError(f"Unknown service '{service}'")
    config = DraftingConfig.get_solo()

    if service in ("cad_drafting", "redline_cleanup"):
        if not 2 <= size <= 40:
            raise ValueError("Hours must be 2–40")
        base = config.hourly_rate * size
    elif service == "asbuilt":
        if not 400 <= size <= 6000:
            raise ValueError("Square footage must be 400–6,000")
        base = max(config.asbuilt_minimum, _round50(config.asbuilt_per_sf * size))
    else:  # pdf_to_cad
        if not 1 <= size <= 40:
            raise ValueError("Sheets must be 1–40")
        base = config.per_sheet * size

    stamp_amount = config.stamp_fee if stamp else Decimal("0")
    rush_amount = (
        ((base + stamp_amount) * Decimal("0.25")).quantize(Decimal("0.01"))
        if rush
        else Decimal("0")
    )
    return Quote(
        kind="drafting",
        config={"service": service, "size": size, "stamp": stamp, "rush": rush},
        subtotal=base,
        stamp_amount=stamp_amount,
        rush_amount=rush_amount,
        total=base + stamp_amount + rush_amount,
    )
