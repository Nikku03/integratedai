"""Messages for work requests between agents and questions to the head: work_request, work_decision, question,
answer.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-29
"""

from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None

KINDS = ("work_request", "work_decision", "question", "answer")


def upgrade() -> None:
    with op.get_context().autocommit_block():  # a new enum value cannot be added inside a transaction that uses it
        for k in KINDS:
            op.execute(f"ALTER TYPE message_kind ADD VALUE IF NOT EXISTS '{k}'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value; messages of these kinds are removed so older code can read the table
    op.execute("DELETE FROM agent_messages WHERE kind::text IN ('work_request', 'work_decision', 'question', 'answer')")
