from alembic import op
import sqlalchemy as sa

revision = "cae093ae686d"
down_revision = "5ffa30316b33"
branch_labels = None
depends_on = None


def upgrade():
    # 1) create new table WITHOUT conflicting index names
    op.create_table(
        "users_new",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("avatar_path", sa.String(), nullable=True),
    )

    # 2) copy legacy rows
    op.execute("""
        INSERT INTO users_new (name, email, password_hash, avatar_path)
        SELECT name, NULL, NULL, NULL FROM users
    """)

    # 3) drop old table; this also drops its ix_users_name index
    op.drop_table("users")

    # 4) rename new -> users
    op.rename_table("users_new", "users")

    # 5) NOW create the named unique index and unique constraint
    op.create_index("ix_users_name", "users", ["name"], unique=True)
    op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade():
    # revert to legacy schema (name-only PK)
    op.create_table(
        "users_old",
        sa.Column("name", sa.String(), primary_key=True, nullable=False),
    )
    op.execute("INSERT INTO users_old (name) SELECT name FROM users")

    # drop new constraints/indexes first
    with op.batch_alter_table("users") as b:
        b.drop_constraint("uq_users_email", type_="unique")
    op.drop_index("ix_users_name", table_name="users")

    op.drop_table("users")
    op.rename_table("users_old", "users")
