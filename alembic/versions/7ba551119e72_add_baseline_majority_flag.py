"""add baseline majority flag

Revision ID: 7ba551119e72
Revises: 170d538bdaec
Create Date: 2025-xx-xx xx:xx:xx.xxx
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7ba551119e72"
down_revision = "170d538bdaec"  # game_scenario_tables migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_scenario_options",
        sa.Column(
            "is_baseline_majority",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Optional: drop server default afterwards
    op.alter_column(
        "game_scenario_options",
        "is_baseline_majority",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("game_scenario_options", "is_baseline_majority")
