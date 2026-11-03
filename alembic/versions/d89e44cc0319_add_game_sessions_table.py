"""add_game_sessions_table

Revision ID: d89e44cc0319
Revises: 5ee7c44da1e2
Create Date: 2025-11-28 20:37:22.906792

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d89e44cc0319"
down_revision: Union[str, Sequence[str], None] = "5ee7c44da1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "game_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.String(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_game_sessions_player_id", "game_sessions", ["player_id"])
    op.create_index("ix_game_sessions_started_at", "game_sessions", ["started_at"])
    op.create_index("ix_game_sessions_ended_at", "game_sessions", ["ended_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_game_sessions_ended_at", table_name="game_sessions")
    op.drop_index("ix_game_sessions_started_at", table_name="game_sessions")
    op.drop_index("ix_game_sessions_player_id", table_name="game_sessions")
    op.drop_table("game_sessions")
