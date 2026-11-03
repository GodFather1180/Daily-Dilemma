# alembic revision: 3e588a47adb0
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3e588a47adb0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("avatar_path", sa.String(), nullable=True),
    )
    # Explicit, named UNIQUE index (tests assert this exact name exists)
    op.create_index("ix_users_name", "users", ["name"], unique=True)
    # Unique email (nullable)
    op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade():
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_index("ix_users_name", table_name="users")
    op.drop_table("users")
