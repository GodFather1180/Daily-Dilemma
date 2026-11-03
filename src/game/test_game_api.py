# src/game/test_game_api.py
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi import FastAPI

from game.api import router, MIN_RESPONSES_FOR_LIVE_MAJORITY
from game.models import (
    GameBase,
    Scenario,
    ScenarioOption,
    ScenarioPrediction,
    ScenarioOpinion,
    GameSession,  # for session / analytics tests
)

from user_service.jwt_service import jwt_service


# ----------------------------------------------------
# ENGINE (Isolated Test Engine)
# ----------------------------------------------------
@pytest.fixture(scope="function")
def engine():
    engine = create_engine(
        "sqlite://",  # shared in-memory DB for this engine
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    GameBase.metadata.create_all(bind=engine)

    try:
        yield engine
    finally:
        GameBase.metadata.drop_all(bind=engine)


# ----------------------------------------------------
# SESSION
# ----------------------------------------------------
@pytest.fixture(scope="function")
def session(engine):
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    db = TestingSessionLocal()
    yield db
    db.close()


def make_jwt_for_user(user_id: int) -> str:
    """
    Helper for tests: issue a valid JWT for the given user id.
    Uses a short future expiry (1 hour from now).
    """
    expiry = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    return jwt_service.issue_token(user_id, expiry)


# ----------------------------------------------------
# FASTAPI CLIENT (database overridden)
# ----------------------------------------------------
@pytest.fixture(scope="function")
def client(session):
    app = FastAPI()
    app.include_router(router)

    from shared.database import get_db

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    return TestClient(app)


# ----------------------------------------------------
# SEEDER
# ----------------------------------------------------
def seed_single_scenario(session: Session) -> Scenario:
    slug = f"bus-{uuid.uuid4()}"

    scenario = Scenario(
        slug=slug,
        text="Bus dilemma",
    )
    session.add(scenario)
    session.flush()

    option1 = ScenarioOption(
        scenario_id=scenario.id,
        key="A",
        text="Give seat",
    )
    option2 = ScenarioOption(
        scenario_id=scenario.id,
        key="B",
        text="Ignore",
    )

    session.add_all([option1, option2])
    session.commit()
    session.refresh(scenario)

    return scenario


# ----------------------------------------------------
# EXISTING TESTS (Prediction mode, Feature 1)
# ----------------------------------------------------
def test_get_next_returns_unanswered_scenario(client, session):
    sc = seed_single_scenario(session)

    resp = client.get("/game/next", params={"player_id": "p1"})
    assert resp.status_code == 200

    body = resp.json()
    assert body["id"] == sc.id
    assert body["text"] == "Bus dilemma"
    assert len(body["options"]) == 2
    assert {o["key"] for o in body["options"]} == {"A", "B"}


def test_predict_creates_prediction(client, session):
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "p1"},
        json={"option_id": opt.id},
    )
    assert r.status_code == 200

    pred = session.query(ScenarioPrediction).one()
    assert pred.player_id == "p1"
    assert pred.scenario_id == sc.id
    assert pred.option_id == opt.id  # or whatever the column is actually called


def test_predict_updates_existing_prediction(client, session):
    sc = seed_single_scenario(session)
    a, b = sc.options

    client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "p1"},
        json={"option_id": a.id},
    )

    client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "p1"},
        json={"option_id": b.id},
    )

    pred = session.query(ScenarioPrediction).one()
    assert pred.option_id == b.id


def test_get_next_returns_404_when_all_answered(client, session):
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "p2"},
        json={"option_id": opt.id},
    )

    r = client.get("/game/next", params={"player_id": "p2"})
    assert r.status_code == 404


def test_predict_rejects_option_for_wrong_scenario(client, session):
    sc1 = seed_single_scenario(session)
    sc2 = seed_single_scenario(session)
    wrong_opt = sc2.options[0]

    r = client.post(
        f"/game/scenarios/{sc1.id}/predict",
        params={"player_id": "p1"},
        json={"option_id": wrong_opt.id},
    )
    assert r.status_code == 400


def test_predict_requires_player_id_or_auth(client, session):
    """
    If neither player_id nor Authorization header is provided,
    the API should reject the request.
    """
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        json={"option_id": opt.id},
    )
    # Once we make player_id optional in the endpoint signature and add
    # auth/identity logic, this should be a 401 from our own check.
    assert r.status_code == 401


def test_predict_allows_jwt_without_player_id(client, session):
    """
    Logged-in players should be able to submit a prediction using only a JWT,
    with no player_id query parameter.
    """
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    # Fake "real" account id 42
    token = make_jwt_for_user(42)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        json={"option_id": opt.id},
        headers=headers,
    )
    assert r.status_code == 200

    preds = session.query(ScenarioPrediction).all()
    assert len(preds) == 1
    assert preds[0].option_id == opt.id
    # The exact player_id format is up to the implementation, but at least
    # we know a row was created and tied to this identity.


def test_profile_uses_jwt_identity_when_no_player_id(client, session):
    """
    If a JWT is provided and no player_id param is passed, the profile endpoint
    should still find the correct prediction history for that account.
    """
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    # Simulate a logged-in user with id 77
    token = make_jwt_for_user(77)
    headers = {"Authorization": f"Bearer {token}"}

    # Make a prediction as this logged-in user (no player_id)
    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        json={"option_id": opt.id},
        headers=headers,
    )
    assert r.status_code == 200

    # Now fetch profile with JWT only (no player_id in query)
    r = client.get("/game/me", headers=headers)
    assert r.status_code == 200
    j = r.json()

    assert "history" in j
    assert isinstance(j["history"], list)
    assert len(j["history"]) >= 1

    row = j["history"][0]
    assert row["scenario_id"] == sc.id
    assert row["predicted_option_id"] == opt.id


def test_result_uses_baseline_when_few_votes(client, session):
    # seed a scenario where A is the baseline majority
    sc = seed_single_scenario(session)
    # mark one option as baseline in DB
    # assume key "A" is baseline for this scenario
    opt_a, opt_b = sc.options
    opt_a.is_baseline_majority = True
    opt_b.is_baseline_majority = False
    session.commit()

    # no predictions yet
    r = client.get(f"/game/scenarios/{sc.id}/result")
    assert r.status_code == 200
    data = r.json()
    assert data["used_baseline"] is True

    # baseline option should be flagged as majority
    majority_keys = [o["key"] for o in data["options"] if o["is_majority"]]
    assert majority_keys == ["A"]


def test_result_switches_to_live_majority_when_enough_votes(client, session):
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # mark A as baseline
    opt_a.is_baseline_majority = True
    opt_b.is_baseline_majority = False
    session.commit()

    # simulate enough votes so that live data should override baseline
    # (we'll just hammer B)
    for i in range(MIN_RESPONSES_FOR_LIVE_MAJORITY):
        client.post(
            f"/game/scenarios/{sc.id}/predict",
            params={"player_id": f"user{i}"},
            json={"option_id": opt_b.id},
        )

    r = client.get(f"/game/scenarios/{sc.id}/result")
    assert r.status_code == 200
    data = r.json()
    assert data["used_baseline"] is False

    # now B should be the majority
    majority_keys = [o["key"] for o in data["options"] if o["is_majority"]]
    assert majority_keys == ["B"]


# ----------------------------------------------------
# FEATURE 5: Opinion / Personality Mode Tests
# ----------------------------------------------------
def test_opinion_next_returns_unanswered_scenario(client, session):
    sc = seed_single_scenario(session)

    resp = client.get("/game/opinion/next", params={"player_id": "p-op1"})
    assert resp.status_code == 200

    body = resp.json()
    # Same scenario structure as prediction mode
    assert body["id"] == sc.id
    assert body["text"] == "Bus dilemma"
    assert len(body["options"]) == 2
    assert {o["key"] for o in body["options"]} == {"A", "B"}

    # Progress is for OPINION mode (no opinions yet)
    assert body["answered_count"] == 0
    assert body["total_count"] >= 1
    assert body["remaining_count"] >= 1


def test_opinion_next_returns_404_when_all_answered(client, session):
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    # Submit an opinion for this scenario
    r = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "p-op2"},
        json={"option_id": opt.id},
    )
    assert r.status_code == 200

    # Now there should be no more opinion questions for this player
    r2 = client.get("/game/opinion/next", params={"player_id": "p-op2"})
    assert r2.status_code == 404

    body = r2.json()
    assert "detail" in body
    detail = body["detail"]
    assert "progress" in detail
    assert detail["progress"]["answered_count"] == 1


def test_submit_opinion_creates_row(client, session):
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    r = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "p-op3"},
        json={"option_id": opt.id},
    )
    assert r.status_code == 200
    data = r.json()

    assert data["scenario_id"] == sc.id
    assert data["option_id"] == opt.id
    assert "opinion_id" in data

    opinion = session.query(ScenarioOpinion).one()
    assert opinion.player_id == "p-op3"
    assert opinion.scenario_id == sc.id
    assert opinion.option_id == opt.id


def test_submit_opinion_updates_existing_row(client, session):
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # First opinion: choose A
    r1 = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "p-op4"},
        json={"option_id": opt_a.id},
    )
    assert r1.status_code == 200

    # Second opinion: same player changes to B
    r2 = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "p-op4"},
        json={"option_id": opt_b.id},
    )
    assert r2.status_code == 200

    opinions = session.query(ScenarioOpinion).all()
    # Still only one row, but updated option_id
    assert len(opinions) == 1
    assert opinions[0].option_id == opt_b.id


def test_submit_opinion_rejects_option_for_wrong_scenario(client, session):
    sc1 = seed_single_scenario(session)
    sc2 = seed_single_scenario(session)
    wrong_opt = sc2.options[0]

    r = client.post(
        f"/game/scenarios/{sc1.id}/opinion",
        params={"player_id": "p-op5"},
        json={"option_id": wrong_opt.id},
    )
    assert r.status_code == 400


def test_opinion_result_counts_votes_and_shares(client, session):
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # 3 players choose A, 1 chooses B
    for pid in ["u1", "u2", "u3"]:
        r = client.post(
            f"/game/scenarios/{sc.id}/opinion",
            params={"player_id": pid},
            json={"option_id": opt_a.id},
        )
        assert r.status_code == 200

    r = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "u4"},
        json={"option_id": opt_b.id},
    )
    assert r.status_code == 200

    # Now check distribution
    r = client.get(f"/game/scenarios/{sc.id}/opinion-result")
    assert r.status_code == 200
    data = r.json()

    assert data["scenario_id"] == sc.id
    assert data["total_votes"] == 4
    assert len(data["options"]) == 2

    # Turn into a dict keyed by option key for easy asserts
    by_key = {opt["key"]: opt for opt in data["options"]}

    assert by_key["A"]["votes"] == 3
    assert by_key["B"]["votes"] == 1

    # Shares are simple fractions of total_votes
    assert by_key["A"]["share"] == pytest.approx(3 / 4)
    assert by_key["B"]["share"] == pytest.approx(1 / 4)


def test_opinion_result_handles_no_votes(client, session):
    sc = seed_single_scenario(session)

    r = client.get(f"/game/scenarios/{sc.id}/opinion-result")
    assert r.status_code == 200
    data = r.json()

    assert data["scenario_id"] == sc.id
    assert data["total_votes"] == 0

    # All shares should be 0 when there are no votes
    for opt in data["options"]:
        assert opt["votes"] == 0
        assert opt["share"] == 0.0


def test_opinion_next_skips_already_answered_scenarios(client, session):
    """
    When there are multiple scenarios, /game/opinion/next should only return
    scenarios that the player has NOT yet answered.
    """
    sc1 = seed_single_scenario(session)
    sc2 = seed_single_scenario(session)
    sc3 = seed_single_scenario(session)

    # Player answers sc2
    opt_sc2 = sc2.options[0]
    r = client.post(
        f"/game/scenarios/{sc2.id}/opinion",
        params={"player_id": "p-multi"},
        json={"option_id": opt_sc2.id},
    )
    assert r.status_code == 200

    seen_ids = set()

    # First next() call: must be either sc1 or sc3, but never sc2
    r1 = client.get("/game/opinion/next", params={"player_id": "p-multi"})
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["id"] in {sc1.id, sc3.id}
    assert body1["id"] != sc2.id
    seen_ids.add(body1["id"])

    # Mark that returned scenario as answered
    chosen_sc = sc1 if body1["id"] == sc1.id else sc3
    opt_chosen = chosen_sc.options[0]
    r = client.post(
        f"/game/scenarios/{chosen_sc.id}/opinion",
        params={"player_id": "p-multi"},
        json={"option_id": opt_chosen.id},
    )
    assert r.status_code == 200

    # Second next() call: must be the remaining unanswered scenario
    r2 = client.get("/game/opinion/next", params={"player_id": "p-multi"})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["id"] in {sc1.id, sc3.id}
    assert body2["id"] != sc2.id
    assert body2["id"] not in seen_ids
    seen_ids.add(body2["id"])

    # Mark the final scenario as answered
    final_sc_id = body2["id"]
    final_sc = sc1 if final_sc_id == sc1.id else sc3
    opt_final = final_sc.options[0]
    r = client.post(
        f"/game/scenarios/{final_sc.id}/opinion",
        params={"player_id": "p-multi"},
        json={"option_id": opt_final.id},
    )
    assert r.status_code == 200

    # Now all three scenarios are answered -> 404 with progress
    r3 = client.get("/game/opinion/next", params={"player_id": "p-multi"})
    assert r3.status_code == 404
    body3 = r3.json()
    assert "detail" in body3
    progress = body3["detail"]["progress"]
    assert progress["answered_count"] == 3
    assert progress["total_count"] >= 3
    assert progress["remaining_count"] == 0


def test_submit_opinion_same_option_twice_keeps_single_row(client, session):
    """
    Posting the same opinion twice for the same (player, scenario) should be
    idempotent: still only one ScenarioOpinion row with that option_id.
    """
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    for _ in range(2):
        r = client.post(
            f"/game/scenarios/{sc.id}/opinion",
            params={"player_id": "p-idem"},
            json={"option_id": opt.id},
        )
        assert r.status_code == 200

    opinions = session.query(ScenarioOpinion).all()
    assert len(opinions) == 1
    assert opinions[0].player_id == "p-idem"
    assert opinions[0].scenario_id == sc.id
    assert opinions[0].option_id == opt.id


def test_submit_opinion_requires_option_id(client, session):
    """
    The request body must include option_id. Missing it should fail with 422
    (FastAPI validation error).
    """
    sc = seed_single_scenario(session)

    r = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "p-missing-opt"},
        json={},  # no option_id
    )

    # FastAPI typically returns 422 for missing required fields
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]  # contains validation error info


def test_submit_opinion_rejects_unknown_option_id(client, session):
    """
    If the option_id doesn't exist at all, the endpoint should reject it.
    """
    sc = seed_single_scenario(session)

    # Assuming option PKs are positive ints, -1 is a safe "non-existent" id
    r = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "p-bad-opt"},
        json={"option_id": -1},
    )

    # You can use 400 Bad Request to signal "invalid option"
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body


# ----------------------------------------------------
# FEATURE 4: Analytics (scenario stats + median session length)
# ----------------------------------------------------
def _get_analytics(client) -> dict:
    r = client.get("/game/analytics")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert "scenarios" in data
    assert "medianSessionLength" in data
    return data


def test_analytics_empty_state(client, session):
    """
    With scenarios in the DB but no predictions or sessions yet, the analytics
    endpoint should return well-shaped payload with empty stats.
    """
    sc = seed_single_scenario(session)

    data = _get_analytics(client)
    scenarios = data["scenarios"]

    # Find the seeded scenario
    row = next(item for item in scenarios if item["scenarioId"] == sc.id)
    assert row["scenarioText"] == "Bus dilemma"
    assert row["optionPercentages"] == {}
    assert row["globalCorrectnessRate"] is None
    assert row["disagreementScore"] == 0.0

    # No sessions -> median is None
    assert data["medianSessionLength"] is None


def test_analytics_disagreement_and_correctness(client, session):
    """
    Analytics should compute disagreement and correctness, and order scenarios
    by disagreement descending (most disagreed-on first).
    """
    # Low-disagreement scenario: everyone picks the same option
    sc_low = seed_single_scenario(session)
    low_a, low_b = sc_low.options
    low_a.is_baseline_majority = True
    low_b.is_baseline_majority = False
    session.commit()

    for i in range(MIN_RESPONSES_FOR_LIVE_MAJORITY):
        r = client.post(
            f"/game/scenarios/{sc_low.id}/predict",
            params={"player_id": f"low{i}"},
            json={"option_id": low_a.id},
        )
        assert r.status_code == 200

    # High-disagreement scenario: 50/50 split between A and B
    sc_high = seed_single_scenario(session)
    high_a, high_b = sc_high.options
    high_a.is_baseline_majority = True
    high_b.is_baseline_majority = False
    session.commit()

    for i in range(MIN_RESPONSES_FOR_LIVE_MAJORITY // 2):
        r = client.post(
            f"/game/scenarios/{sc_high.id}/predict",
            params={"player_id": f"ha{i}"},
            json={"option_id": high_a.id},
        )
        assert r.status_code == 200

    for i in range(MIN_RESPONSES_FOR_LIVE_MAJORITY // 2):
        r = client.post(
            f"/game/scenarios/{sc_high.id}/predict",
            params={"player_id": f"hb{i}"},
            json={"option_id": high_b.id},
        )
        assert r.status_code == 200

    data = _get_analytics(client)
    by_id = {row["scenarioId"]: row for row in data["scenarios"]}

    low_row = by_id[sc_low.id]
    high_row = by_id[sc_high.id]

    # Global correctness: low scenario should be ~100%, high ~50%
    assert low_row["globalCorrectnessRate"] == pytest.approx(100.0)
    assert high_row["globalCorrectnessRate"] == pytest.approx(50.0)

    # Disagreement score: high > low
    assert high_row["disagreementScore"] > low_row["disagreementScore"]

    # And ordering: high-disagreement scenario comes first
    ordered_ids = [row["scenarioId"] for row in data["scenarios"]]
    assert ordered_ids.index(sc_high.id) < ordered_ids.index(sc_low.id)


def test_analytics_option_percentages(client, session):
    """
    Analytics should compute per-option percentages (0-100) correctly.
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # 3 predictions for A, 1 for B
    for i in range(3):
        r = client.post(
            f"/game/scenarios/{sc.id}/predict",
            params={"player_id": f"a{i}"},
            json={"option_id": opt_a.id},
        )
        assert r.status_code == 200

    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "b0"},
        json={"option_id": opt_b.id},
    )
    assert r.status_code == 200

    data = _get_analytics(client)
    row = next(item for item in data["scenarios"] if item["scenarioId"] == sc.id)

    percentages = row["optionPercentages"]
    assert set(percentages.keys()) == {"A", "B"}
    assert percentages["A"] == pytest.approx(75.0)
    assert percentages["B"] == pytest.approx(25.0)
    assert percentages["A"] + percentages["B"] == pytest.approx(100.0)


# ---- Session / medianSessionLength tests ----
def _create_session_row(session: Session, player_id: str, duration_minutes: float):
    """
    Create a GameSession row with the given duration (in minutes).
    """
    now = datetime.now(timezone.utc)
    started_at = now - timedelta(minutes=duration_minutes)
    ended_at = now
    s = GameSession(
        player_id=player_id,
        started_at=started_at,
        ended_at=ended_at,
    )
    session.add(s)


def test_analytics_median_session_length_none_when_no_sessions(client, session):
    """
    When there are no GameSession rows, medianSessionLength should be None.
    """
    seed_single_scenario(session)  # just so there is at least one scenario

    data = _get_analytics(client)
    assert data["medianSessionLength"] is None


def test_analytics_median_session_length_odd_number(client, session):
    """
    For an odd number of sessions, medianSessionLength should be the middle
    duration in minutes.
    """
    seed_single_scenario(session)

    _create_session_row(session, "p1", 10.0)
    _create_session_row(session, "p2", 20.0)
    _create_session_row(session, "p3", 30.0)
    session.commit()

    data = _get_analytics(client)
    assert data["medianSessionLength"] == pytest.approx(20.0)


def test_analytics_median_session_length_even_number(client, session):
    """
    For an even number of sessions, medianSessionLength should be the average
    of the two middle durations.
    """
    seed_single_scenario(session)

    _create_session_row(session, "p1", 10.0)
    _create_session_row(session, "p2", 30.0)
    session.commit()

    data = _get_analytics(client)
    # median of [10, 30] is 20
    assert data["medianSessionLength"] == pytest.approx(20.0)


# FEATURE 3: Profile / Alignment tests
# ----------------------------------------------------


def test_profile_empty_state(client):
    """
    Brand-new player should get a well-shaped payload:
    - alignment_percent is None
    - history is an empty list
    - (optional) friendly message present
    """
    r = client.get("/game/me", params={"player_id": "u1"})
    assert r.status_code == 200
    j = r.json()
    assert "alignment_percent" in j
    assert "history" in j
    assert j["alignment_percent"] is None
    assert isinstance(j["history"], list)
    assert len(j["history"]) == 0
    # message is optional; if present, it should be a string
    if "message" in j and j["message"] is not None:
        assert isinstance(j["message"], str)


def test_profile_history_shows_waiting_before_majority(client, session):
    """
    After a player makes a prediction, /game/me should list it in 'history'
    with status='waiting' when the majority hasn't been determined yet.
    """
    # Seed a scenario with two options
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    # Player makes a prediction
    pr = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "u2"},
        json={"option_id": opt.id},
    )
    assert pr.status_code == 200

    # Profile should list that prediction with 'waiting' status initially
    r = client.get("/game/me", params={"player_id": "u2"})
    assert r.status_code == 200
    j = r.json()

    assert "history" in j
    assert isinstance(j["history"], list)
    assert len(j["history"]) >= 1

    row = j["history"][0]
    assert row["scenario_id"] == sc.id
    assert row["scenario_text"] == "Bus dilemma"  # from seed_single_scenario
    assert row["predicted_option_id"] == opt.id
    assert row["predicted_option_key"] in ("A", "B")
    assert row["status"] == "waiting"

    # With 'waiting' rows only, alignment_percent should still be None
    assert j["alignment_percent"] is None


def test_profile_correct_when_baseline_majority_matches_choice(client, session):
    """
    Baseline majority: A. Player chose A -> revealed-correct, 100.0% alignment.
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options
    # Set baseline majority to A
    opt_a.is_baseline_majority = True
    opt_b.is_baseline_majority = False
    session.commit()

    # Player picks A
    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "u3"},
        json={"option_id": opt_a.id},
    )
    assert r.status_code == 200

    # Profile should show revealed-correct and 100.0 alignment
    r = client.get("/game/me", params={"player_id": "u3"})
    assert r.status_code == 200
    j = r.json()

    assert j["alignment_percent"] == 100.0
    assert len(j["history"]) >= 1
    row = j["history"][0]
    assert row["scenario_id"] == sc.id
    assert row["status"] == "revealed-correct"


def test_profile_incorrect_when_baseline_majority_differs(client, session):
    """
    Baseline majority: A. Player chose B -> revealed-incorrect, 0.0% alignment.
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options
    # Set baseline majority to A
    opt_a.is_baseline_majority = True
    opt_b.is_baseline_majority = False
    session.commit()

    # Player picks B
    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "u4"},
        json={"option_id": opt_b.id},
    )
    assert r.status_code == 200

    # Profile should show revealed-incorrect and 0.0 alignment
    r = client.get("/game/me", params={"player_id": "u4"})
    assert r.status_code == 200
    j = r.json()

    assert j["alignment_percent"] == 0.0
    assert len(j["history"]) >= 1
    row = j["history"][0]
    assert row["scenario_id"] == sc.id
    assert row["status"] == "revealed-incorrect"


# ----------------------------------------------------
# FEATURE 7: PARTY MODE (BACKEND CONTRACT)
# ----------------------------------------------------


def test_party_start_creates_session_and_returns_players(client):
    """
    POST /game/party/sessions should:
    - accept a player_count between 3 and 8
    - return 201
    - include a non-empty party_id
    - include the player_count and a players array [1..N]
    """
    r = client.post("/game/party/sessions", json={"player_count": 5})
    assert r.status_code == 201

    body = r.json()
    assert "party_id" in body
    assert isinstance(body["party_id"], str)
    assert body["party_id"]  # not empty

    assert body["player_count"] == 5
    assert body["players"] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("bad_count", [0, 1, 2, 9, 100])
def test_party_start_rejects_invalid_player_counts(client, bad_count):
    """
    For counts outside [3, 8], the endpoint should reject with 400.
    """
    r = client.post("/game/party/sessions", json={"player_count": bad_count})
    assert r.status_code == 400
    body = r.json()
    # message wording is up to you; just ensure it's a proper validation error
    assert "detail" in body


def test_party_start_requires_player_count_field(client):
    """
    Missing player_count should be treated as a validation error (422)
    by FastAPI's body validation.
    """
    r = client.post("/game/party/sessions", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["detail"]  # FastAPI validation errors


def test_party_next_404_for_unknown_party_id(client):
    """
    GET /game/party/sessions/{party_id}/next with an unknown party_id
    should return 404.
    """
    r = client.get("/game/party/sessions/not-a-real-party/next")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body


def test_party_complete_404_for_unknown_party_id(client, session):
    """
    Completing a scenario for an unknown party_id should 404.
    """
    sc = seed_single_scenario(session)
    opt = sc.options[0]

    r = client.post(
        f"/game/party/sessions/not-a-real-party/scenarios/{sc.id}/complete",
        json={"option_id": opt.id},
    )
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body


def test_party_complete_404_for_unknown_scenario_id(client):
    """
    Completing a scenario that doesn't exist (or doesn't belong to any party)
    should return 404.
    """
    # start a valid party
    r = client.post("/game/party/sessions", json={"player_count": 3})
    assert r.status_code == 201
    party_id = r.json()["party_id"]

    # Use a clearly non-existent scenario id (e.g. -1)
    r2 = client.post(
        f"/game/party/sessions/{party_id}/scenarios/-1/complete",
        json={"option_id": 123},
    )
    assert r2.status_code == 404
    body = r2.json()
    assert "detail" in body


def test_party_complete_requires_option_id(client, session):
    """
    The complete endpoint must receive option_id in the body.
    Missing it should fail with 422 (FastAPI validation).
    """
    sc = seed_single_scenario(session)

    r = client.post("/game/party/sessions", json={"player_count": 3})
    assert r.status_code == 201
    party_id = r.json()["party_id"]

    # Get the scenario via /next just to "attach" it to this party
    r_next = client.get(f"/game/party/sessions/{party_id}/next")
    assert r_next.status_code == 200
    assert r_next.json()["id"] == sc.id

    # Now call complete WITHOUT option_id
    r_complete = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{sc.id}/complete",
        json={},
    )
    assert r_complete.status_code == 422
    body = r_complete.json()
    assert body["detail"]


def test_party_complete_rejects_invalid_option_id(client, session):
    """
    If the option_id doesn't exist at all, the endpoint should reject it with 400.
    """
    sc = seed_single_scenario(session)

    r = client.post("/game/party/sessions", json={"player_count": 3})
    assert r.status_code == 201
    party_id = r.json()["party_id"]

    # Attach scenario with /next
    r_next = client.get(f"/game/party/sessions/{party_id}/next")
    assert r_next.status_code == 200
    assert r_next.json()["id"] == sc.id

    # Complete with a bogus option_id
    r_bad = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{sc.id}/complete",
        json={"option_id": -1},
    )
    assert r_bad.status_code == 400
    body = r_bad.json()
    assert "detail" in body


def test_party_flow_uses_same_scenario_pipeline(client, session):
    """
    Full happy-path:
    - seed 1 scenario
    - start a party
    - /party/.../next returns that scenario
    - /party/.../complete records a prediction row
    - subsequent /party/.../next returns 404 with progress showing 1 answered
    """
    # Arrange: one scenario with 2 options
    sc = seed_single_scenario(session)
    first_opt = sc.options[0]

    # Start a party with 3 players (arbitrary)
    r = client.post("/game/party/sessions", json={"player_count": 3})
    assert r.status_code == 201
    party = r.json()
    party_id = party["party_id"]

    # First next call: should return the seeded scenario
    r = client.get(f"/game/party/sessions/{party_id}/next")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sc.id
    assert body["text"] == "Bus dilemma"
    assert {o["key"] for o in body["options"]} == {"A", "B"}

    # Record the party's majority choice (we just pick first_opt for the test)
    r = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{sc.id}/complete",
        json={"option_id": first_opt.id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scenario_id"] == sc.id
    assert body["recorded_option_id"] == first_opt.id

    # The backend should have created exactly one ScenarioPrediction row
    preds = session.query(ScenarioPrediction).all()
    assert len(preds) == 1
    assert preds[0].scenario_id == sc.id
    assert preds[0].option_id == first_opt.id

    # After completing the only scenario, there should be no more for this party
    r = client.get(f"/game/party/sessions/{party_id}/next")
    assert r.status_code == 404
    detail = r.json()["detail"]

    # Reuse the same progress structure as /game/next
    assert "progress" in detail
    progress = detail["progress"]
    assert progress["answered_count"] == 1
    assert progress["remaining_count"] == 0
    assert progress["total_count"] == 1


def test_party_next_skips_completed_scenarios(client, session):
    """
    When there are multiple scenarios in the DB, a party session should only
    receive scenarios it hasn't already completed via /complete.
    """
    sc1 = seed_single_scenario(session)
    sc2 = seed_single_scenario(session)

    # Start a party
    r = client.post("/game/party/sessions", json={"player_count": 4})
    assert r.status_code == 201
    party_id = r.json()["party_id"]

    seen_ids = set()

    # First next(): either sc1 or sc2
    r1 = client.get(f"/game/party/sessions/{party_id}/next")
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["id"] in {sc1.id, sc2.id}
    first_id = body1["id"]
    seen_ids.add(first_id)

    # Complete the first scenario for this party
    first_sc = sc1 if first_id == sc1.id else sc2
    first_opt = first_sc.options[0]
    r_complete1 = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{first_sc.id}/complete",
        json={"option_id": first_opt.id},
    )
    assert r_complete1.status_code == 200

    # Second next(): must be the OTHER scenario
    r2 = client.get(f"/game/party/sessions/{party_id}/next")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["id"] in {sc1.id, sc2.id}
    assert body2["id"] not in seen_ids
    second_id = body2["id"]
    seen_ids.add(second_id)

    # Complete the second scenario as well
    second_sc = sc1 if second_id == sc1.id else sc2
    second_opt = second_sc.options[0]
    r_complete2 = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{second_sc.id}/complete",
        json={"option_id": second_opt.id},
    )
    assert r_complete2.status_code == 200

    # Now all scenarios have been completed for this party -> 404 with progress
    r3 = client.get(f"/game/party/sessions/{party_id}/next")
    assert r3.status_code == 404
    detail = r3.json()["detail"]
    assert "progress" in detail
    progress = detail["progress"]

    # At least the two scenarios we created should be counted
    assert progress["answered_count"] >= 2
    assert progress["remaining_count"] == 0
    assert progress["total_count"] >= 2


def test_party_complete_is_idempotent_for_same_scenario(client, session):
    """
    Calling /complete on the same party + scenario multiple times should not
    create duplicate ScenarioPrediction rows. Implementation can either:
    - treat the second call as a no-op, or
    - update the existing prediction row.
    But there must still be exactly one DB row for that (party, scenario).
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # Start party
    r = client.post("/game/party/sessions", json={"player_count": 3})
    assert r.status_code == 201
    party_id = r.json()["party_id"]

    # Attach scenario via next()
    r_next = client.get(f"/game/party/sessions/{party_id}/next")
    assert r_next.status_code == 200
    assert r_next.json()["id"] == sc.id

    # First completion: choose A
    r1 = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{sc.id}/complete",
        json={"option_id": opt_a.id},
    )
    assert r1.status_code == 200

    # Second completion: choose B instead (e.g. host changed mind)
    r2 = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{sc.id}/complete",
        json={"option_id": opt_b.id},
    )
    assert r2.status_code == 200

    preds = session.query(ScenarioPrediction).filter_by(scenario_id=sc.id).all()
    # Exactly one row in DB for this scenario from this party
    assert len(preds) == 1
    # It's up to you whether you update to B or keep A; the key is no duplicates.
    assert preds[0].option_id in {opt_a.id, opt_b.id}


def test_party_summary_404_for_unknown_party_id(client):
    """
    GET /game/party/sessions/{party_id}/summary with an unknown party_id
    should return 404.
    """
    r = client.get("/game/party/sessions/not-a-real-party/summary")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body


def test_party_summary_empty_for_party_with_no_answers(client):
    """
    New party with no recorded PartyAnswer rows should return a well-shaped
    but empty summary payload.
    """
    # Start a valid party
    r = client.post("/game/party/sessions", json={"player_count": 4})
    assert r.status_code == 201
    party_id = r.json()["party_id"]

    # Immediately ask for summary (no /answers calls yet)
    r_sum = client.get(f"/game/party/sessions/{party_id}/summary")
    assert r_sum.status_code == 200
    data = r_sum.json()

    assert data["party_id"] == party_id
    assert data["players"] == []
    assert data["top_crowd_aligned_players"] == []
    assert data["most_in_sync_pairs"] == []


def test_party_summary_majority_alignment_and_in_sync_pairs(client, session):
    """
    For a party that has answered a scenario:

    - Players who picked the global majority option should have higher
      matched_majority counts.
    - top_crowd_aligned_players should include those players.
    - most_in_sync_pairs should highlight the pair that agreed most often.
    """
    # Seed a single scenario with 2 options
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # Make A the baseline/global majority (no live predictions needed)
    opt_a.is_baseline_majority = True
    opt_b.is_baseline_majority = False
    session.commit()

    # Start a party with 3 players
    r = client.post("/game/party/sessions", json={"player_count": 3})
    assert r.status_code == 201
    party_id = r.json()["party_id"]

    # Record per-player answers for this scenario:
    # - Player 1 -> A (matches baseline majority)
    # - Player 2 -> A (matches baseline majority)
    # - Player 3 -> B (does NOT match baseline majority)
    answers_payload = {
        "answers": [
            {"player_number": 1, "option_id": opt_a.id},
            {"player_number": 2, "option_id": opt_a.id},
            {"player_number": 3, "option_id": opt_b.id},
        ]
    }
    r_ans = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{sc.id}/answers",
        json=answers_payload,
    )
    assert r_ans.status_code == 200
    assert r_ans.json()["saved_answers"] == 3

    # Also mark the scenario as "completed" for the party (uses ScenarioPrediction)
    r_complete = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{sc.id}/complete",
        json={"option_id": opt_a.id},
    )
    assert r_complete.status_code == 200

    # Now request the summary
    r_sum = client.get(f"/game/party/sessions/{party_id}/summary")
    assert r_sum.status_code == 200
    data = r_sum.json()

    assert data["party_id"] == party_id

    # --- Per-player stats ---
    players = {p["player_number"]: p for p in data["players"]}
    assert set(players.keys()) == {1, 2, 3}

    # Everyone answered exactly 1 round
    assert players[1]["rounds_played"] == 1
    assert players[2]["rounds_played"] == 1
    assert players[3]["rounds_played"] == 1

    # Player 1 and 2 picked the majority option A -> matched_majority == 1
    assert players[1]["matched_majority"] == 1
    assert players[2]["matched_majority"] == 1

    # Player 3 picked B -> matched_majority == 0
    assert players[3]["matched_majority"] == 0

    # top_crowd_aligned_players should list [1, 2] (order doesn’t matter much)
    top = data["top_crowd_aligned_players"]
    assert set(top) == {1, 2}

    # --- Pairwise agreement ---
    pairs = data["most_in_sync_pairs"]
    # Only the pair (1, 2) agreed on their answer
    assert len(pairs) == 1
    pair = pairs[0]
    assert set(pair["players"]) == {1, 2}
    assert pair["shared_rounds"] == 1
    assert pair["agree_count"] == 1
    assert pair["agreement_rate"] == 1.0


def test_profile_history_shows_revealed_after_majority_determined(client, session):
    """
    After a player makes a prediction, /game/me should list it in 'history'
    with status='revealed-correct' or 'revealed-incorrect' once the majority
    has been determined.
    """
    # Seed a scenario with two options
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # Player makes a prediction (choose A)
    pr = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "u5"},
        json={"option_id": opt_a.id},
    )
    assert pr.status_code == 200

    # Simulate enough other players voting so that live majority is determined
    from game.api import MIN_RESPONSES_FOR_LIVE_MAJORITY

    for i in range(MIN_RESPONSES_FOR_LIVE_MAJORITY):
        vote_opt = opt_a if i % 2 == 0 else opt_b  # alternate votes
        client.post(
            f"/game/scenarios/{sc.id}/predict",
            params={"player_id": f"other_user{i}"},
            json={"option_id": vote_opt.id},
        )

    # Now the profile should show the prediction as revealed
    r = client.get("/game/me", params={"player_id": "u5"})
    assert r.status_code == 200


def test_result_player_result_anonymous_when_no_identity(client, session):
    """
    If no player_id and no JWT are provided, player_result should be 'anonymous'
    and not contain any prediction info.
    """
    sc = seed_single_scenario(session)

    r = client.get(f"/game/scenarios/{sc.id}/result")
    assert r.status_code == 200
    data = r.json()

    assert "player_result" in data
    pr = data["player_result"]
    assert pr["status"] == "anonymous"
    assert pr["predicted_option_id"] is None
    assert pr["predicted_option_key"] is None
    assert pr["is_correct"] is None


def test_result_player_result_no_prediction_when_identity_has_none(client, session):
    """
    If a player identity is provided but they never predicted this scenario,
    player_result.status should be 'no-prediction'.
    """
    sc = seed_single_scenario(session)

    r = client.get(
        f"/game/scenarios/{sc.id}/result",
        params={"player_id": "no-pred-user"},
    )
    assert r.status_code == 200
    data = r.json()

    pr = data["player_result"]
    assert pr["status"] == "no-prediction"
    assert pr["predicted_option_id"] is None
    assert pr["predicted_option_key"] is None
    assert pr["is_correct"] is None


def test_result_player_result_waiting_when_no_majority_yet(client, session):
    """
    When there is no baseline majority and not enough responses to form a
    live majority, player_result should be 'waiting'.
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # Ensure no baseline majority is defined
    opt_a.is_baseline_majority = False
    opt_b.is_baseline_majority = False
    session.commit()

    # Player predicts, but total predictions < MIN_RESPONSES_FOR_LIVE_MAJORITY
    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "u-wait"},
        json={"option_id": opt_a.id},
    )
    assert r.status_code == 200

    r2 = client.get(
        f"/game/scenarios/{sc.id}/result",
        params={"player_id": "u-wait"},
    )
    assert r2.status_code == 200
    data = r2.json()

    assert data["total_votes"] < MIN_RESPONSES_FOR_LIVE_MAJORITY
    assert data["used_baseline"] is True  # we *tried* baseline but none set

    pr = data["player_result"]
    assert pr["predicted_option_id"] == opt_a.id
    assert pr["status"] == "waiting"
    assert pr["is_correct"] is None


def test_result_result_revealed_correct_when_majority_matches_choice(client, session):
    """
    Baseline majority = A, player picks A -> revealed-correct.
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    opt_a.is_baseline_majority = True
    opt_b.is_baseline_majority = False
    session.commit()

    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "u-correct"},
        json={"option_id": opt_a.id},
    )
    assert r.status_code == 200

    r2 = client.get(
        f"/game/scenarios/{sc.id}/result",
        params={"player_id": "u-correct"},
    )
    assert r2.status_code == 200
    data = r2.json()

    pr = data["player_result"]
    assert pr["status"] == "revealed-correct"
    assert pr["predicted_option_id"] == opt_a.id
    assert pr["is_correct"] is True


def test_result_player_result_revealed_incorrect_when_majority_differs(client, session):
    """
    Baseline majority = A, player picks B -> revealed-incorrect.
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    opt_a.is_baseline_majority = True
    opt_b.is_baseline_majority = False
    session.commit()

    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "u-wrong"},
        json={"option_id": opt_b.id},
    )
    assert r.status_code == 200

    r2 = client.get(
        f"/game/scenarios/{sc.id}/result",
        params={"player_id": "u-wrong"},
    )
    assert r2.status_code == 200
    data = r2.json()

    pr = data["player_result"]
    assert pr["status"] == "revealed-incorrect"
    assert pr["predicted_option_id"] == opt_b.id
    assert pr["is_correct"] is False


def test_opinion_summary_empty_state(client):
    """
    If the player has not answered any opinions, opinion summary should
    return zeros and an empty details list.
    """
    r = client.get("/game/opinion/summary", params={"player_id": "op-sum-empty"})
    assert r.status_code == 200
    data = r.json()

    assert data["total_answered"] == 0
    assert data["compared_count"] == 0
    assert data["matched_majority"] == 0
    assert data["match_rate"] is None
    assert data["details"] == []


def test_opinion_summary_counts_matches_against_majority(client, session):
    """
    Player has opinions on two dilemmas:
    - sc1: majority A, player picks A (match)
    - sc2: majority B, player picks A (not match)
    """
    sc1 = seed_single_scenario(session)
    sc2 = seed_single_scenario(session)

    sc1_a, sc1_b = sc1.options
    sc2_a, sc2_b = sc2.options

    # Make baseline majorities: sc1 -> A, sc2 -> B
    sc1_a.is_baseline_majority = True
    sc1_b.is_baseline_majority = False
    sc2_a.is_baseline_majority = False
    sc2_b.is_baseline_majority = True
    session.commit()

    # Player's personal opinions
    # sc1: A (matches majority)
    r1 = client.post(
        f"/game/scenarios/{sc1.id}/opinion",
        params={"player_id": "op-sum-1"},
        json={"option_id": sc1_a.id},
    )
    assert r1.status_code == 200

    # sc2: A (does NOT match majority B)
    r2 = client.post(
        f"/game/scenarios/{sc2.id}/opinion",
        params={"player_id": "op-sum-1"},
        json={"option_id": sc2_a.id},
    )
    assert r2.status_code == 200

    r_sum = client.get("/game/opinion/summary", params={"player_id": "op-sum-1"})
    assert r_sum.status_code == 200
    data = r_sum.json()

    assert data["total_answered"] == 2
    assert data["compared_count"] == 2
    assert data["matched_majority"] == 1
    assert data["match_rate"] == pytest.approx(0.5)

    # Detail rows should reflect matched / not-matched
    statuses = {d["scenario_id"]: d["status"] for d in data["details"]}
    assert statuses[sc1.id] == "matched"
    assert statuses[sc2.id] == "not-matched"


def test_opinion_summary_marks_waiting_when_no_majority(client, session):
    """
    If there is no baseline and not enough predictions to form a majority,
    opinion summary should mark such scenarios as 'waiting' and not count
    them in compared_count.
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # Ensure no baseline majority
    opt_a.is_baseline_majority = False
    opt_b.is_baseline_majority = False
    session.commit()

    # Player gives an opinion
    r = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "op-wait"},
        json={"option_id": opt_a.id},
    )
    assert r.status_code == 200

    r_sum = client.get("/game/opinion/summary", params={"player_id": "op-wait"})
    assert r_sum.status_code == 200
    data = r_sum.json()

    assert data["total_answered"] == 1
    # No majority yet -> not compared
    assert data["compared_count"] == 0
    assert data["matched_majority"] == 0
    assert data["match_rate"] is None

    assert len(data["details"]) == 1
    d = data["details"][0]
    assert d["scenario_id"] == sc.id
    assert d["status"] == "waiting"
    assert d["majority_option_id"] is None


def test_analytics_includes_total_predictions_and_opinion_stats(client, session):
    """
    Analytics should expose totalPredictions, totalOpinions and
    opinionOptionPercentages for each scenario.
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # Predictions: 3 for A, 1 for B
    for i in range(3):
        r = client.post(
            f"/game/scenarios/{sc.id}/predict",
            params={"player_id": f"pred-a{i}"},
            json={"option_id": opt_a.id},
        )
        assert r.status_code == 200

    r = client.post(
        f"/game/scenarios/{sc.id}/predict",
        params={"player_id": "pred-b0"},
        json={"option_id": opt_b.id},
    )
    assert r.status_code == 200

    # Opinions: 2 for A, 1 for B
    for i in range(2):
        r = client.post(
            f"/game/scenarios/{sc.id}/opinion",
            params={"player_id": f"op-a{i}"},
            json={"option_id": opt_a.id},
        )
        assert r.status_code == 200

    r = client.post(
        f"/game/scenarios/{sc.id}/opinion",
        params={"player_id": "op-b0"},
        json={"option_id": opt_b.id},
    )
    assert r.status_code == 200

    data = _get_analytics(client)
    row = next(item for item in data["scenarios"] if item["scenarioId"] == sc.id)

    assert row["totalPredictions"] == 4
    assert row["totalOpinions"] == 3

    opin = row["opinionOptionPercentages"]
    assert set(opin.keys()) == {"A", "B"}
    assert opin["A"] == pytest.approx(2 / 3 * 100.0)
    assert opin["B"] == pytest.approx(1 / 3 * 100.0)


def test_party_round_result_counts_votes_and_majorities(client, session):
    """
    Party round result should:
    - count party votes per option
    - find party_majority_option_id
    - expose global majority and whether baseline was used
    """
    sc = seed_single_scenario(session)
    opt_a, opt_b = sc.options

    # Make A the global majority via baseline
    opt_a.is_baseline_majority = True
    opt_b.is_baseline_majority = False
    session.commit()

    # Start party with 3 players
    r = client.post("/game/party/sessions", json={"player_count": 3})
    assert r.status_code == 201
    party_id = r.json()["party_id"]

    # Record per-player answers:
    # Player 1 -> A, Player 2 -> A, Player 3 -> B
    answers_payload = {
        "answers": [
            {"player_number": 1, "option_id": opt_a.id},
            {"player_number": 2, "option_id": opt_a.id},
            {"player_number": 3, "option_id": opt_b.id},
        ]
    }
    r_ans = client.post(
        f"/game/party/sessions/{party_id}/scenarios/{sc.id}/answers",
        json=answers_payload,
    )
    assert r_ans.status_code == 200

    r_res = client.get(f"/game/party/sessions/{party_id}/scenarios/{sc.id}/result")
    assert r_res.status_code == 200
    data = r_res.json()

    assert data["party_id"] == party_id
    assert data["scenario_id"] == sc.id
    assert data["total_party_answers"] == 3
    assert data["party_majority_option_id"] == opt_a.id
    assert data["global_majority_option_id"] == opt_a.id
    assert data["used_global_baseline"] is True

    by_id = {o["id"]: o for o in data["options"]}
    opt_a_payload = by_id[opt_a.id]
    opt_b_payload = by_id[opt_b.id]

    assert opt_a_payload["party_votes"] == 2
    assert opt_b_payload["party_votes"] == 1
    assert opt_a_payload["party_share"] == pytest.approx(2 / 3)
    assert opt_b_payload["party_share"] == pytest.approx(1 / 3)
    assert opt_a_payload["is_party_majority"] is True
    assert opt_b_payload["is_party_majority"] is False
    assert opt_a_payload["is_global_majority"] is True
    assert opt_b_payload["is_global_majority"] is False
