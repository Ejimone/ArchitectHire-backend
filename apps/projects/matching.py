"""The matching engine.

Design contract (Matches.dc.html + Business Wiki):
- Hard filters: architect is live, accepting work, and LICENSED IN THE PROJECT'S
  STATE (stamped work never crosses the stamp line), with capacity headroom.
- Ranking: project-type specialization, reputation, capacity headroom.
- Returns 2–3 matches, capped at 3 by design ("we cap it at three").
- Tags: BEST MATCH (top score), STRONG, HOURLY OPTION (best hourly-capable
  alternative, mirroring the design's third card).
"""

from apps.providers.models import ArchitectProfile, OnboardingStatus

MAX_MATCHES = 3


def _score(profile: ArchitectProfile, project) -> tuple[int, list[str]]:
    score = 70
    reasons = [f"Licensed {project.state.code} · verified"]

    if (
        project.project_type_ref
        and profile.project_types.filter(pk=project.project_type_ref.pk).exists()
    ):
        score += 12
        reasons.append(f"{project.project_type_ref.name} specialist")

    if profile.rating:
        score += min(8, int(float(profile.rating) * 1.6))
        reasons.append(f"★ {profile.rating} across {profile.review_count} reviews")

    active = project.__class__.objects.filter(architect=profile.user, status="underway").count()
    headroom = max(0, profile.capacity - active)
    if headroom >= 2:
        score += 6
        reasons.append("Capacity to start now")
    elif headroom == 1:
        score += 2

    if profile.on_time_rate:
        score += min(4, profile.on_time_rate // 25)

    return min(score, 98), reasons[:3]


def find_matches(project) -> list[dict]:
    """Score eligible architects; return up to MAX_MATCHES as dicts."""
    eligible = (
        ArchitectProfile.objects.filter(
            onboarding_status=OnboardingStatus.APPROVED,
            accepting_work=True,
            licensed_states=project.state,
        )
        .select_related("user")
        .prefetch_related("project_types")
    )

    scored = []
    for profile in eligible:
        active = project.__class__.objects.filter(architect=profile.user, status="underway").count()
        if active >= profile.capacity:
            continue
        score, reasons = _score(profile, project)
        scored.append({"profile": profile, "score": score, "reasons": reasons})

    scored.sort(key=lambda entry: -entry["score"])
    top = scored[:MAX_MATCHES]

    # Tagging: best, strong, and surface an hourly option if one exists in the top set
    for index, entry in enumerate(top):
        entry["tag"] = "BEST MATCH" if index == 0 else "STRONG"
    hourly = next((e for e in top[1:] if e["profile"].engagement_mode in ("hourly", "both")), None)
    if hourly is not None and hourly is not top[0]:
        hourly["tag"] = "HOURLY OPTION"
    return top
