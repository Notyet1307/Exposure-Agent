from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlmodel import Session


@contextmanager
def reject_audit_inserts(db: Session) -> Iterator[None]:
    db.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION fail_test_audit_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'test audit failure';
            END;
            $$
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TRIGGER fail_test_audit_insert
            BEFORE INSERT ON audit_events
            FOR EACH ROW EXECUTE FUNCTION fail_test_audit_insert()
            """
        )
    )
    db.commit()
    try:
        yield
    finally:
        db.rollback()
        db.execute(
            text("DROP TRIGGER IF EXISTS fail_test_audit_insert ON audit_events")
        )
        db.execute(text("DROP FUNCTION IF EXISTS fail_test_audit_insert()"))
        db.commit()


@contextmanager
def reject_publish_audit_inserts(db: Session) -> Iterator[None]:
    """Reject only governance_run.published audit inserts, leaving other events visible."""
    db.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION fail_test_publish_audit_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.action = 'governance_run.published' THEN
                    RAISE EXCEPTION 'test publish audit failure';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TRIGGER fail_test_publish_audit_insert
            BEFORE INSERT ON audit_events
            FOR EACH ROW EXECUTE FUNCTION fail_test_publish_audit_insert()
            """
        )
    )
    db.commit()
    try:
        yield
    finally:
        db.rollback()
        db.execute(
            text(
                "DROP TRIGGER IF EXISTS fail_test_publish_audit_insert "
                "ON audit_events"
            )
        )
        db.execute(
            text("DROP FUNCTION IF EXISTS fail_test_publish_audit_insert()")
        )
        db.commit()
