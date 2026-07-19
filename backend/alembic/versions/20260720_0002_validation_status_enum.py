"""Use the v3 validation status enum and three-category accuracy view.

Revision ID: 20260720_0002
Revises: 20260719_0001
Create Date: 2026-07-20

The v3 daily state contract stores validation as a top-level string. The
source value ``SEBAGIAN BENAR`` is represented as ``SEBAGIAN_BENAR`` in the
PostgreSQL enum because enum labels use SQL-safe underscore values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260720_0002"
down_revision: Union[str, Sequence[str], None] = "20260719_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENUM_VALUES = "'BENAR', 'SEBAGIAN_BENAR', 'SALAH', 'NO_PICK', 'NO_PREDICTION'"


def _create_view() -> None:
    op.execute(
        """
        CREATE VIEW accuracy_metrics AS
        SELECT
            m.sport,
            DATE(m.kickoff_wib) AS match_date,
            COUNT(*) FILTER (
                WHERE pr.validation_status IN ('BENAR', 'SEBAGIAN_BENAR', 'SALAH')
            ) AS evaluated_count,
            COUNT(*) FILTER (WHERE pr.validation_status = 'BENAR') AS correct_count,
            COUNT(*) FILTER (
                WHERE pr.validation_status = 'SEBAGIAN_BENAR'
            ) AS partial_count,
            COUNT(*) FILTER (WHERE pr.validation_status = 'SALAH') AS incorrect_count,
            COUNT(*) FILTER (
                WHERE pr.validation_status IN ('NO_PICK', 'NO_PREDICTION')
            ) AS excluded_count,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE pr.validation_status = 'BENAR')
                / NULLIF(
                    COUNT(*) FILTER (
                        WHERE pr.validation_status IN ('BENAR', 'SEBAGIAN_BENAR', 'SALAH')
                    ), 0
                ),
                2
            ) AS strict_accuracy_percent,
            ROUND(
                100.0 * COUNT(*) FILTER (
                    WHERE pr.validation_status IN ('BENAR', 'SEBAGIAN_BENAR')
                )
                / NULLIF(
                    COUNT(*) FILTER (
                        WHERE pr.validation_status IN ('BENAR', 'SEBAGIAN_BENAR', 'SALAH')
                    ), 0
                ),
                2
            ) AS lenient_accuracy_percent
        FROM matches m
        JOIN prediction_results pr ON pr.match_id = m.match_id
        GROUP BY m.sport, DATE(m.kickoff_wib)
        """
    )


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS accuracy_metrics")
    op.execute(f"CREATE TYPE validation_status_enum AS ENUM ({_ENUM_VALUES})")
    op.execute(
        """
        ALTER TABLE prediction_results
        ALTER COLUMN validation_status TYPE validation_status_enum
        USING CASE validation_status
            WHEN 'SEBAGIAN BENAR' THEN 'SEBAGIAN_BENAR'::validation_status_enum
            WHEN 'BENAR' THEN 'BENAR'::validation_status_enum
            WHEN 'SALAH' THEN 'SALAH'::validation_status_enum
            WHEN 'NO_PICK' THEN 'NO_PICK'::validation_status_enum
            WHEN 'NO_PREDICTION' THEN 'NO_PREDICTION'::validation_status_enum
            ELSE NULL
        END
        """
    )
    op.drop_column("prediction_results", "outcome_correct")
    op.drop_column("prediction_results", "score_correct")
    _create_view()


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS accuracy_metrics")
    op.add_column("prediction_results", sa.Column("outcome_correct", sa.Boolean(), nullable=True))
    op.add_column("prediction_results", sa.Column("score_correct", sa.Boolean(), nullable=True))
    op.execute(
        """
        ALTER TABLE prediction_results
        ALTER COLUMN validation_status TYPE TEXT
        USING validation_status::text
        """
    )
    op.execute("DROP TYPE validation_status_enum")
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
