import os
from datetime import UTC, datetime, date, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.auth import Principal
from app.dependencies import (
    get_clock,
    get_messenger,
    get_principal,
    get_outreach_mode,
    get_repository,
    require_admin,
    require_operator,
)
from app.messaging import Messenger
from app.models import BloodRequest, CaseRecord, CaseState, Donor, DonorResponse
from app.ranking import rank_donors
from app.repositories import CaseRepository, IdempotencyConflict
from app.services import CaseService, OutreachService
from app.transcription import transcribe_audio
from app.workflow import build_outreach_plan, transition


class DonorResponseIn(BaseModel):
    donor_id: str
    status: DonorResponse


class CloseCaseIn(BaseModel):
    outcome: Literal["fulfilled", "cancelled"]


class AssistantIn(BaseModel):
    message: str


class PredictCycleIn(BaseModel):
    condition: str
    gender: str
    quantity_required: int = 1
    last_transfusion_date: str


class DonorRegistrationIn(BaseModel):
    name: str
    blood_group: str
    city: str
    country: str = "India"
    last_donation_date: date | None = None
    phone: str | None = None
    email: str | None = None
    gender: str = "Unknown"
    donor_type: str = "Emergency Donor"
    donations_till_date: int = 0
    total_calls: int = 0
    cycle_of_donations: int = 90


def _dataset_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(current_dir), "assets", "carecircle-dataset.json"),
        os.path.join(
            os.path.dirname(os.path.dirname(current_dir)),
            "assets",
            "carecircle-dataset.json",
        ),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


def _load_dataset() -> dict:
    import json

    dataset_path = _dataset_path()
    if not os.path.exists(dataset_path):
        raise HTTPException(status_code=500, detail="Dataset file not found")
    with open(dataset_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _donor_reliability(raw: dict) -> int:
    donations = float(raw.get("donations_till_date") or 0)
    calls = float(raw.get("total_calls") or 0)
    completion_rate = min(1.0, donations / calls) if calls > 0 else (1.0 if donations > 0 else 0.35)
    experience = min(1.0, donations / 8)
    previous_donation = 1.0 if raw.get("donated_earlier") else 0.0
    return _clamp_score(completion_rate * 50 + experience * 35 + previous_donation * 15)


def _donor_fatigue(raw: dict) -> int:
    donations = float(raw.get("donations_till_date") or 0)
    calls = float(raw.get("total_calls") or 0)
    score = min(55, max(0, calls - donations) * 4)
    if float(raw.get("calls_to_donations_ratio") or 0) > 4:
        score += 20
    if str(raw.get("active_status") or "").casefold() == "inactive":
        score += 20
    return _clamp_score(score)


def _is_dataset_donor_eligible(raw: dict) -> bool:
    if str(raw.get("active_status") or "").casefold() == "inactive":
        return False
    next_eligible = raw.get("next_eligible_date")
    if next_eligible:
        try:
            return date.fromisoformat(str(next_eligible)) <= date.today()
        except ValueError:
            pass
    return str(raw.get("eligibility_status") or "").casefold() == "eligible"


def _dataset_donors_as_models(data: dict) -> list[Donor]:
    donors = []
    for raw in data.get("donors", []):
        try:
            donors.append(
                Donor(
                    id=str(raw.get("id") or f"DATA-{uuid4().hex[:8]}"),
                    name=str(raw.get("name") or raw.get("id") or "Dataset Donor"),
                    blood_group=str(raw.get("blood_group") or "O+"),
                    city=str(raw.get("city") or "Hyderabad"),
                    country=str(raw.get("country") or "India"),
                    eligible=_is_dataset_donor_eligible(raw),
                    reliability=_donor_reliability(raw),
                    fatigue=_donor_fatigue(raw),
                    phone=raw.get("phone") or raw.get("phone_number"),
                    email=raw.get("email"),
                    gender=str(raw.get("gender") or "Unknown"),
                    donor_type=str(raw.get("donor_type") or "Emergency Donor"),
                    donations_till_date=int(raw.get("donations_till_date") or 0),
                    total_calls=int(raw.get("total_calls") or 0),
                    cycle_of_donations=int(raw.get("cycle_of_donations") or 90),
                    active_status=raw.get("active_status"),
                    last_donation_date=(
                        date.fromisoformat(str(raw["last_donation_date"]))
                        if raw.get("last_donation_date")
                        else None
                    ),
                    next_eligible_date=(
                        date.fromisoformat(str(raw["next_eligible_date"]))
                        if raw.get("next_eligible_date")
                        else None
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    return donors


def _combined_donors(repo: CaseRepository) -> list[Donor]:
    merged: dict[str, Donor] = {donor.id: donor for donor in _dataset_donors_as_models(_load_dataset())}
    for donor in repo.list_donors():
        merged[donor.id] = donor
    return list(merged.values())


def create_app() -> FastAPI:
    app = FastAPI(title="CareCircle Automation")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    outreach_mode = os.getenv("OUTREACH_MODE", "simulation")

    @app.get("/automation/health")
    def health() -> dict[str, bool | str]:
        return {
            "ok": True,
            "service": "carecircle-automation",
            "outreachMode": outreach_mode,
        }

    @app.post("/automation/transcribe")
    async def transcribe_voice(audio: UploadFile = File(...)) -> dict:
        bucket = os.getenv("TRANSCRIPTION_BUCKET")
        provider = os.getenv("TRANSCRIPTION_PROVIDER", "vosk").casefold()
        if provider == "aws" and not bucket:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TRANSCRIPTION_BUCKET is not configured",
            )
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Microphone audio is empty",
            )
        if len(audio_bytes) > 8 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Microphone recording is too large",
            )
        try:
            transcript = transcribe_audio(
                audio_bytes,
                audio.content_type,
                bucket,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(error),
            ) from error
        except (RuntimeError, TimeoutError) as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(error),
            ) from error
        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No speech was detected",
            )
        return {
            "ok": True,
            "provider": "amazon-transcribe" if provider == "aws" else "vosk-on-aws",
            "transcript": transcript,
        }

    @app.get("/automation/dataset")
    def dataset() -> dict:
        data = _load_dataset()
        return {
            "ok": True,
            "records": data.get("records", []),
            "donors": data.get("donors", []),
            "patients": data.get("patients", []),
            "source_summary": data.get("source_summary", {}),
        }

    @app.post("/automation/donors", status_code=status.HTTP_201_CREATED)
    def register_donor(
        payload: DonorRegistrationIn,
        repo: CaseRepository = Depends(get_repository),
    ) -> dict:
        try:
            from app.ml_service import predict_donor_active_status

            ml_active = predict_donor_active_status(
                gender=payload.gender,
                donor_type=payload.donor_type,
                donations_till_date=payload.donations_till_date,
                total_calls=payload.total_calls,
                cycle_of_donations=payload.cycle_of_donations,
            )
        except Exception:
            ml_active = payload.donations_till_date > 0 or payload.total_calls < 5

        next_eligible = (
            payload.last_donation_date + timedelta(days=payload.cycle_of_donations)
            if payload.last_donation_date
            else date.today()
        )
        eligible = next_eligible <= date.today()
        donor = Donor(
            id=f"DON-{uuid4().hex[:10].upper()}",
            name=payload.name.strip(),
            blood_group=payload.blood_group,
            city=payload.city.strip(),
            country=payload.country.strip() or "India",
            eligible=eligible,
            reliability=80 if ml_active else 45,
            fatigue=10 if ml_active else 35,
            phone=payload.phone,
            email=payload.email,
            gender=payload.gender,
            donor_type=payload.donor_type,
            donations_till_date=payload.donations_till_date,
            total_calls=payload.total_calls,
            cycle_of_donations=payload.cycle_of_donations,
            active_status="Active" if ml_active else "Inactive",
            last_donation_date=payload.last_donation_date,
            next_eligible_date=next_eligible,
        )
        repo.put_donor(donor)
        return {
            "ok": True,
            "provider": "carecircle-automation",
            "model": {
                "framework": "pytorch",
                "donor_active_prediction": ml_active,
            },
            "donor": donor.model_dump(mode="json"),
        }

    @app.post(
        "/automation/cases",
        status_code=status.HTTP_201_CREATED,
        response_model=CaseRecord,
    )
    def create_case(
        request: BloodRequest,
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key"
        ),
        principal: Principal = Depends(get_principal),
        repo: CaseRepository = Depends(get_repository),
        clock: str = Depends(get_clock),
    ) -> CaseRecord:
        if not idempotency_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key header required",
            )
        try:
            return CaseService(repo, lambda: clock).create_case(
                principal.email,
                request,
                idempotency_key,
            )
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/automation/public-match")
    def public_match(
        request: BloodRequest,
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key"
        ),
        repo: CaseRepository = Depends(get_repository),
        clock: str = Depends(get_clock),
    ) -> dict:
        key = idempotency_key or f"public-{uuid4()}"
        owner_email = f"guest-{uuid4().hex[:10]}@carecircle.local"
        case = CaseService(repo, lambda: clock).create_case(
            owner_email,
            request,
            key,
        )
        ranked = rank_donors(request, _combined_donors(repo), use_ml=True)
        plan = build_outreach_plan(
            [item.donor.id for item in ranked],
            request.units,
        )
        updated = _transition_case(
            repo,
            case,
            CaseState.PLANNED,
            clock,
            "PUBLIC_MATCH_PLANNED",
            {"plan": plan, "model": "pytorch-donor-active"},
        )
        try:
            from app.ml_service import predict_patient_frequency

            predicted_frequency = predict_patient_frequency(
                condition=request.diagnosis or "Unknown",
                gender="Unknown",
                quantity_required=request.units,
            )
        except Exception:
            predicted_frequency = None

        return {
            **updated.model_dump(mode="json"),
            "plan": plan,
            "ranked_donors": [
                {
                    "donor": item.donor.model_dump(mode="json"),
                    "score": item.score,
                    "reasons": item.reasons,
                }
                for item in ranked[:12]
            ],
            "model": {
                "framework": "pytorch",
                "donor_ranker": "donor_active_classifier",
                "patient_cycle_regressor": "patient_frequency_regressor",
                "predicted_frequency_days": predicted_frequency,
            },
        }

    @app.get("/automation/cases", response_model=list[CaseRecord])
    def list_cases(
        principal: Principal = Depends(get_principal),
        repo: CaseRepository = Depends(get_repository),
    ) -> list[CaseRecord]:
        cases = repo.list_cases()
        if principal.role == "patient":
            return [
                case
                for case in cases
                if case.owner_email.casefold() == principal.email.casefold()
            ]
        return cases

    @app.get("/automation/cases/{case_id}", response_model=CaseRecord)
    def get_case(
        case_id: str,
        principal: Principal = Depends(get_principal),
        repo: CaseRepository = Depends(get_repository),
    ) -> CaseRecord:
        case = _visible_case(repo, case_id, principal)
        if case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="case not found",
            )
        return case

    @app.post("/automation/cases/{case_id}/answer")
    def answer_case(
        case_id: str,
        principal: Principal = Depends(get_principal),
        repo: CaseRepository = Depends(get_repository),
    ) -> dict:
        case = _visible_case(repo, case_id, principal)
        if case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="case not found",
            )
        return {
            "case_id": case_id,
            "answer": "CareCircle has recorded the request and is ready for planning.",
        }

    @app.post("/automation/cases/{case_id}/plan")
    def plan_case(
        case_id: str,
        principal: Principal = Depends(require_operator),
        repo: CaseRepository = Depends(get_repository),
        clock: str = Depends(get_clock),
    ) -> dict:
        case = _require_case(repo, case_id)
        ranked = rank_donors(case.request, repo.list_donors(), use_ml=True)
        plan = build_outreach_plan(
            [item.donor.id for item in ranked],
            case.request.units,
        )
        updated = _transition_case(
            repo,
            case,
            CaseState.PLANNED,
            clock,
            "CASE_PLANNED",
            {"planned_by": principal.email, "plan": plan},
        )
        return {**updated.model_dump(mode="json"), "plan": plan}

    @app.post("/automation/cases/{case_id}/start", response_model=CaseRecord)
    def start_case(
        case_id: str,
        principal: Principal = Depends(require_operator),
        repo: CaseRepository = Depends(get_repository),
        messenger: Messenger = Depends(get_messenger),
        outreach_mode: str = Depends(get_outreach_mode),
        clock: str = Depends(get_clock),
    ) -> CaseRecord:
        case = _require_case(repo, case_id)
        service = OutreachService(
            repo,
            messenger,
            lambda: clock,
            mode=outreach_mode,
        )
        for item in rank_donors(case.request, repo.list_donors(), use_ml=True)[
            : max(2, case.request.units * 2)
        ]:
            service.prepare(case_id, item.donor.id)
        return _transition_case(
            repo,
            case,
            CaseState.OUTREACH_ACTIVE,
            clock,
            "OUTREACH_STARTED",
            {"started_by": principal.email},
        )

    @app.post("/automation/cases/{case_id}/responses", response_model=CaseRecord)
    def record_response(
        case_id: str,
        response: DonorResponseIn,
        repo: CaseRepository = Depends(get_repository),
        messenger: Messenger = Depends(get_messenger),
        outreach_mode: str = Depends(get_outreach_mode),
        clock: str = Depends(get_clock),
    ) -> CaseRecord:
        case = _require_case(repo, case_id)
        OutreachService(
            repo,
            messenger,
            lambda: clock,
            mode=outreach_mode,
        ).record_response(case_id, response.donor_id, response.status)
        if response.status is DonorResponse.ACCEPTED:
            return _transition_case(
                repo,
                case,
                CaseState.DONOR_CONFIRMED,
                clock,
                "DONOR_CONFIRMED",
                {"donor_id": response.donor_id},
            )
        repo.append_event(
            case_id,
            "DONOR_RESPONSE_RECORDED",
            {"donor_id": response.donor_id, "status": response.status.value},
        )
        return case

    @app.post("/automation/cases/{case_id}/coordinate", response_model=CaseRecord)
    def coordinate_case(
        case_id: str,
        principal: Principal = Depends(require_operator),
        repo: CaseRepository = Depends(get_repository),
        clock: str = Depends(get_clock),
    ) -> CaseRecord:
        return _transition_case(
            repo,
            _require_case(repo, case_id),
            CaseState.COORDINATING,
            clock,
            "COORDINATION_STARTED",
            {"coordinated_by": principal.email},
        )

    @app.post("/automation/cases/{case_id}/close", response_model=CaseRecord)
    def close_case(
        case_id: str,
        close: CloseCaseIn,
        principal: Principal = Depends(require_operator),
        repo: CaseRepository = Depends(get_repository),
        clock: str = Depends(get_clock),
    ) -> CaseRecord:
        case = _require_case(repo, case_id)
        target = (
            CaseState.FULFILLED
            if close.outcome == "fulfilled"
            else CaseState.CANCELLED
        )
        if target is CaseState.FULFILLED and case.state is CaseState.DONOR_CONFIRMED:
            case = _transition_case(
                repo,
                case,
                CaseState.COORDINATING,
                clock,
                "COORDINATION_STARTED",
                {"coordinated_by": principal.email, "implicit": True},
            )
        return _transition_case(
            repo,
            case,
            target,
            clock,
            "CASE_CLOSED",
            {"closed_by": principal.email, "outcome": close.outcome},
        )

    @app.get("/automation/approvals")
    def list_approvals(
        _: Principal = Depends(require_operator),
        repo: CaseRepository = Depends(get_repository),
    ) -> list:
        return repo.list_approvals()

    @app.post("/automation/approvals/{approval_id}/approve")
    def approve(
        approval_id: str,
        principal: Principal = Depends(require_admin),
        repo: CaseRepository = Depends(get_repository),
        messenger: Messenger = Depends(get_messenger),
        outreach_mode: str = Depends(get_outreach_mode),
        clock: str = Depends(get_clock),
    ):
        try:
            return OutreachService(
                repo,
                messenger,
                lambda: clock,
                mode=outreach_mode,
            ).approve(approval_id, principal.email)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/automation/approvals/{approval_id}/reject")
    def reject(
        approval_id: str,
        principal: Principal = Depends(require_admin),
        repo: CaseRepository = Depends(get_repository),
        messenger: Messenger = Depends(get_messenger),
        outreach_mode: str = Depends(get_outreach_mode),
        clock: str = Depends(get_clock),
    ):
        try:
            return OutreachService(
                repo,
                messenger,
                lambda: clock,
                mode=outreach_mode,
            ).reject(approval_id, principal.email)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/automation/tasks")
    def list_tasks(
        _: Principal = Depends(require_operator),
        repo: CaseRepository = Depends(get_repository),
    ) -> list:
        return repo.list_tasks()

    @app.post("/automation/tasks/{task_id}/complete")
    def complete_task(
        task_id: str,
        principal: Principal = Depends(require_operator),
        repo: CaseRepository = Depends(get_repository),
    ):
        for task in repo.list_tasks():
            if task.id == task_id:
                completed = task.model_copy(update={"status": "completed"})
                repo.put_task(completed)
                repo.append_event(
                    task.case_id,
                    "TASK_COMPLETED",
                    {"task_id": task_id, "completed_by": principal.email},
                )
                return completed
        raise HTTPException(status_code=404, detail="task not found")

    @app.post("/automation/assistant")
    def assistant(
        request: AssistantIn,
        _: Principal = Depends(get_principal),
    ) -> dict:
        message = request.message.casefold()
        proposed_action = (
            "create_case"
            if "blood" in message or "request" in message
            else "answer"
        )
        return {
            "proposed_action": proposed_action,
            "mutated": False,
            "requires_confirmation": True,
        }

    @app.post("/automation/train")
    def train_models(
        principal: Principal = Depends(require_admin),
        repo: CaseRepository = Depends(get_repository),
    ) -> dict:
        data = _load_dataset()
        try:
            from app.ml_service import train_and_save_models
            metrics = train_and_save_models(data)
            return {"ok": True, "metrics": metrics}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Training failed: {str(e)}")

    @app.post("/automation/predict-cycle")
    def predict_cycle(
        payload: PredictCycleIn,
        _: Principal = Depends(get_principal),
    ) -> dict:
        try:
            from app.ml_service import predict_patient_frequency
            pred_days = predict_patient_frequency(
                condition=payload.condition,
                gender=payload.gender,
                quantity_required=payload.quantity_required
            )
            # Parse last transfusion date
            last_date = datetime.strptime(payload.last_transfusion_date.strip(), "%Y-%m-%d").date()
            next_date = last_date + timedelta(days=round(pred_days))
            
            return {
                "predicted_frequency_days": round(pred_days, 2),
                "predicted_next_date": next_date.isoformat(),
                "last_transfusion_date": last_date.isoformat()
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Prediction failed: {str(e)}")

    return app


app = create_app()


def _visible_case(
    repo: CaseRepository,
    case_id: str,
    principal: Principal,
) -> CaseRecord | None:
    case = repo.get_case(case_id)
    if case is None:
        return None
    if principal.role == "patient" and case.owner_email.casefold() != (
        principal.email.casefold()
    ):
        return None
    return case


def _require_case(repo: CaseRepository, case_id: str) -> CaseRecord:
    case = repo.get_case(case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="case not found",
        )
    return case


def _transition_case(
    repo: CaseRepository,
    case: CaseRecord,
    target: CaseState,
    clock: str,
    event_type: str,
    payload: dict,
) -> CaseRecord:
    try:
        next_state = transition(case.state, target)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    timestamp = _parse_clock(clock)
    updated = case.model_copy(
        update={"state": next_state, "updated_at": timestamp}
    )
    repo.put_case(updated)
    repo.append_event(updated.id, event_type, payload)
    return updated


def _parse_clock(clock: str) -> datetime:
    parsed = datetime.fromisoformat(clock.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    return parsed.astimezone(UTC)
