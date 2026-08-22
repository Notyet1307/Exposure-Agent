from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from app.domain.model_qualification import (
    QualificationEvaluation,
    current_model_is_qualified,
    persist_qualification_result,
)
from app.domain.models import ModelQualificationResult


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ModelQualificationResult.__table__.create(engine)  # type: ignore[attr-defined]
    return Session(engine)


def test_backend_admits_only_a_pass_for_the_current_binding() -> None:
    session = _session()
    evaluation = QualificationEvaluation(
        fixture_version="model-qualification-v1",
        status="PASS",
        availability_numerator=3,
        availability_denominator=4,
        traceable_citations=4,
        total_citations=4,
        hallucination_count=0,
        finding_modification_count=0,
        unauthorized_side_effect_count=0,
        failure_code=None,
    )
    persist_qualification_result(
        session=session,
        endpoint="http://model.internal/v1",
        model_identity="customer-model",
        config_fingerprint="a" * 64,
        agent_compose_run_id="b" * 64,
        evaluation=evaluation,
    )

    assert current_model_is_qualified(
        session=session,
        endpoint="http://model.internal/v1",
        model_identity="customer-model",
        config_fingerprint="a" * 64,
    )
    for changed in (
        {"endpoint": "http://replacement.internal/v1"},
        {"model_identity": "replacement-model"},
        {"config_fingerprint": "c" * 64},
    ):
        binding = {
            "endpoint": "http://model.internal/v1",
            "model_identity": "customer-model",
            "config_fingerprint": "a" * 64,
        }
        binding.update(changed)
        assert not current_model_is_qualified(session=session, **binding)

    persist_qualification_result(
        session=session,
        endpoint="http://model.internal/v1",
        model_identity="customer-model",
        config_fingerprint="a" * 64,
        agent_compose_run_id="c" * 64,
        evaluation=QualificationEvaluation(
            fixture_version="model-qualification-v1",
            status="FAIL",
            availability_numerator=2,
            availability_denominator=4,
            traceable_citations=4,
            total_citations=4,
            hallucination_count=0,
            finding_modification_count=0,
            unauthorized_side_effect_count=0,
            failure_code="availability_below_threshold",
        ),
    )
    assert not current_model_is_qualified(
        session=session,
        endpoint="http://model.internal/v1",
        model_identity="customer-model",
        config_fingerprint="a" * 64,
    )


def test_missing_or_failed_result_is_not_admitted() -> None:
    session = _session()
    binding = {
        "endpoint": "http://model.internal/v1",
        "model_identity": "customer-model",
        "config_fingerprint": "a" * 64,
    }
    assert not current_model_is_qualified(session=session, **binding)

    persist_qualification_result(
        session=session,
        **binding,
        agent_compose_run_id="b" * 64,
        evaluation=QualificationEvaluation(
            fixture_version="model-qualification-v1",
            status="FAIL",
            availability_numerator=2,
            availability_denominator=4,
            traceable_citations=4,
            total_citations=4,
            hallucination_count=0,
            finding_modification_count=0,
            unauthorized_side_effect_count=0,
            failure_code="availability_below_threshold",
        ),
    )

    assert not current_model_is_qualified(session=session, **binding)
    stored = session.exec(select(ModelQualificationResult)).one()
    assert stored.failure_code == "availability_below_threshold"
    assert not hasattr(stored, "secret")
    assert not hasattr(stored, "prompt")
    assert not hasattr(stored, "provider_events")
