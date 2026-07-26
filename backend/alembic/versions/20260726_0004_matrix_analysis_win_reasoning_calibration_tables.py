"""Add matrix_analysis, win_reasoning, calibration_history, weight_adjustments, notification_audit tables.

M2 (Matrix Analysis) of the prediction engine migration requires:
- matrix_analysis: per-match evidence from Stage 2 (injuries, form, H2H, odds, weather)
- win_reasoning: post-match narrative (Stage 4)
- calibration_history: nightly evaluation results (Stage 6)
- weight_adjustments: approved weight deltas for confidence framework
- notification_audit: idempotency for Discord/email notifications

Spec: ADR-008-schema-data-for-matrix-analysis-and-calibration.md

Revision ID: 20260726_0004
Revises: 20260721_0003
Create Date: 2026-07-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0004"
down_revision: Union[str, Sequence[str], None] = "20260721_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. matrix_analysis ─────────────────────────────────────────────────────
    op.create_table(
        "matrix_analysis",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        # Player/team condition
        sa.Column("home_injuries", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("away_injuries", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("home_suspensions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("away_suspensions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("lineup_notes", postgresql.JSONB(), nullable=False, server_default="[]"),
        # Form
        sa.Column("home_form_last5", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("away_form_last5", postgresql.JSONB(), nullable=False, server_default="[]"),
        # H2H
        sa.Column("h2h_results", postgresql.JSONB(), nullable=False, server_default="[]"),
        # Strategy/Tactics
        sa.Column("tactical_notes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("motivational", sa.Text(), nullable=True),
        # Contextual
        sa.Column("venue_weather", postgresql.JSONB(), nullable=True),
        sa.Column("schedule_fatigue", postgresql.JSONB(), nullable=True),
        # Market/Odds
        sa.Column("market_odds", postgresql.JSONB(), nullable=True),
        sa.Column("polymarket_data", postgresql.JSONB(), nullable=True),
        # Composite quality signal
        sa.Column("evidence_quality_score", sa.Integer(), nullable=True),
        sa.Column("sources_used", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("data_source_degraded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("research_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("match_id", name="uq_matrix_analysis_match_id"),
    )
    op.create_index("ix_matrix_analysis_match_id", "matrix_analysis", ["match_id"])
    op.create_index("ix_matrix_analysis_sport", "matrix_analysis", ["sport"])
    op.create_index("ix_matrix_analysis_data_source_degraded", "matrix_analysis", ["data_source_degraded"])
    # FK ke matches
    op.create_foreign_key("fk_matrix_analysis_match_id", "matrix_analysis", "matches", ["match_id"], ["match_id"], ondelete="CASCADE")

    # ── 2. win_reasoning ──────────────────────────────────────────────────────
    op.create_table(
        "win_reasoning",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("winner", sa.Text(), nullable=False),
        sa.Column("winning_factors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("losing_factors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("key_moment", sa.Text(), nullable=True),
        sa.Column("tactical_winner", sa.Text(), nullable=True),  # 'home'|'away'|'neutral'
        # For learning
        sa.Column("factors_missed_by_prediction", postgresql.JSONB(), server_default="[]"),
        sa.Column("pattern_tags", postgresql.ARRAY(sa.Text()), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("match_id", name="uq_win_reasoning_match_id"),
    )
    op.create_index("ix_win_reasoning_match_id", "win_reasoning", ["match_id"])
    op.create_index("ix_win_reasoning_pattern_tags", "win_reasoning", ["pattern_tags"], postgresql_using="gin")
    op.create_foreign_key("fk_win_reasoning_match_id", "win_reasoning", "matches", ["match_id"], ["match_id"], ondelete="CASCADE")

    # ── 3. calibration_history ────────────────────────────────────────────────
    op.create_table(
        "calibration_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("run_at_wib", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        # Bucket stats
        sa.Column("bucket", sa.Text(), nullable=False),  # 'HIGH'|'MEDIUM'|'LOW'|'COIN_FLIP'
        sa.Column("matches_in_bucket", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mean_confidence_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("actual_accuracy_pct", sa.Numeric(5, 2), nullable=True),
        # Calibration error
        sa.Column("calibration_error_pp", sa.Numeric(5, 2), nullable=True),
        sa.Column("direction", sa.Text(), nullable=True),  # 'over_confident'|'under_confident'
        sa.Column("needs_recalibration", sa.Boolean(), nullable=False, server_default="false"),
        # Suggested adjustment
        sa.Column("suggested_adjustment", postgresql.JSONB(), nullable=True),
        # Full distribution
        sa.Column("bucket_distribution", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_calibration_history_sport", "calibration_history", ["sport"])
    op.create_index("ix_calibration_history_run_at", "calibration_history", ["run_at_wib"])

    # ── 4. weight_adjustments ─────────────────────────────────────────────────
    op.create_table(
        "weight_adjustments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("factor", sa.Text(), nullable=False),  # 'form'|'h2h'|'player_condition'|etc.
        sa.Column("delta_weight", sa.Numeric(4, 3), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),  # 'increase'|'decrease'
        # Provenance
        sa.Column("triggered_by", sa.Text(), nullable=False),  # 'pattern_tag'|'calibration_suggestion'|'manual'
        sa.Column("trigger_detail", postgresql.JSONB(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Text(), nullable=True),  # 'system'|'user:{user_id}'
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'applied'")),  # 'applied'|'pending_approval'|'rejected'|'rolled_back'
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),  # NULL=permanent
        # Partial uniqueness is implemented as a PostgreSQL partial unique index below.
    )
    op.create_index("ix_weight_adjustments_sport", "weight_adjustments", ["sport"])
    op.create_index("ix_weight_adjustments_status", "weight_adjustments", ["status"])
    op.create_index(
        "uq_weight_adjustments_sport_factor_status",
        "weight_adjustments",
        ["sport", "factor"],
        unique=True,
        postgresql_where=sa.text("status = 'applied'"),
    )

    # ── 5. notification_audit ─────────────────────────────────────────────────
    op.create_table(
        "notification_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),  # 'discord'|'email'
        sa.Column("match_id", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),  # untuk email
        sa.Column("recipient", sa.Text(), nullable=True),  # channel ID atau email address
        sa.Column("status", sa.Text(), nullable=False),  # 'sent'|'deduped'|'failed'
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        # Debugging
        sa.Column("payload_hash", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_audit_idempotency_key"),
    )
    op.create_index("ix_notification_audit_match_id", "notification_audit", ["match_id"])
    op.create_index("ix_notification_audit_idempotency", "notification_audit", ["idempotency_key"])


def downgrade() -> None:
    # Drop in reverse FK dependency order (notification_audit has no FK, drop first)
    op.drop_table("notification_audit")
    op.drop_table("weight_adjustments")
    op.drop_table("calibration_history")
    op.drop_table("win_reasoning")
    op.drop_table("matrix_analysis")
