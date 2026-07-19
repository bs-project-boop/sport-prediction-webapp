"""Create initial Sport Prediction web-app projection schema.

Revision ID: 20260719_0001
Revises:
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260719_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "matches",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("date_wib", sa.Date(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("competition", sa.Text(), nullable=False, server_default=""),
        sa.Column("event_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("team_a", sa.Text(), nullable=True),
        sa.Column("team_b", sa.Text(), nullable=True),
        sa.Column("kickoff_wib", sa.DateTime(timezone=False), nullable=True),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="scheduled"),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_document", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("match_id", name="uq_matches_match_id"),
    )
    op.create_index("ix_matches_date_sport", "matches", ["date_wib", "sport"])
    op.create_index("ix_matches_kickoff", "matches", ["kickoff_wib"])

    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("predicted_outcome", sa.Text(), nullable=True),
        sa.Column("predicted_score_or_result", sa.Text(), nullable=True),
        sa.Column("confidence_percent", sa.Integer(), nullable=True),
        sa.Column("confidence_label", sa.Text(), nullable=True),
        sa.Column("confidence_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("confidence_model_version", sa.Text(), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("no_pick", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("no_pick_reason", sa.Text(), nullable=True),
        sa.Column("data_source_degraded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confidence_penalty_applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prediction_eligible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("accuracy_excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("validation_status", sa.Text(), nullable=True),
        sa.Column("reasoning", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("raw_document", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["match_id"], ["matches.match_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_record_id", name="uq_predictions_source_record_id"),
    )
    op.create_index("ix_predictions_match_id", "predictions", ["match_id"])
    op.create_index("ix_predictions_confidence", "predictions", ["confidence_percent"])

    op.create_table(
        "prediction_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("actual_result", sa.Text(), nullable=True),
        sa.Column("actual_winner", sa.Text(), nullable=True),
        sa.Column("actual_score", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.Text(), nullable=True),
        sa.Column("outcome_correct", sa.Boolean(), nullable=True),
        sa.Column("score_correct", sa.Boolean(), nullable=True),
        sa.Column("score_diff", sa.Numeric(), nullable=True),
        sa.Column("accuracy_excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw_document", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.match_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_record_id", name="uq_prediction_results_source_record_id"),
    )
    op.create_index("ix_prediction_results_match_id", "prediction_results", ["match_id"])
    op.create_index("ix_prediction_results_validation", "prediction_results", ["validation_status"])

    op.create_table(
        "ingestion_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=True),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_ingestion_audit_idempotency_key"),
    )
    op.create_index("ix_ingestion_audit_source_file", "ingestion_audit", ["source_file"])
    op.create_index("ix_ingestion_audit_status", "ingestion_audit", ["status"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("client_key", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_client_key", "auth_sessions", ["client_key"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.execute(
        """
        CREATE VIEW accuracy_metrics AS
        SELECT
            m.sport,
            m.date_wib,
            COUNT(*) FILTER (WHERE pr.outcome_correct IS NOT NULL AND NOT pr.accuracy_excluded) AS evaluated_count,
            COUNT(*) FILTER (WHERE pr.outcome_correct = TRUE AND NOT pr.accuracy_excluded) AS correct_count,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE pr.outcome_correct = TRUE AND NOT pr.accuracy_excluded)
                / NULLIF(COUNT(*) FILTER (WHERE pr.outcome_correct IS NOT NULL AND NOT pr.accuracy_excluded), 0), 2
            ) AS accuracy_percent
        FROM matches m
        LEFT JOIN prediction_results pr ON pr.match_id = m.match_id
        GROUP BY m.sport, m.date_wib
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS accuracy_metrics")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_client_key", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_ingestion_audit_status", table_name="ingestion_audit")
    op.drop_index("ix_ingestion_audit_source_file", table_name="ingestion_audit")
    op.drop_table("ingestion_audit")
    op.drop_index("ix_prediction_results_validation", table_name="prediction_results")
    op.drop_index("ix_prediction_results_match_id", table_name="prediction_results")
    op.drop_table("prediction_results")
    op.drop_index("ix_predictions_confidence", table_name="predictions")
    op.drop_index("ix_predictions_match_id", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("ix_matches_kickoff", table_name="matches")
    op.drop_index("ix_matches_date_sport", table_name="matches")
    op.drop_table("matches")
