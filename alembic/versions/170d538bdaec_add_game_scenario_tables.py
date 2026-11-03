from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "170d538bdaec"
down_revision = "955862ba7c22"  # keep whatever was here if different
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "game_scenarios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "game_scenario_options",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "scenario_id",
            sa.Integer,
            sa.ForeignKey("game_scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=1), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
    )
    op.create_unique_constraint(
        "uq_game_scenario_option_key",
        "game_scenario_options",
        ["scenario_id", "key"],
    )

    op.create_table(
        "game_scenario_predictions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column(
            "scenario_id",
            sa.Integer,
            sa.ForeignKey("game_scenarios.id"),
            nullable=False,
        ),
        sa.Column(
            "option_id",
            sa.Integer,
            sa.ForeignKey("game_scenario_options.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_game_prediction_player_scenario",
        "game_scenario_predictions",
        ["player_id", "scenario_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_game_prediction_player_scenario",
        "game_scenario_predictions",
        type_="unique",
    )
    op.drop_table("game_scenario_predictions")

    op.drop_constraint(
        "uq_game_scenario_option_key",
        "game_scenario_options",
        type_="unique",
    )
    op.drop_table("game_scenario_options")

    op.drop_table("game_scenarios")
