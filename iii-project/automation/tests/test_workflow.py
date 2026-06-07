import pytest

from app.models import CaseState
from app.workflow import ALLOWED_TRANSITIONS, build_outreach_plan, transition


EXPECTED_TRANSITIONS = {
    CaseState.DRAFT: {
        CaseState.NEEDS_INFORMATION,
        CaseState.PLANNED,
        CaseState.CANCELLED,
    },
    CaseState.NEEDS_INFORMATION: {
        CaseState.PLANNED,
        CaseState.CANCELLED,
        CaseState.EXPIRED,
    },
    CaseState.PLANNED: {
        CaseState.AWAITING_APPROVAL,
        CaseState.OUTREACH_ACTIVE,
        CaseState.CANCELLED,
    },
    CaseState.AWAITING_APPROVAL: {
        CaseState.OUTREACH_ACTIVE,
        CaseState.CANCELLED,
    },
    CaseState.OUTREACH_ACTIVE: {
        CaseState.DONOR_CONFIRMED,
        CaseState.UNFULFILLED,
        CaseState.CANCELLED,
        CaseState.EXPIRED,
    },
    CaseState.DONOR_CONFIRMED: {
        CaseState.COORDINATING,
        CaseState.CANCELLED,
    },
    CaseState.COORDINATING: {
        CaseState.FULFILLED,
        CaseState.CANCELLED,
        CaseState.UNFULFILLED,
    },
}


def test_allowed_transitions_match_the_workflow_plan_exactly() -> None:
    assert ALLOWED_TRANSITIONS == EXPECTED_TRANSITIONS


def test_allowed_transitions_are_immutable() -> None:
    with pytest.raises(TypeError):
        ALLOWED_TRANSITIONS[CaseState.DRAFT] = frozenset()

    assert all(
        isinstance(targets, frozenset)
        for targets in ALLOWED_TRANSITIONS.values()
    )
    with pytest.raises(AttributeError):
        ALLOWED_TRANSITIONS[CaseState.DRAFT].add(CaseState.FULFILLED)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current, targets in EXPECTED_TRANSITIONS.items()
        for target in targets
    ],
)
def test_transition_accepts_every_allowed_move(
    current: CaseState, target: CaseState
) -> None:
    assert transition(current, target) is target


@pytest.mark.parametrize("state", list(CaseState))
def test_transition_is_idempotent_for_every_state(state: CaseState) -> None:
    assert transition(state, state) is state


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current in CaseState
        for target in CaseState
        if current != target
        and target not in EXPECTED_TRANSITIONS.get(current, set())
    ],
)
def test_transition_rejects_every_unlisted_move(
    current: CaseState, target: CaseState
) -> None:
    with pytest.raises(ValueError, match="Invalid transition"):
        transition(current, target)


@pytest.mark.parametrize(
    "terminal",
    [
        CaseState.FULFILLED,
        CaseState.CANCELLED,
        CaseState.EXPIRED,
        CaseState.UNFULFILLED,
    ],
)
def test_terminal_states_have_no_outgoing_transitions(
    terminal: CaseState,
) -> None:
    for target in CaseState:
        if target is terminal:
            assert transition(terminal, target) is terminal
        else:
            with pytest.raises(ValueError, match="Invalid transition"):
                transition(terminal, target)


def test_case_cannot_skip_from_draft_to_fulfilled() -> None:
    with pytest.raises(ValueError, match="Invalid transition"):
        transition(CaseState.DRAFT, CaseState.FULFILLED)


def test_ranked_donors_are_split_into_primary_backup_and_emergency() -> None:
    donor_ids = [f"D{i}" for i in range(10)]

    plan = build_outreach_plan(donor_ids, units=2)

    assert plan == {
        "primary": ["D0", "D1", "D2", "D3"],
        "backup": ["D4", "D5", "D6", "D7"],
        "emergency": ["D8", "D9"],
    }


@pytest.mark.parametrize(
    ("units", "expected_circle_size"),
    [(1, 2), (2, 4), (3, 6), (5, 10)],
)
def test_primary_and_backup_sizes_scale_with_units(
    units: int, expected_circle_size: int
) -> None:
    donor_ids = [f"D{i}" for i in range(expected_circle_size * 2 + 3)]

    plan = build_outreach_plan(donor_ids, units=units)

    assert len(plan["primary"]) == expected_circle_size
    assert len(plan["backup"]) == expected_circle_size
    assert len(plan["emergency"]) == 3


@pytest.mark.parametrize("units", [0, -1])
def test_outreach_plan_rejects_nonpositive_units(units: int) -> None:
    with pytest.raises(ValueError, match="units must be positive"):
        build_outreach_plan(["D0", "D1"], units=units)


def test_too_few_donors_fill_circles_in_priority_order() -> None:
    plan = build_outreach_plan(["D0", "D1", "D2"], units=2)

    assert plan == {
        "primary": ["D0", "D1", "D2"],
        "backup": [],
        "emergency": [],
    }


def test_donor_is_not_repeated_across_outreach_circles() -> None:
    plan = build_outreach_plan(
        ["D0", "D1", "D0", "D2", "D3", "D1", "D4"],
        units=1,
    )

    assert plan == {
        "primary": ["D0", "D1"],
        "backup": ["D2", "D3"],
        "emergency": ["D4"],
    }
    assigned = plan["primary"] + plan["backup"] + plan["emergency"]
    assert len(assigned) == len(set(assigned))
