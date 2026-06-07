from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models import BloodRequest, CaseRecord, CaseState, Donor
from app.ranking import rank_donors


def make_request(
    units: int = 1,
    blood_group: str = "A+",
    deadline: date | None = None,
) -> BloodRequest:
    return BloodRequest(
        patient_name="Asha",
        blood_group=blood_group,
        units=units,
        hospital="City Hospital",
        city="Dehradun",
        deadline=deadline or date.today() + timedelta(days=3),
        urgency="high",
    )


def test_models_expose_states_defaults_and_case_record_fields() -> None:
    request = make_request()
    now = datetime.now(UTC)
    case = CaseRecord(
        id="C1",
        owner_email="owner@example.com",
        request=request,
        state=CaseState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    donor = Donor(
        id="D1",
        name="Donor",
        blood_group="O-",
        city="Dehradun",
        eligible=True,
        reliability=80,
        fatigue=10,
    )

    assert {state.value for state in CaseState} == {
        "DRAFT",
        "NEEDS_INFORMATION",
        "PLANNED",
        "AWAITING_APPROVAL",
        "OUTREACH_ACTIVE",
        "DONOR_CONFIRMED",
        "COORDINATING",
        "FULFILLED",
        "CANCELLED",
        "EXPIRED",
        "UNFULFILLED",
    }
    assert request.component == "red_cells"
    assert request.diagnosis is None
    assert donor.email is None
    assert donor.phone is None
    assert donor.opted_out is False
    assert case.escalation_level == 0


@pytest.mark.parametrize("units", [0, 21])
def test_blood_request_rejects_units_outside_supported_range(units: int) -> None:
    with pytest.raises(ValidationError):
        make_request(units=units)


def test_models_normalize_blood_groups() -> None:
    request = make_request(blood_group=" a+ ")
    donor = Donor(
        id="D1",
        name="Donor",
        blood_group=" o- ",
        city="Dehradun",
        eligible=True,
        reliability=80,
        fatigue=10,
    )

    assert request.blood_group == "A+"
    assert donor.blood_group == "O-"


@pytest.mark.parametrize("model", ["request", "donor"])
def test_models_reject_invalid_blood_groups(model: str) -> None:
    with pytest.raises(ValidationError):
        if model == "request":
            make_request(blood_group="X")
        else:
            Donor(
                id="D1",
                name="Donor",
                blood_group="X",
                city="Dehradun",
                eligible=True,
                reliability=80,
                fatigue=10,
            )


def test_blood_request_allows_past_deadline() -> None:
    request = make_request(deadline=date.today() - timedelta(days=1))

    assert request.deadline < date.today()


@pytest.mark.parametrize(
    ("field", "value"),
    [("reliability", -1), ("reliability", 101), ("fatigue", -1), ("fatigue", 101)],
)
def test_donor_rejects_scores_outside_percentage_range(
    field: str, value: int
) -> None:
    data = {
        "id": "D1",
        "name": "Donor",
        "blood_group": "O-",
        "city": "Dehradun",
        "eligible": True,
        "reliability": 80,
        "fatigue": 10,
    }
    data[field] = value

    with pytest.raises(ValidationError):
        Donor(**data)


def test_case_record_rejects_negative_escalation_level() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValidationError):
        CaseRecord(
            id="C1",
            owner_email="owner@example.com",
            request=make_request(),
            state=CaseState.DRAFT,
            escalation_level=-1,
            created_at=now,
            updated_at=now,
        )


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_case_record_rejects_naive_timestamps(field: str) -> None:
    now = datetime.now(UTC)
    timestamps = {"created_at": now, "updated_at": now}
    timestamps[field] = datetime.now()

    with pytest.raises(ValidationError):
        CaseRecord(
            id="C1",
            owner_email="owner@example.com",
            request=make_request(),
            state=CaseState.DRAFT,
            **timestamps,
        )


def test_case_record_rejects_updated_before_created() -> None:
    created_at = datetime.now(UTC)

    with pytest.raises(ValidationError):
        CaseRecord(
            id="C1",
            owner_email="owner@example.com",
            request=make_request(),
            state=CaseState.DRAFT,
            created_at=created_at,
            updated_at=created_at - timedelta(seconds=1),
        )


def test_ranking_filters_incompatible_ineligible_and_opted_out_donors() -> None:
    donors = [
        Donor(
            id="D1",
            name="Eligible",
            blood_group="A+",
            city="Dehradun",
            eligible=True,
            reliability=90,
            fatigue=10,
        ),
        Donor(
            id="D2",
            name="Incompatible",
            blood_group="B+",
            city="Dehradun",
            eligible=True,
            reliability=99,
            fatigue=0,
        ),
        Donor(
            id="D3",
            name="Ineligible",
            blood_group="O-",
            city="Dehradun",
            eligible=False,
            reliability=99,
            fatigue=0,
        ),
        Donor(
            id="D4",
            name="Opted out",
            blood_group="O-",
            city="Dehradun",
            eligible=True,
            reliability=99,
            fatigue=0,
            opted_out=True,
        ),
    ]

    ranked = rank_donors(make_request(), donors)

    assert [item.donor.id for item in ranked] == ["D1"]


def test_ranking_scores_clamps_explains_and_orders_donors() -> None:
    donors = [
        Donor(
            id="D3",
            name="Exact outside",
            blood_group="A+",
            city="Delhi",
            eligible=True,
            reliability=80,
            fatigue=20,
        ),
        Donor(
            id="D4",
            name="Low score",
            blood_group="O-",
            city="Delhi",
            eligible=True,
            reliability=0,
            fatigue=100,
        ),
        Donor(
            id="D2",
            name="Compatible local",
            blood_group="O-",
            city="dehradun",
            eligible=True,
            reliability=90,
            fatigue=40,
        ),
        Donor(
            id="D1",
            name="Exact local",
            blood_group="A+",
            city="Dehradun",
            eligible=True,
            reliability=80,
            fatigue=20,
        ),
    ]

    ranked = rank_donors(make_request(), donors)

    assert [(item.donor.id, item.score) for item in ranked] == [
        ("D1", 100),
        ("D2", 95),
        ("D3", 85),
        ("D4", 0),
    ]
    assert ranked[0].reasons == ["compatible", "same city", "exact group"]
    assert ranked[1].reasons == ["compatible", "same city", "compatible group"]
    assert ranked[2].reasons == ["compatible", "outside city", "exact group"]


def test_ranking_orders_tied_scores_by_donor_id() -> None:
    donors = [
        Donor(
            id="D2",
            name="Second",
            blood_group="A+",
            city="Dehradun",
            eligible=True,
            reliability=80,
            fatigue=20,
        ),
        Donor(
            id="D1",
            name="First",
            blood_group="A+",
            city="Dehradun",
            eligible=True,
            reliability=80,
            fatigue=20,
        ),
    ]

    ranked = rank_donors(make_request(), donors)

    assert [item.donor.id for item in ranked] == ["D1", "D2"]


def test_ranking_normalizes_city_whitespace_and_case() -> None:
    request = make_request()
    request.city = " Dehradun "
    donor = Donor(
        id="D1",
        name="Local",
        blood_group="A+",
        city="dEhRaDuN",
        eligible=True,
        reliability=50,
        fatigue=0,
    )

    ranked = rank_donors(request, [donor])

    assert ranked[0].score == 85
    assert "same city" in ranked[0].reasons
