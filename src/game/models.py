from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

# IMPORTANT: reuse the same Base as the rest of the user_service
from user_service.v1.models.user import Base as GameBase


class Scenario(GameBase):
    """
    Core dilemma / scenario shown in:
    - Main prediction mode (Feature 1)
    - Personal Opinion / Personality mode (Feature 5)
    - Party mode (Feature 7)
    """

    __tablename__ = "game_scenarios"

    id = Column(Integer, primary_key=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    text = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    options = relationship(
        "ScenarioOption",
        back_populates="scenario",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    # Prediction-mode answers: “what do you think MOST people chose?”
    predictions = relationship(
        "ScenarioPrediction",
        back_populates="scenario",
        cascade="all, delete-orphan",
    )

    # Feature 5: personal opinion answers: “what would YOU do?”
    opinions = relationship(
        "ScenarioOpinion",
        back_populates="scenario",
        cascade="all, delete-orphan",
    )

    # Feature 7 (Party Mode): per-party-player answers
    party_answers = relationship(
        "PartyAnswer",
        back_populates="scenario",
        cascade="all, delete-orphan",
    )


class ScenarioOption(GameBase):
    """
    One of the possible choices for a scenario, e.g. "A", "B", "C".
    Shared between prediction mode, opinion mode, and party mode.
    """

    __tablename__ = "game_scenario_options"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(
        Integer,
        ForeignKey("game_scenarios.id"),
        nullable=False,
        index=True,
    )
    key = Column(String(1), nullable=False)  # "A", "B", "C", ...
    text = Column(String, nullable=False)

    # Baseline majority flag (for early players in prediction mode)
    is_baseline_majority = Column(Boolean, nullable=False, default=False)

    scenario = relationship("Scenario", back_populates="options")

    # Prediction-mode answers pointing at this option
    predictions = relationship("ScenarioPrediction", back_populates="option")

    # Feature 5: opinion-mode answers pointing at this option
    opinions = relationship("ScenarioOpinion", back_populates="option")

    # Feature 7: party-mode answers pointing at this option
    party_answers = relationship("PartyAnswer", back_populates="option")

    __table_args__ = (
        # Only one option with a given key per scenario
        UniqueConstraint(
            "scenario_id",
            "key",
            name="uq_game_option_scenario_key",
        ),
    )


class ScenarioPrediction(GameBase):
    """
    A single prediction-mode answer:
    - player is guessing which option is the *majority*.
    """

    __tablename__ = "game_scenario_predictions"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(
        Integer,
        ForeignKey("game_scenarios.id"),
        nullable=False,
        index=True,
    )
    option_id = Column(
        Integer,
        ForeignKey("game_scenario_options.id"),
        nullable=False,
        index=True,
    )
    player_id = Column(String, nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scenario = relationship("Scenario", back_populates="predictions")
    option = relationship("ScenarioOption", back_populates="predictions")

    __table_args__ = (
        # One prediction per (player, scenario)
        UniqueConstraint(
            "scenario_id",
            "player_id",
            name="uq_game_prediction_player_scenario",
        ),
    )


class ScenarioOpinion(GameBase):
    """
    Feature 5: Personal Opinion Mode – "What would YOU do?"

    Stores personal answers separate from prediction-mode answers.
    """

    __tablename__ = "game_scenario_opinions"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(
        Integer,
        ForeignKey("game_scenarios.id"),
        nullable=False,
        index=True,
    )
    option_id = Column(
        Integer,
        ForeignKey("game_scenario_options.id"),
        nullable=False,
        index=True,
    )
    # Same "player_id" concept as predictions (can be anon/session/user id)
    player_id = Column(String, nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scenario = relationship("Scenario", back_populates="opinions")
    option = relationship("ScenarioOption", back_populates="opinions")

    __table_args__ = (
        # One personal opinion per (player, scenario)
        UniqueConstraint(
            "scenario_id",
            "player_id",
            name="uq_game_opinion_player_scenario",
        ),
    )


class GameSession(GameBase):
    """
    Feature 4: Game sessions for analytics (median session length, etc.)

    Each row represents a contiguous play session for a given player_id.
    """

    __tablename__ = "game_sessions"

    id = Column(Integer, primary_key=True)

    # Reuse the same player_id concept as predictions/opinions
    player_id = Column(String, nullable=False, index=True)

    # When the session started
    started_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # When the session ended (null while it's still "open")
    ended_at = Column(DateTime(timezone=True), nullable=True, index=True)


class PartyAnswer(GameBase):
    """
    Feature 7: Party Mode: per-player answers within a local party session.

    Each row = how a single party player answered a specific scenario.
    """

    __tablename__ = "game_party_answers"

    id = Column(Integer, primary_key=True)

    # Local party session id (matches the party_id from the API)
    party_id = Column(String, nullable=False, index=True)

    # Local player number within that party: 1..N
    party_player_number = Column(Integer, nullable=False)

    scenario_id = Column(
        Integer,
        ForeignKey("game_scenarios.id"),
        nullable=False,
        index=True,
    )
    option_id = Column(
        Integer,
        ForeignKey("game_scenario_options.id"),
        nullable=False,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scenario = relationship("Scenario", back_populates="party_answers")
    option = relationship("ScenarioOption", back_populates="party_answers")

    __table_args__ = (
        # One answer per (party, player_number, scenario)
        UniqueConstraint(
            "party_id",
            "party_player_number",
            "scenario_id",
            name="uq_game_party_answer_party_player_scenario",
        ),
    )
