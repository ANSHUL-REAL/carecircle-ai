from types import MappingProxyType

from app.models import CaseState


ALLOWED_TRANSITIONS = MappingProxyType({
    CaseState.DRAFT: frozenset({
        CaseState.NEEDS_INFORMATION,
        CaseState.PLANNED,
        CaseState.CANCELLED,
    }),
    CaseState.NEEDS_INFORMATION: frozenset({
        CaseState.PLANNED,
        CaseState.CANCELLED,
        CaseState.EXPIRED,
    }),
    CaseState.PLANNED: frozenset({
        CaseState.AWAITING_APPROVAL,
        CaseState.OUTREACH_ACTIVE,
        CaseState.CANCELLED,
    }),
    CaseState.AWAITING_APPROVAL: frozenset({
        CaseState.OUTREACH_ACTIVE,
        CaseState.CANCELLED,
    }),
    CaseState.OUTREACH_ACTIVE: frozenset({
        CaseState.DONOR_CONFIRMED,
        CaseState.UNFULFILLED,
        CaseState.CANCELLED,
        CaseState.EXPIRED,
    }),
    CaseState.DONOR_CONFIRMED: frozenset({
        CaseState.COORDINATING,
        CaseState.CANCELLED,
    }),
    CaseState.COORDINATING: frozenset({
        CaseState.FULFILLED,
        CaseState.CANCELLED,
        CaseState.UNFULFILLED,
    }),
})


def transition(current: CaseState, target: CaseState) -> CaseState:
    if current == target:
        return current
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"Invalid transition: {current} -> {target}")
    return target


def build_outreach_plan(
    donor_ids: list[str], units: int
) -> dict[str, list[str]]:
    if units <= 0:
        raise ValueError("units must be positive")

    unique_donor_ids = list(dict.fromkeys(donor_ids))
    primary_size = max(2, units * 2)
    backup_size = max(2, units * 2)
    backup_end = primary_size + backup_size

    return {
        "primary": unique_donor_ids[:primary_size],
        "backup": unique_donor_ids[primary_size:backup_end],
        "emergency": unique_donor_ids[backup_end:],
    }
