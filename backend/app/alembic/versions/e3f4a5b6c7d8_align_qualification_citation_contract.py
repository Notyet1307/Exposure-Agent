"""Align the qualification citation verdict with the quality gate.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-23 00:00:00.000000

"""

from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_model_qualification_results_verdict",
        "model_qualification_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_model_qualification_results_verdict",
        "model_qualification_results",
        "(status = 'PASS' AND availability_numerator * 4 >= "
        "availability_denominator * 3 AND total_citations > 0 AND "
        "traceable_citations = total_citations AND hallucination_count = 0 "
        "AND finding_modification_count = 0 AND "
        "unauthorized_side_effect_count = 0 AND failure_code IS NULL) OR "
        "(status = 'FAIL' AND failure_code IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_qualification_results_verdict",
        "model_qualification_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_model_qualification_results_verdict",
        "model_qualification_results",
        "(status = 'PASS' AND availability_numerator * 4 >= "
        "availability_denominator * 3 AND total_citations >= "
        "availability_numerator AND traceable_citations = total_citations "
        "AND hallucination_count = 0 AND finding_modification_count = 0 "
        "AND unauthorized_side_effect_count = 0 AND failure_code IS NULL) OR "
        "(status = 'FAIL' AND failure_code IS NOT NULL)",
    )
