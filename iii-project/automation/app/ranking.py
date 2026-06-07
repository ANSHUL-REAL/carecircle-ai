from app.compatibility import can_donate_red_cells
from app.models import BloodRequest, Donor, RankedDonor


def rank_donors(
    request: BloodRequest, donors: list[Donor], use_ml: bool = False
) -> list[RankedDonor]:
    ranked = []
    for donor in donors:
        if donor.opted_out or not donor.eligible:
            continue
        if not can_donate_red_cells(donor.blood_group, request.blood_group):
            continue

        same_city = donor.city.strip().casefold() == request.city.strip().casefold()
        exact_group = donor.blood_group == request.blood_group
        
        score = donor.reliability - donor.fatigue // 2
        score += 20 if same_city else 0
        score += 15 if exact_group else 5
        
        if use_ml:
            from app.ml_service import predict_donor_active_status
            is_active_pred = predict_donor_active_status(
                gender=getattr(donor, "gender", "Unknown"),
                donor_type=getattr(donor, "donor_type", "Bridge Donor"),
                donations_till_date=getattr(donor, "donations_till_date", 0),
                total_calls=getattr(donor, "total_calls", 0),
                cycle_of_donations=getattr(donor, "cycle_of_donations", 90)
            )
            score += 25 if is_active_pred else -10

        ranked.append(
            RankedDonor(
                donor=donor,
                score=max(0, min(100, score)),
                reasons=[
                    "compatible",
                    "same city" if same_city else "outside city",
                    "exact group" if exact_group else "compatible group",
                ],
            )
        )

    return sorted(ranked, key=lambda item: (-item.score, item.donor.id))
