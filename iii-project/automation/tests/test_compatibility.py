import pytest

from app.compatibility import can_donate_red_cells


GROUPS = ("O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+")
EXPECTED_RECIPIENTS = {
    "O-": {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
    "O+": {"O+", "A+", "B+", "AB+"},
    "A-": {"A-", "A+", "AB-", "AB+"},
    "A+": {"A+", "AB+"},
    "B-": {"B-", "B+", "AB-", "AB+"},
    "B+": {"B+", "AB+"},
    "AB-": {"AB-", "AB+"},
    "AB+": {"AB+"},
}


@pytest.mark.parametrize(
    ("donor_group", "patient_group"),
    [(donor, patient) for donor in GROUPS for patient in GROUPS],
)
def test_complete_red_cell_compatibility_matrix(
    donor_group: str, patient_group: str
) -> None:
    expected = patient_group in EXPECTED_RECIPIENTS[donor_group]

    assert can_donate_red_cells(donor_group, patient_group) is expected


@pytest.mark.parametrize(
    ("donor_group", "patient_group"),
    [("X", "O+"), ("O-", "X"), ("X", "X")],
)
def test_invalid_group_is_rejected(
    donor_group: str, patient_group: str
) -> None:
    assert can_donate_red_cells(donor_group, patient_group) is False


def test_compatibility_normalizes_case_and_whitespace() -> None:
    assert can_donate_red_cells(" o- ", " ab+ ") is True
