from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"


def upgrade():
    op.add_column("users", sa.Column("email", sa.String()))


def downgrade():
    op.drop_column("users", "email")

