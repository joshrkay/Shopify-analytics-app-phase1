"""baseline_schema

Revision ID: cf2ab2db71d6
Revises: 
Create Date: 2026-02-16 16:13:50.215507

"""
from typing import Sequence, Union

from alembic import op

from src.db_base import Base
import src.models  # noqa: F401 - required to register all model metadata


# revision identifiers, used by Alembic.
revision: str = 'cf2ab2db71d6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
