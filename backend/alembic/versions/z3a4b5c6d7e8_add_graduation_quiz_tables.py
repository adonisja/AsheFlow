"""add graduation quiz tables

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-05-29

Three tables:

  graduation_quiz_templates — per-company question bank.
    Each company configures their own questions; the demo company is seeded via
    seed_graduation_quiz.py. MC questions carry correct_answer + choices (JSONB).
    Short-answer questions carry keywords (JSONB) for preliminary auto-scoring.

  graduation_quizzes — one row per trainee attempt.
    Created by management when they issue the quiz (status: issued).
    Trainee submits answers (status: submitted → under_review).
    Manager confirms pass/fail (status: passed | failed).
    weak_topics (JSONB) holds topic titles from failed mandatory questions so
    the next trainer can target those areas.

  graduation_quiz_responses — one row per question per attempt.
    auto_correct: set by scoring engine (null for non-auto-scoreable).
    manager_override: manager can flip auto_correct after review.
    override_note: optional note per question from the manager.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = 'z3a4b5c6d7e8'
down_revision = 'y2z3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'graduation_quiz_templates',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('question_text', sa.Text, nullable=False),
        sa.Column('question_type', sa.String(20), nullable=False),   # multiple_choice | short_answer
        sa.Column('choices', JSONB, nullable=True),                  # list[str] for MC
        sa.Column('correct_answer', sa.Text, nullable=True),         # exact MC answer string; null for short_answer
        sa.Column('is_mandatory', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('auto_scoreable', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('keywords', JSONB, nullable=True),                 # list[str] for short_answer preliminary scoring
        sa.Column('display_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table(
        'graduation_quizzes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('trainee_id', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('issued_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('training_record_id', UUID(as_uuid=True), sa.ForeignKey('training_records.id', ondelete='SET NULL'), nullable=True),
        sa.Column('attempt_number', sa.Integer, nullable=False, server_default='1'),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        # pending_issue: created, not yet sent to trainee
        # issued: trainee can see and submit
        # submitted: responses recorded, scoring in progress
        # under_review: scored, awaiting manager confirmation
        # passed: manager confirmed pass
        # failed: manager confirmed fail
        sa.Column('status', sa.String(20), nullable=False, server_default="'pending_issue'"),
        sa.Column('auto_score', sa.Float, nullable=True),
        sa.Column('final_score', sa.Float, nullable=True),
        sa.Column('passed', sa.Boolean, nullable=True),
        sa.Column('manager_reviewed_by', UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('manager_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('weak_topics', JSONB, nullable=True),             # list[str] topic titles for further training
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.text('now()')),
    )
    op.create_index('ix_graduation_quizzes_trainee_id', 'graduation_quizzes', ['trainee_id'])
    op.create_index('ix_graduation_quizzes_status', 'graduation_quizzes', ['status'])

    op.create_table(
        'graduation_quiz_responses',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('quiz_id', UUID(as_uuid=True), sa.ForeignKey('graduation_quizzes.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('question_id', UUID(as_uuid=True), sa.ForeignKey('graduation_quiz_templates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('answer_text', sa.Text, nullable=True),
        sa.Column('auto_correct', sa.Boolean, nullable=True),       # null = not auto-scored (short_answer)
        sa.Column('manager_override', sa.Boolean, nullable=True),   # manager flips after review
        sa.Column('override_note', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_graduation_quiz_responses_quiz_id', 'graduation_quiz_responses', ['quiz_id'])


def downgrade() -> None:
    op.drop_table('graduation_quiz_responses')
    op.drop_table('graduation_quizzes')
    op.drop_table('graduation_quiz_templates')
