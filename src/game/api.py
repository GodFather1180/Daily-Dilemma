from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.database import get_db
from game.models import (
    Scenario,
    ScenarioOption,
    ScenarioPrediction,
    ScenarioOpinion,  # Feature 5
    GameSession,  # Feature 4
    PartyAnswer,  # Feature 7
)
from user_service.jwt_service import jwt_service

router = APIRouter(prefix="/game", tags=["game"])

# How many real responses we require before using true majority
MIN_RESPONSES_FOR_LIVE_MAJORITY = 35

# ----------------------------------------------------
# FEATURE 7: Party Mode – in-memory session registry
# ----------------------------------------------------

# Very small in-memory registry just for party sessions.
# Key: party_id -> {"player_count": int}
PARTY_SESSIONS: Dict[str, Dict[str, Any]] = {}


class PartySessionCreate(BaseModel):
    player_count: int


class PartyCompleteRequest(BaseModel):
    option_id: int


class PartyPlayerAnswerPayload(BaseModel):
    player_number: int  # 1..N in this party
    option_id: int


class PartyRoundAnswersPayload(BaseModel):
    answers: List[PartyPlayerAnswerPayload]


def _party_player_id(party_id: str) -> str:
    """
    Map a party_id to the synthetic player_id used in ScenarioPrediction.
    This is used ONLY for marking that the party has 'completed' a scenario
    so /party/.../next can skip it.
    """
    return f"party:{party_id}"


# ----------------------------------------------------
# Auth / identity helpers (guest + JWT accounts)
# ----------------------------------------------------

_security = HTTPBearer(auto_error=False)


def optional_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_security),
) -> Optional[Dict[str, Any]]:
    """
    Decode JWT if present. Returns a dict with at least an "id" key,
    or None if no Authorization header was provided.

    We don't hit the DB here; for the game we only need a stable user id
    from the token's `sub` claim.
    """
    if creds is None:
        return None

    payload = jwt_service.validate_token(creds.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    sub = payload.get("sub")
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    return {"id": user_id, "payload": payload}


def resolve_player_id(
    player_id: Optional[str],
    current_user: Optional[Dict[str, Any]],
) -> str:
    """
    Hybrid identity rule used by all game endpoints:

    - If a JWT-authenticated user is present, derive a stable player_id
      from that account (e.g. "user-<id>").
    - Otherwise, require an explicit player_id (guest mode).
    """
    if current_user is not None:
        return f"user-{current_user['id']}"

    if player_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: provide player_id or JWT",
        )

    return player_id


# ----------------------------------------------------
# Helpers (Prediction Mode – Feature 1)
# ----------------------------------------------------


def get_progress(db: Session, player_id: str) -> Dict[str, int]:
    """
    Return answered/total/remaining counts for this player (prediction mode).
    """
    total_count: int = db.query(func.count(Scenario.id)).scalar() or 0

    answered_count: int = (
        db.query(func.count(func.distinct(ScenarioPrediction.scenario_id)))
        .filter(ScenarioPrediction.player_id == player_id)
        .scalar()
        or 0
    )

    remaining_count = max(total_count - answered_count, 0)

    return {
        "answered_count": answered_count,
        "total_count": total_count,
        "remaining_count": remaining_count,
    }


def get_unanswered_scenario(db: Session, player_id: str) -> Scenario | None:
    """
    Return the first scenario the player hasn't answered in prediction mode.
    """
    answered_ids_subq = select(ScenarioPrediction.scenario_id).where(
        ScenarioPrediction.player_id == player_id
    )

    return (
        db.query(Scenario)
        .filter(~Scenario.id.in_(answered_ids_subq))
        .order_by(Scenario.id.asc())
        .first()
    )


# ----------------------------------------------------
# Shared majority helper (Feature 2.1 / 2.2)
# ----------------------------------------------------


def compute_majority_for_scenario(
    db: Session,
    scenario_id: int,
) -> Tuple[Optional[int], int, bool, List[Any]]:
    """
    Shared majority helper.

    Returns:
        majority_option_id: Optional[int]
        total_votes: int
        used_baseline: bool  (True if we fell back to is_baseline_majority)
        rows: list of rows with (id, key, text, is_baseline_majority, votes)

    Behavior:
    - If total_votes == 0: majority_option_id = None.
    - If total_votes < MIN_RESPONSES_FOR_LIVE_MAJORITY: use baseline majority.
    - Else: use real data, with deterministic tie-breaking by smallest option id.
    """
    rows = (
        db.query(
            ScenarioOption.id,
            ScenarioOption.key,
            ScenarioOption.text,
            ScenarioOption.is_baseline_majority,
            func.count(ScenarioPrediction.id).label("votes"),
        )
        .outerjoin(
            ScenarioPrediction,
            ScenarioPrediction.option_id == ScenarioOption.id,
        )
        .filter(ScenarioOption.scenario_id == scenario_id)
        .group_by(
            ScenarioOption.id,
            ScenarioOption.key,
            ScenarioOption.text,
            ScenarioOption.is_baseline_majority,
        )
        .order_by(ScenarioOption.key.asc())
        .all()
    )

    total_votes = sum((row.votes or 0) for row in rows)

    if total_votes == 0:
        # No predictions yet; fall back to baseline majority if one is defined.
        baseline = next((r for r in rows if r.is_baseline_majority), None)
        if baseline is not None:
            return baseline.id, 0, True, rows
        # No baseline defined: truly no majority
        return None, 0, False, rows

    used_baseline = total_votes < MIN_RESPONSES_FOR_LIVE_MAJORITY
    majority_option_id: Optional[int] = None

    if used_baseline:
        # Use the pre-seeded baseline majority if present
        baseline = next((r for r in rows if r.is_baseline_majority), None)
        majority_option_id = baseline.id if baseline else None
    else:
        # Real-data majority with deterministic tie-breaking
        max_votes = max((row.votes or 0) for row in rows)
        candidates = [r for r in rows if (r.votes or 0) == max_votes]
        # Pick the candidate with smallest id to keep behavior deterministic
        winner = min(candidates, key=lambda r: r.id)
        majority_option_id = winner.id

    return majority_option_id, total_votes, used_baseline, rows


def _majority_option_id_or_none(db: Session, scenario_id: int) -> Optional[int]:
    """
    Return the current majority option id for a scenario, or None if neither
    real data nor baseline majority is available.
    """
    majority_option_id, _total_votes, _used_baseline, _rows = (
        compute_majority_for_scenario(db, scenario_id)
    )
    return majority_option_id


# ----------------------------------------------------
# Helpers (Opinion / Personality Mode – Feature 5)
# ----------------------------------------------------


def get_opinion_progress(db: Session, player_id: str) -> Dict[str, int]:
    """
    Return answered/total/remaining counts for this player (opinion mode).
    """
    total_count: int = db.query(func.count(Scenario.id)).scalar() or 0

    answered_count: int = (
        db.query(func.count(func.distinct(ScenarioOpinion.scenario_id)))
        .filter(ScenarioOpinion.player_id == player_id)
        .scalar()
        or 0
    )

    remaining_count = max(total_count - answered_count, 0)

    return {
        "answered_count": answered_count,
        "total_count": total_count,
        "remaining_count": remaining_count,
    }


def get_unanswered_opinion_scenario(db: Session, player_id: str) -> Scenario | None:
    """
    Return the first scenario the player hasn't answered in opinion mode.
    """
    answered_ids_subq = select(ScenarioOpinion.scenario_id).where(
        ScenarioOpinion.player_id == player_id
    )

    return (
        db.query(Scenario)
        .filter(~Scenario.id.in_(answered_ids_subq))
        .order_by(Scenario.id.asc())
        .first()
    )


def serialize_scenario(s: Scenario) -> Dict[str, Any]:
    """
    Turn a Scenario ORM object into the JSON structure expected by the API.
    Used by both prediction and opinion modes.
    """
    return {
        "id": s.id,
        "slug": s.slug,
        "text": s.text,
        "options": [
            {
                "id": o.id,
                "key": o.key,
                "text": o.text,
                "is_baseline_majority": o.is_baseline_majority,
            }
            for o in s.options
        ],
    }


# ----------------------------------------------------
# GET /game/next  (Prediction Mode – Feature 1)
# ----------------------------------------------------


@router.get("/next")
def get_next_scenario(
    player_id: Optional[str] = Query(None, description="Opaque per-player identifier"),
    db: Session = Depends(get_db),
    current_user: Optional[Dict[str, Any]] = Depends(optional_current_user),
) -> Dict[str, Any]:
    """
    Return the next unanswered scenario for this player (prediction mode),
    plus progress (answered/total/remaining). If there are no more scenarios,
    return 404 with a detail payload including progress.
    """
    effective_player_id = resolve_player_id(player_id, current_user)

    scenario = get_unanswered_scenario(db, player_id=effective_player_id)
    progress = get_progress(db, player_id=effective_player_id)

    if not scenario:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "No more scenarios for this player.",
                "progress": progress,
            },
        )

    scenario_payload = serialize_scenario(scenario)

    return {
        **scenario_payload,
        **progress,
    }


# ----------------------------------------------------
# Session logging endpoints: engagement metric (Feature 4)
# ----------------------------------------------------


@router.post("/session/start")
def start_session(
    player_id: str = Query(..., description="Unique player id from frontend"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Mark the start of a play session for this player.
    """
    now = datetime.now(timezone.utc)

    session = GameSession(
        player_id=player_id,
        started_at=now,
        ended_at=None,
    )
    db.add(session)
    db.commit()

    return {"status": "ok"}


@router.post("/session/end")
def end_session(
    player_id: str = Query(..., description="Unique player id from frontend"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Mark the end of the player's most recent open session, if any.
    """
    now = datetime.now(timezone.utc)

    open_session = (
        db.query(GameSession)
        .filter(
            GameSession.player_id == player_id,
            GameSession.ended_at.is_(None),
        )
        .order_by(GameSession.started_at.desc())
        .first()
    )

    if not open_session:
        # Not fatal; just report there isn't anything to close
        return {"status": "no-open-session"}

    open_session.ended_at = now
    db.commit()

    return {"status": "ok"}


# ----------------------------------------------------
# GET /game/opinion/next  (Opinion Mode – Feature 5.1 part)
# ----------------------------------------------------


@router.get("/opinion/next")
def get_next_opinion_scenario(
    player_id: Optional[str] = Query(None, description="Opaque per-player identifier"),
    db: Session = Depends(get_db),
    current_user: Optional[Dict[str, Any]] = Depends(optional_current_user),
) -> Dict[str, Any]:
    """
    Return the next unanswered scenario for this player in PERSONAL OPINION mode,
    plus progress (answered/total/remaining for opinions).
    """
    effective_player_id = resolve_player_id(player_id, current_user)

    scenario = get_unanswered_opinion_scenario(db, player_id=effective_player_id)
    progress = get_opinion_progress(db, player_id=effective_player_id)

    if not scenario:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "No more scenarios for this player in opinion mode.",
                "progress": progress,
            },
        )

    scenario_payload = serialize_scenario(scenario)

    return {
        **scenario_payload,
        **progress,
    }


# ----------------------------------------------------
# GET /game/opinion/summary  (Feature 5.1 – opinion vs majority)
# ----------------------------------------------------


@router.get("/opinion/summary")
def get_opinion_summary(
    player_id: Optional[str] = Query(
        None, description="Opaque player id (from FE localStorage)"
    ),
    db: Session = Depends(get_db),
    current_user: Optional[Dict[str, Any]] = Depends(optional_current_user),
) -> Dict[str, Any]:
    """
    Feature 5.1:
    Summarize how often this player's PERSONAL OPINIONS match the current majority.

    Returns:
        - total_answered: number of scenarios with an opinion
        - compared_count: number of those where a majority exists
        - matched_majority: how many of those matched the majority
        - match_rate: matched_majority / compared_count (0..1), or None
        - details: optional per-scenario breakdown
    """
    effective_player_id = resolve_player_id(player_id, current_user)

    # Get all opinion answers for this player
    rows = (
        db.query(ScenarioOpinion, Scenario, ScenarioOption)
        .join(Scenario, Scenario.id == ScenarioOpinion.scenario_id)
        .join(ScenarioOption, ScenarioOption.id == ScenarioOpinion.option_id)
        .filter(ScenarioOpinion.player_id == effective_player_id)
        .order_by(ScenarioOpinion.id.desc())
        .all()
    )

    total_answered = len(rows)
    if total_answered == 0:
        return {
            "total_answered": 0,
            "compared_count": 0,
            "matched_majority": 0,
            "match_rate": None,
            "details": [],
            "message": "You haven't answered any dilemmas in opinion mode yet.",
        }

    majority_cache: Dict[int, Optional[int]] = {}
    compared_count = 0
    matched_majority = 0
    details: List[Dict[str, Any]] = []

    for opinion, scenario, opt in rows:
        sc_id = scenario.id
        if sc_id not in majority_cache:
            majority_cache[sc_id] = _majority_option_id_or_none(db, sc_id)
        maj_id = majority_cache[sc_id]

        if maj_id is None:
            # No majority defined yet for this scenario; skip for scoring
            details.append(
                {
                    "scenario_id": sc_id,
                    "slug": scenario.slug,
                    "scenario_text": scenario.text,
                    "opinion_option_id": opinion.option_id,
                    "opinion_option_key": opt.key,
                    "majority_option_id": None,
                    "status": "waiting",
                }
            )
            continue

        compared_count += 1
        is_match = opinion.option_id == maj_id
        if is_match:
            matched_majority += 1

        details.append(
            {
                "scenario_id": sc_id,
                "slug": scenario.slug,
                "scenario_text": scenario.text,
                "opinion_option_id": opinion.option_id,
                "opinion_option_key": opt.key,
                "majority_option_id": maj_id,
                "status": "matched" if is_match else "not-matched",
            }
        )

    match_rate: Optional[float] = None
    if compared_count > 0:
        match_rate = matched_majority / compared_count

    return {
        "total_answered": total_answered,
        "compared_count": compared_count,
        "matched_majority": matched_majority,
        "match_rate": match_rate,
        "details": details,
    }


# ----------------------------------------------------
# POST /game/scenarios/{scenario_id}/predict  (Feature 1)
# ----------------------------------------------------


@router.post("/scenarios/{scenario_id}/predict")
def predict(
    scenario_id: int,
    payload: Dict[str, Any],
    player_id: Optional[str] = Query(None, description="Opaque per-player identifier"),
    db: Session = Depends(get_db),
    current_user: Optional[Dict[str, Any]] = Depends(optional_current_user),
) -> Dict[str, Any]:
    """
    Store or update the player's choice for a scenario in PREDICTION mode.

    Body must contain:
      - option_id: int  (the chosen ScenarioOption.id)
    """
    effective_player_id = resolve_player_id(player_id, current_user)

    option_id = payload.get("option_id")
    if option_id is None:
        raise HTTPException(status_code=422, detail="option_id is required")

    scenario = db.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    option = db.get(ScenarioOption, option_id)
    if not option or option.scenario_id != scenario.id:
        raise HTTPException(
            status_code=400,
            detail="Option does not belong to this scenario",
        )

    pred = (
        db.query(ScenarioPrediction)
        .filter(
            ScenarioPrediction.scenario_id == scenario.id,
            ScenarioPrediction.player_id == effective_player_id,
        )
        .one_or_none()
    )

    if pred:
        pred.option_id = option.id
    else:
        pred = ScenarioPrediction(
            scenario_id=scenario.id,
            option_id=option.id,
            player_id=effective_player_id,
        )
        db.add(pred)

    db.commit()
    db.refresh(pred)

    return {
        "prediction_id": pred.id,
        "scenario_id": scenario.id,
        "option_id": pred.option_id,
    }


# ----------------------------------------------------
# POST /game/scenarios/{scenario_id}/opinion  (Feature 5)
# ----------------------------------------------------


@router.post("/scenarios/{scenario_id}/opinion")
def submit_opinion(
    scenario_id: int,
    payload: Dict[str, Any],
    player_id: Optional[str] = Query(None, description="Opaque per-player identifier"),
    db: Session = Depends(get_db),
    current_user: Optional[Dict[str, Any]] = Depends(optional_current_user),
) -> Dict[str, Any]:
    """
    Store or update the player's PERSONAL OPINION for a scenario.

    Body must contain:
      - option_id: int  (the chosen ScenarioOption.id)
    """
    effective_player_id = resolve_player_id(player_id, current_user)

    option_id = payload.get("option_id")
    if option_id is None:
        raise HTTPException(status_code=422, detail="option_id is required")

    scenario = db.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    option = db.get(ScenarioOption, option_id)
    if not option or option.scenario_id != scenario.id:
        raise HTTPException(
            status_code=400,
            detail="Option does not belong to this scenario",
        )

    opinion = (
        db.query(ScenarioOpinion)
        .filter(
            ScenarioOpinion.scenario_id == scenario.id,
            ScenarioOpinion.player_id == effective_player_id,
        )
        .one_or_none()
    )

    if opinion:
        opinion.option_id = option.id
    else:
        opinion = ScenarioOpinion(
            scenario_id=scenario.id,
            option_id=option.id,
            player_id=effective_player_id,
        )
        db.add(opinion)

    db.commit()
    db.refresh(opinion)

    return {
        "opinion_id": opinion.id,
        "scenario_id": opinion.scenario_id,
        "option_id": opinion.option_id,
    }


# ----------------------------------------------------
# GET /game/scenarios/{scenario_id}/result
# Prediction Majority + Per-player correctness (Feature 2.1 + 2.2)
# ----------------------------------------------------


@router.get("/scenarios/{scenario_id}/result")
def get_result(
    scenario_id: int,
    player_id: Optional[str] = Query(
        None,
        description="Opaque per-player identifier"
        " (used to compute your correctness on this scenario)",
    ),
    db: Session = Depends(get_db),
    current_user: Optional[Dict[str, Any]] = Depends(optional_current_user),
) -> Dict[str, Any]:
    """
    Return how people answered a scenario in PREDICTION mode.

    Feature 2.1:
        - Aggregate counts per option and determine majority using real data
          or baseline majority (with threshold).
    Feature 2.2:
        - If a player identity is provided (player_id or JWT), compare that
          player's prediction to the majority and return a clear correctness status:
          "waiting", "revealed-correct", "revealed-incorrect", or "no-prediction".
    """
    scenario = db.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    majority_option_id, total_votes, used_baseline, rows = (
        compute_majority_for_scenario(db, scenario_id)
    )

    option_payloads: List[Dict[str, Any]] = []
    for row in rows:
        share = float(row.votes or 0) / float(total_votes) if total_votes else 0.0
        option_payloads.append(
            {
                "id": row.id,
                "key": row.key,
                "text": row.text,
                "votes": row.votes,
                "share": share,
                "is_baseline_majority": row.is_baseline_majority,
                "is_majority": bool(
                    majority_option_id is not None and row.id == majority_option_id
                ),
            }
        )

    # --- Feature 2.2: per-player correctness on this scenario ----------------
    player_result: Dict[str, Any] = {
        "status": "anonymous",  # default when no identity is provided
        "predicted_option_id": None,
        "predicted_option_key": None,
        "is_correct": None,
    }

    effective_player_id: Optional[str] = None
    if player_id is not None or current_user is not None:
        # If either player_id or JWT is provided, resolve to a stable player id
        effective_player_id = resolve_player_id(player_id, current_user)

    if effective_player_id is not None:
        # Look up this player's prediction for the scenario (if any)
        pred_row = (
            db.query(ScenarioPrediction, ScenarioOption)
            .join(ScenarioOption, ScenarioOption.id == ScenarioPrediction.option_id)
            .filter(
                ScenarioPrediction.scenario_id == scenario.id,
                ScenarioPrediction.player_id == effective_player_id,
            )
            .one_or_none()
        )

        if pred_row is None:
            # Player never answered this scenario
            player_result = {
                "status": "no-prediction",
                "predicted_option_id": None,
                "predicted_option_key": None,
                "is_correct": None,
            }
        else:
            prediction, opt = pred_row

            # If there's no majority yet (no real data and no baseline),
            # we can't mark this prediction as correct/incorrect.
            if majority_option_id is None:
                status = "waiting"
                is_correct = None
            else:
                is_correct = prediction.option_id == majority_option_id
                status = "revealed-correct" if is_correct else "revealed-incorrect"

            player_result = {
                "status": status,
                "predicted_option_id": prediction.option_id,
                "predicted_option_key": opt.key,
                "is_correct": is_correct,
            }

    return {
        "scenario_id": scenario.id,
        "slug": scenario.slug,
        "text": scenario.text,
        "total_votes": total_votes,
        "used_baseline": used_baseline,
        "options": option_payloads,
        "player_result": player_result,
    }


# ----------------------------------------------------
# Analytics dashboard: Feature 4 (scenario stats + median session)
# + Feature 5.2 (opinion stats) + Feature 4.1 (totalPredictions)
# ----------------------------------------------------


@router.get("/analytics")
def analytics_dashboard(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns:
        - scenarios: per-scenario prediction stats (disagreement, correctness)
          plus opinion stats
        - medianSessionLength: median session length (last 7 days) in minutes
    """
    scenarios_payload: List[Dict[str, Any]] = []

    scenarios = db.query(Scenario).all()

    for scenario in scenarios:
        majority_option_id, total_votes, _used_baseline, rows = (
            compute_majority_for_scenario(db, scenario.id)
        )

        # --- Prediction stats ------------------------------------------------
        if total_votes == 0 or not rows:
            option_percentages: Dict[str, float] = {}
            global_correctness_rate: Optional[float] = None
            disagreement_score = 0.0
        else:
            # Option percentages (0–100), keyed by option key ("A", "B", ...)
            option_percentages = {}
            pct_values: List[float] = []

            for row in rows:
                pct = (float(row.votes or 0) / float(total_votes)) * 100.0
                option_percentages[row.key] = pct
                pct_values.append(pct)

            # Disagreement score based on closeness of top two options
            pct_values_sorted = sorted(pct_values, reverse=True)
            if len(pct_values_sorted) >= 2:
                diff = abs(pct_values_sorted[0] - pct_values_sorted[1])
                # 50/50 -> diff=0 -> max disagreement 100
                # 90/10 -> diff=80 -> low disagreement 20
                disagreement_score = 100.0 - diff
            else:
                disagreement_score = 0.0

            # Global correctness rate = % of predictions that match the current majority
            if majority_option_id is not None:
                correct_predictions = (
                    db.query(func.count(ScenarioPrediction.id))
                    .filter(
                        ScenarioPrediction.scenario_id == scenario.id,
                        ScenarioPrediction.option_id == majority_option_id,
                    )
                    .scalar()
                    or 0
                )
                global_correctness_rate = (
                    float(correct_predictions) / float(total_votes)
                ) * 100.0
            else:
                global_correctness_rate = None

        # --- Opinion stats (Feature 5.2) ------------------------------------
        opinion_rows = (
            db.query(
                ScenarioOption.key,
                func.count(ScenarioOpinion.id).label("votes"),
            )
            .outerjoin(
                ScenarioOpinion,
                ScenarioOpinion.option_id == ScenarioOption.id,
            )
            .filter(ScenarioOption.scenario_id == scenario.id)
            .group_by(ScenarioOption.key)
            .all()
        )

        total_opinions = sum((row.votes or 0) for row in opinion_rows)
        opinion_option_percentages: Dict[str, float] = {}

        if total_opinions > 0:
            for row in opinion_rows:
                pct = (float(row.votes or 0) / float(total_opinions)) * 100.0
                opinion_option_percentages[row.key] = pct

        scenarios_payload.append(
            {
                "scenarioId": scenario.id,
                "scenarioText": scenario.text,
                "optionPercentages": option_percentages,
                "globalCorrectnessRate": global_correctness_rate,
                "disagreementScore": disagreement_score,
                "totalPredictions": total_votes,
                "totalOpinions": total_opinions,
                "opinionOptionPercentages": opinion_option_percentages,
            }
        )

    # Order scenarios by "most interesting": highest disagreement first
    scenarios_payload.sort(key=lambda s: s["disagreementScore"], reverse=True)

    median_minutes = _compute_median_session_minutes(db, days=7)

    return {
        "scenarios": scenarios_payload,
        "medianSessionLength": median_minutes,
    }


# ----------------------------------------------------
# Helpers: Engagement metric (median session length)
# ----------------------------------------------------


def _compute_median_session_minutes(db: Session, days: int = 7) -> float | None:
    """
    Compute median session length (in minutes) over the last `days` days,
    based on GameSession rows having both started_at and ended_at.

    Do the timestamp arithmetic in Python so it works on SQLite and Postgres.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    sessions = (
        db.query(GameSession)
        .filter(GameSession.started_at >= cutoff)
        .filter(GameSession.ended_at.isnot(None))
        .all()
    )

    durations: List[float] = []
    for s in sessions:
        if s.started_at is None or s.ended_at is None:
            continue
        delta = s.ended_at - s.started_at
        durations.append(delta.total_seconds() / 60.0)  # minutes

    if not durations:
        return None

    durations.sort()
    n = len(durations)
    mid = n // 2

    if n % 2 == 1:
        return float(durations[mid])
    else:
        return float((durations[mid - 1] + durations[mid]) / 2.0)


# ----------------------------------------------------
# GET /game/scenarios/{scenario_id}/opinion-result (Feature 5)
# ----------------------------------------------------


@router.get("/scenarios/{scenario_id}/opinion-result")
def get_opinion_result(
    scenario_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Return how people answered a scenario in OPINION mode.
    """
    scenario = db.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    rows = (
        db.query(
            ScenarioOption.id,
            ScenarioOption.key,
            ScenarioOption.text,
            func.count(ScenarioOpinion.id).label("votes"),
        )
        .outerjoin(
            ScenarioOpinion,
            ScenarioOpinion.option_id == ScenarioOption.id,
        )
        .filter(ScenarioOption.scenario_id == scenario.id)
        .group_by(
            ScenarioOption.id,
            ScenarioOption.key,
            ScenarioOption.text,
        )
        .order_by(ScenarioOption.key.asc())
        .all()
    )

    total_votes = sum(row.votes or 0 for row in rows)

    option_payloads: List[Dict[str, Any]] = []
    for row in rows:
        share = float(row.votes or 0) / float(total_votes) if total_votes else 0.0
        option_payloads.append(
            {
                "id": row.id,
                "key": row.key,
                "text": row.text,
                "votes": row.votes,
                "share": share,
            }
        )

    return {
        "scenario_id": scenario.id,
        "slug": scenario.slug,
        "text": scenario.text,
        "total_votes": total_votes,
        "options": option_payloads,
    }


# ----------------------------------------------------
# FEATURE 7: Party Mode endpoints (basic flow)
# ----------------------------------------------------


@router.post(
    "/party/sessions",
    status_code=status.HTTP_201_CREATED,
)
def start_party_session(payload: PartySessionCreate) -> Dict[str, Any]:
    """
    Create a new party session.

    - player_count must be between 3 and 8 -> 201
    - otherwise -> 400
    - response: {party_id, player_count, players: [1..N]}
    """
    pc = payload.player_count
    if pc < 3 or pc > 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="player_count must be between 3 and 8",
        )

    party_id = str(uuid.uuid4())
    PARTY_SESSIONS[party_id] = {
        "player_count": pc,
    }

    return {
        "party_id": party_id,
        "player_count": pc,
        "players": list(range(1, pc + 1)),
    }


@router.get("/party/sessions/{party_id}/next")
def party_next(
    party_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get the next unanswered scenario for this party.

    - 404 if party_id is unknown
    - 404 with progress if all scenarios completed
    - otherwise same structure as /game/next (id, text, options, ...)
    """
    if party_id not in PARTY_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown party session",
        )

    player_id = _party_player_id(party_id)

    scenario = get_unanswered_scenario(db, player_id=player_id)
    progress = get_progress(db, player_id=player_id)

    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "No more dilemmas available for this party.",
                "progress": progress,
            },
        )

    return serialize_scenario(scenario)


@router.post("/party/sessions/{party_id}/scenarios/{scenario_id}/complete")
def party_complete(
    party_id: str,
    scenario_id: int,
    body: PartyCompleteRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Record the party's majority choice for a scenario.

    Behaviour required by tests:
    - 404 if party_id is unknown
    - 404 if scenario_id doesn't exist
    - 400 if option_id doesn't exist or doesn't belong to that scenario
    - Idempotent for (party, scenario): one ScenarioPrediction row that may be
      updated, but not duplicated.
    """
    if party_id not in PARTY_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown party session",
        )

    scenario: Optional[Scenario] = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found",
        )

    option = db.get(ScenarioOption, body.option_id)
    if option is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid option_id",
        )

    if option.scenario_id != scenario_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Option does not belong to this scenario",
        )

    player_id = _party_player_id(party_id)

    existing: Optional[ScenarioPrediction] = (
        db.query(ScenarioPrediction)
        .filter(
            ScenarioPrediction.player_id == player_id,
            ScenarioPrediction.scenario_id == scenario_id,
        )
        .one_or_none()
    )

    if existing is None:
        pred = ScenarioPrediction(
            player_id=player_id,
            scenario_id=scenario_id,
            option_id=option.id,
        )
        db.add(pred)
    else:
        existing.option_id = option.id

    db.commit()

    return {
        "party_id": party_id,
        "scenario_id": scenario_id,
        "recorded_option_id": option.id,
    }


# ----------------------------------------------------
# FEATURE 7: Party Mode – per-player answers & summary
# ----------------------------------------------------


@router.post("/party/sessions/{party_id}/scenarios/{scenario_id}/answers")
def party_submit_round_answers(
    party_id: str,
    scenario_id: int,
    payload: PartyRoundAnswersPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Store or update all local player answers for a single party + scenario.

    This does NOT affect global prediction stats; it only writes to PartyAnswer.
    """
    if party_id not in PARTY_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown party session",
        )

    scenario: Optional[Scenario] = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found",
        )

    # Validate and upsert each answer
    for ans in payload.answers:
        if ans.player_number < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="player_number must be >= 1",
            )

        opt = db.get(ScenarioOption, ans.option_id)
        if opt is None or opt.scenario_id != scenario_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid option_id {ans.option_id} for this scenario",
            )

        existing: Optional[PartyAnswer] = (
            db.query(PartyAnswer)
            .filter(
                PartyAnswer.party_id == party_id,
                PartyAnswer.party_player_number == ans.player_number,
                PartyAnswer.scenario_id == scenario_id,
            )
            .one_or_none()
        )

        if existing is None:
            pa = PartyAnswer(
                party_id=party_id,
                party_player_number=ans.player_number,
                scenario_id=scenario_id,
                option_id=ans.option_id,
            )
            db.add(pa)
        else:
            existing.option_id = ans.option_id

    db.commit()

    return {
        "party_id": party_id,
        "scenario_id": scenario_id,
        "saved_answers": len(payload.answers),
    }


# ----------------------------------------------------
# FEATURE 7.2: Party Mode – per-round result
# ----------------------------------------------------


@router.get("/party/sessions/{party_id}/scenarios/{scenario_id}/result")
def party_round_result(
    party_id: str,
    scenario_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Round result for a specific party + scenario (Feature 7.2):

    - For each option: how many party players chose it and what share that is.
    - Which option is the PARTY majority for this round.
    - Which option is the GLOBAL majority for this scenario (prediction mode).
    """
    if party_id not in PARTY_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown party session",
        )

    scenario: Optional[Scenario] = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scenario not found",
        )

    options = (
        db.query(ScenarioOption)
        .filter(ScenarioOption.scenario_id == scenario_id)
        .order_by(ScenarioOption.key.asc())
        .all()
    )

    # Party answers for this scenario
    answers = (
        db.query(PartyAnswer)
        .filter(
            PartyAnswer.party_id == party_id,
            PartyAnswer.scenario_id == scenario_id,
        )
        .all()
    )

    total_party_answers = len(answers)
    counts_by_option_id: Dict[int, int] = {opt.id: 0 for opt in options}
    for pa in answers:
        counts_by_option_id[pa.option_id] = counts_by_option_id.get(pa.option_id, 0) + 1

    # Party-level majority with deterministic tie-breaking (smallest id)
    party_majority_option_id: Optional[int] = None
    if total_party_answers > 0:
        max_votes = max(counts_by_option_id.values())
        candidates = [
            oid for oid, v in counts_by_option_id.items() if v == max_votes and v > 0
        ]
        if candidates:
            party_majority_option_id = min(candidates)

    # Global majority for this scenario (prediction mode)
    global_majority_option_id = _majority_option_id_or_none(db, scenario_id)

    # Did we rely on baseline for global majority?
    total_preds = (
        db.query(func.count(ScenarioPrediction.id))
        .filter(ScenarioPrediction.scenario_id == scenario_id)
        .scalar()
        or 0
    )
    used_global_baseline = total_preds < MIN_RESPONSES_FOR_LIVE_MAJORITY

    option_payloads: List[Dict[str, Any]] = []
    for opt in options:
        party_votes = counts_by_option_id.get(opt.id, 0)
        party_share = (
            float(party_votes) / float(total_party_answers)
            if total_party_answers > 0
            else 0.0
        )
        option_payloads.append(
            {
                "id": opt.id,
                "key": opt.key,
                "text": opt.text,
                "party_votes": party_votes,
                "party_share": party_share,
                "is_party_majority": bool(
                    party_majority_option_id is not None
                    and opt.id == party_majority_option_id
                ),
                "is_global_majority": bool(
                    global_majority_option_id is not None
                    and opt.id == global_majority_option_id
                ),
            }
        )

    return {
        "party_id": party_id,
        "scenario_id": scenario_id,
        "total_party_answers": total_party_answers,
        "party_majority_option_id": party_majority_option_id,
        "global_majority_option_id": global_majority_option_id,
        "used_global_baseline": used_global_baseline,
        "options": option_payloads,
    }


@router.get("/party/sessions/{party_id}/summary")
def party_summary(
    party_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Summarize a party session:

    - For each player_number:
        * how many scenarios they answered
        * how many times they matched the GLOBAL majority
    - A list of the most crowd-aligned players
    - A list of pairs of players that agreed with each other the most
    """
    if party_id not in PARTY_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown party session",
        )

    rows: List[PartyAnswer] = (
        db.query(PartyAnswer)
        .filter(PartyAnswer.party_id == party_id)
        .order_by(PartyAnswer.scenario_id.asc())
        .all()
    )

    if not rows:
        return {
            "party_id": party_id,
            "players": [],
            "top_crowd_aligned_players": [],
            "most_in_sync_pairs": [],
        }

    # Build player -> {scenario_id -> option_id}
    player_answers: Dict[int, Dict[int, int]] = {}
    all_scenario_ids: set[int] = set()

    for pa in rows:
        player_answers.setdefault(pa.party_player_number, {})[pa.scenario_id] = (
            pa.option_id
        )
        all_scenario_ids.add(pa.scenario_id)

    # Compute majority alignment per player using global prediction majority
    majority_cache: Dict[int, Optional[int]] = {}
    player_stats: Dict[int, Dict[str, Any]] = {}

    for player_num, answers_by_scenario in player_answers.items():
        rounds_played = len(answers_by_scenario)
        matched_majority = 0

        for sc_id, opt_id in answers_by_scenario.items():
            if sc_id not in majority_cache:
                majority_cache[sc_id] = _majority_option_id_or_none(db, sc_id)
            maj_id = majority_cache[sc_id]
            if maj_id is not None and opt_id == maj_id:
                matched_majority += 1

        player_stats[player_num] = {
            "player_number": player_num,
            "rounds_played": rounds_played,
            "matched_majority": matched_majority,
            "majority_match_rate": (
                matched_majority / rounds_played if rounds_played > 0 else 0.0
            ),
        }

    # Determine top crowd-aligned players (ties included)
    if player_stats:
        max_match = max(p["matched_majority"] for p in player_stats.values())
        top_crowd_aligned = sorted(
            [
                p["player_number"]
                for p in player_stats.values()
                if p["matched_majority"] == max_match and max_match > 0
            ]
        )
    else:
        top_crowd_aligned = []

    # Pairwise agreement: for each pair (i, j), count how many times they chose
    # the same option in the same scenario.
    player_numbers = sorted(player_answers.keys())
    most_in_sync_pairs: List[Dict[str, Any]] = []
    best_agree_count = 0

    for idx, p1 in enumerate(player_numbers):
        for p2 in player_numbers[idx + 1 :]:
            a1 = player_answers[p1]
            a2 = player_answers[p2]

            shared_scenarios = set(a1.keys()) & set(a2.keys())
            if not shared_scenarios:
                continue

            agree = sum(1 for sc_id in shared_scenarios if a1[sc_id] == a2[sc_id])
            if agree == 0:
                continue

            pair_info = {
                "players": [p1, p2],
                "shared_rounds": len(shared_scenarios),
                "agree_count": agree,
                "agreement_rate": agree / len(shared_scenarios),
            }

            if agree > best_agree_count:
                best_agree_count = agree
                most_in_sync_pairs = [pair_info]
            elif agree == best_agree_count:
                most_in_sync_pairs.append(pair_info)

    return {
        "party_id": party_id,
        "players": sorted(player_stats.values(), key=lambda p: p["player_number"]),
        "top_crowd_aligned_players": top_crowd_aligned,
        "most_in_sync_pairs": most_in_sync_pairs,
    }


# ----------------------------------------------------
# Profile/Alignment Score (Feature 3)
# ----------------------------------------------------


@router.get("/me", tags=["game"])
def get_my_profile(
    # pylint: disable=too-many-locals
    player_id: Optional[str] = Query(
        None, description="Opaque player id (from FE localStorage)"
    ),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Optional[Dict[str, Any]] = Depends(optional_current_user),
) -> Dict[str, Any]:
    """
    Return the player's recent prediction history and alignment percentage.

    This also satisfies Feature 2.2 at an aggregate level by re-evaluating
    which past predictions are correct/incorrect whenever the majority
    updates.
    """
    effective_player_id = resolve_player_id(player_id, current_user)

    order_col = getattr(ScenarioPrediction, "created_at", ScenarioPrediction.id)

    rows = (
        db.query(ScenarioPrediction, Scenario, ScenarioOption)
        .join(Scenario, Scenario.id == ScenarioPrediction.scenario_id)
        .join(ScenarioOption, ScenarioOption.id == ScenarioPrediction.option_id)
        .filter(ScenarioPrediction.player_id == effective_player_id)
        .order_by(order_col.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    majority_cache: Dict[int, Optional[int]] = {}
    history: List[Dict[str, Any]] = []
    revealed = 0
    correct = 0

    for pr, sc, opt in rows:
        if sc.id not in majority_cache:
            majority_cache[sc.id] = _majority_option_id_or_none(db, sc.id)
        maj_id = majority_cache[sc.id]

        if maj_id is None:
            status = "waiting"
        else:
            revealed += 1
            is_correct = pr.option_id == maj_id
            if is_correct:
                correct += 1
            status = "revealed-correct" if is_correct else "revealed-incorrect"

        history.append(
            {
                "scenario_id": sc.id,
                "slug": sc.slug,
                "scenario_text": sc.text,
                "predicted_option_id": pr.option_id,
                "predicted_option_key": opt.key,
                "status": status,
            }
        )

    alignment_percent: Optional[float] = None
    message: Optional[str] = None
    if revealed > 0:
        alignment_percent = round((correct / revealed) * 100.0, 1)
    else:
        message = (
            "No revealed results yet—this number appears once scenarios "
            "you answered unlock."
        )

    return {
        "alignment_percent": alignment_percent,
        "message": message,
        "history": history,
    }
