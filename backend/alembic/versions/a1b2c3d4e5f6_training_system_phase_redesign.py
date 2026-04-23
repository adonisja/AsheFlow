"""training_system_phase_redesign

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-04-22 00:00:00.000000

Implements ADR-046: phase-based training curriculum redesign.

Changes:
  - training_curriculums: add category, record_type
  - training_records: add submitted_at, phase_closed, phase_closed_at,
                       passed, score, observation_notes, extended
  - training_tasks: add record_type, completed_late, completed_late_at
  - New table: trainer_coverage
  - New table: trainer_marks
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # training_curriculums — add category and record_type
    # ------------------------------------------------------------------
    op.add_column('training_curriculums',
        sa.Column('category', sa.String(50), nullable=True)
    )
    op.add_column('training_curriculums',
        sa.Column('record_type', sa.String(20), nullable=False, server_default='coverage')
    )

    # ------------------------------------------------------------------
    # training_records — add phase tracking and Phase 4 outcome fields
    # ------------------------------------------------------------------
    op.add_column('training_records',
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('training_records',
        sa.Column('phase_closed', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column('training_records',
        sa.Column('phase_closed_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('training_records',
        sa.Column('passed', sa.Boolean(), nullable=True)
    )
    op.add_column('training_records',
        sa.Column('score', sa.Float(), nullable=True)
    )
    op.add_column('training_records',
        sa.Column('observation_notes', sa.Text(), nullable=True)
    )
    op.add_column('training_records',
        sa.Column('extended', sa.Boolean(), nullable=False, server_default='false')
    )

    # ------------------------------------------------------------------
    # training_tasks — add record_type and late completion tracking
    # ------------------------------------------------------------------
    op.add_column('training_tasks',
        sa.Column('record_type', sa.String(20), nullable=False, server_default='coverage')
    )
    op.add_column('training_tasks',
        sa.Column('completed_late', sa.Boolean(), nullable=False, server_default='false')
    )
    op.add_column('training_tasks',
        sa.Column('completed_late_at', sa.DateTime(timezone=True), nullable=True)
    )

    # ------------------------------------------------------------------
    # New table: trainer_coverage
    # Topic-level log of which trainer covered which topic.
    # Enables mid-shift handoff tracing and trainer accountability audits.
    # ------------------------------------------------------------------
    op.create_table(
        'trainer_coverage',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('training_record_id', sa.UUID(), nullable=False),
        sa.Column('trainer_id', sa.UUID(), nullable=False),
        sa.Column('curriculum_item_id', sa.UUID(), nullable=True),
        sa.Column('topic_title', sa.String(255), nullable=False),
        sa.Column('covered_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['training_record_id'], ['training_records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainer_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['curriculum_item_id'], ['training_curriculums.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_trainer_coverage_training_record_id'),
                    'trainer_coverage', ['training_record_id'], unique=False)
    op.create_index(op.f('ix_trainer_coverage_trainer_id'),
                    'trainer_coverage', ['trainer_id'], unique=False)

    # ------------------------------------------------------------------
    # New table: trainer_marks
    # Performance accountability record per trainer per failed phase closure.
    # Only issued when trainer had no inherited debt (ADR-046 §3).
    # ------------------------------------------------------------------
    op.create_table(
        'trainer_marks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('trainer_id', sa.UUID(), nullable=False),
        sa.Column('training_record_id', sa.UUID(), nullable=False),
        sa.Column('trainee_id', sa.UUID(), nullable=False),
        sa.Column('reason', sa.String(50), nullable=False),
        sa.Column('debt_originated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('debt_chain_context', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['trainer_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['training_record_id'], ['training_records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_trainer_marks_trainer_id'),
                    'trainer_marks', ['trainer_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trainer_marks_trainer_id'), table_name='trainer_marks')
    op.drop_table('trainer_marks')

    op.drop_index(op.f('ix_trainer_coverage_trainer_id'), table_name='trainer_coverage')
    op.drop_index(op.f('ix_trainer_coverage_training_record_id'), table_name='trainer_coverage')
    op.drop_table('trainer_coverage')

    op.drop_column('training_tasks', 'completed_late_at')
    op.drop_column('training_tasks', 'completed_late')
    op.drop_column('training_tasks', 'record_type')

    op.drop_column('training_records', 'extended')
    op.drop_column('training_records', 'observation_notes')
    op.drop_column('training_records', 'score')
    op.drop_column('training_records', 'passed')
    op.drop_column('training_records', 'phase_closed_at')
    op.drop_column('training_records', 'phase_closed')
    op.drop_column('training_records', 'submitted_at')

    op.drop_column('training_curriculums', 'record_type')
    op.drop_column('training_curriculums', 'category')
