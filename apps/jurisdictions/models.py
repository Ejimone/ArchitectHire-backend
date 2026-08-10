"""The jurisdiction database — the platform's stated moat.

52 states/territories with permit-complexity scores powering pricing (estimate
multiplier), matching (licensure), and the public SEO pages. Band, multiplier,
timeline and factor levels are derived exactly as the design prototype derives
them, so the frontend renders identical values.
"""

from django.db import models

from apps.core.models import TimeStampedModel

FACTOR_NAMES = [
    "Seismic zone",
    "Historic overlay",
    "Climate load",
    "Coastal / flood",
    "Drawing set",
]


class State(TimeStampedModel):
    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=40, unique=True)
    complexity_score = models.PositiveSmallIntegerField()
    region = models.CharField(max_length=20)
    largest_city = models.CharField(max_length=40, blank=True)
    architect_count = models.CharField(
        max_length=16, blank=True, help_text='Display value, e.g. "140+"'
    )

    # State Permit Guide content (populated in the CMS long-tail stage)
    intro = models.TextField(blank=True)
    body1 = models.TextField(blank=True)
    body2 = models.TextField(blank=True)
    permit_steps = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.complexity_score})"

    # --- Derivations mirroring design/app/Get Started.dc.html + Jurisdiction Database ---

    @property
    def band(self) -> str:
        score = self.complexity_score
        return "HIGH" if score > 65 else "MEDIUM" if score > 48 else "LOW"

    @property
    def band_label(self) -> str:
        score = self.complexity_score
        return (
            "High complexity"
            if score > 65
            else "Moderate complexity"
            if score > 48
            else "Low complexity"
        )

    @property
    def multiplier(self) -> float:
        return 1.05 + (self.complexity_score / 100) * 0.35

    @property
    def typical_timeline(self) -> str:
        # Jurisdiction Database bands: High >65, Moderate 49-65, Low <49
        score = self.complexity_score
        if score > 75:
            return "12–18 wks"
        if score > 65:
            return "9–14 wks"
        if score > 48:
            return "7–11 wks"
        return "5–9 wks"

    @property
    def factors(self) -> list[dict]:
        """Deterministic factor levels — exact port of the design's hash formula."""
        score = self.complexity_score
        h = 0
        for ch in self.name:
            h = ((h * 31) + ord(ch)) & 0xFFFFFFFF
        factors = []
        for i, name in enumerate(FACTOR_NAMES):
            lv = max(
                0,
                min(
                    2,
                    round(score / 40)
                    - 1
                    + ((h >> (i * 2)) & 1)
                    + (1 if i == 4 and score > 70 else 0),
                ),
            )
            level = ["LOW", "MODERATE", "HIGH"][lv]
            if name == "Drawing set":
                level = ["STANDARD", "STANDARD", "EXTENSIVE"][lv]
            if name in ("Historic overlay", "Coastal / flood") and lv == 0:
                level = "N/A"
            factors.append({"name": name, "level": level, "lv": lv})
        return factors


class City(TimeStampedModel):
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=80, unique=True)
    state = models.ForeignKey(State, on_delete=models.CASCADE, related_name="cities")
    county = models.CharField(max_length=60, blank=True)
    architect_count = models.CharField(max_length=16, blank=True)

    # City Landing content (populated in the CMS long-tail stage)
    intro = models.TextField(blank=True)
    body1 = models.TextField(blank=True)
    body2 = models.TextField(blank=True)
    permit_facts = models.JSONField(default=list, blank=True)
    service_areas = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cities"

    def __str__(self):
        return f"{self.name}, {self.state.code}"
