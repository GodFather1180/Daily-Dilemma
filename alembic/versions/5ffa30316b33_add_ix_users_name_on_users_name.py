# alembic revision: 5ffa30316

# revision identifiers, used by Alembic.
revision = "5ffa30316b33"
down_revision = "3e588a47adb0"
branch_labels = None
depends_on = None


def upgrade():
    # No-op: ix_users_name is created in 3e588a47adb0
    pass


def downgrade():
    # No-op to mirror upgrade
    pass
