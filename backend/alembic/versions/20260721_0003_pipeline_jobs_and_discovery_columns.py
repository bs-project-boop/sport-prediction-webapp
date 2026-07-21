"""Add pipeline_jobs table and discovery-stage columns to matches/predictions.

Stage 1 (Discovery) of the prediction engine migration requires:
- pipeline_jobs: register relative-trigger jobs (Stage 2 T-2h) during discovery
- matches.competition_level: tier classification (senior/junior) from ADR-008
- matches.report_label: display label for special matches (e.g., "[JUNIOR - NO PREDICTION]")
- matches.source_metadata.pipeline_source: track which discovery source found this match

Revision ID: 20260721_0003
Revises: 20260720_0002
Create Date: 2026-07-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260721_0003"
down_revision: Union[str, Sequence[str], None] = "20260720_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── pipeline_jobs ──────────────────────────────────────────────────────────
    op.create_table(
        "pipeline_jobs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text(), nullable=True),
        sa.Column("scheduled_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_id", name="uq_pipeline_jobs_job_id"),
    )
    op.create_index(
        "ix_pipeline_jobs_pending",
        "pipeline_jobs",
        ["status", "scheduled_time"],
    )
    op.create_index("ix_pipeline_jobs_match_id", "pipeline_jobs", ["match_id"])
    op.create_index("ix_pipeline_jobs_status", "pipeline_jobs", ["status"])

    # ── matches: stage-1 columns ───────────────────────────────────────────────
    op.add_column(
        "matches",
        sa.Column("competition_level", sa.Text(), nullable=False, server_default="senior"),
    )
    op.add_column(
        "matches",
        sa.Column("report_label", sa.Text(), nullable=True),
    )
    # source_metadata extension — not a separate column, just document the intent:
    # pipeline source will be stored in source_metadata JSONB as {..., "pipeline_source": "espn"|"motogp"|...}

    # ── predictions: pipeline_stage ────────────────────────────────────────────
    op.add_column(
        "predictions",
        sa.Column("pipeline_stage", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("predictions", "pipeline_stage")
    op.drop_column("matches", "report_label")
    op.drop_column("matches", "competition_level")
    op.drop_index("ix_pipeline_jobs_status", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_match_id", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_pending", table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")
