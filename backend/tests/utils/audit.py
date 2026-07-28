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
