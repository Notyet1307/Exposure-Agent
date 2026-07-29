from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.core.security import get_password_hash
from app.domain.models import AuditEvent
from app.models import User, UserCreateByAdmin, UserUpdate, UserUpdateByAdmin


def _user_audit_snapshot(user: User) -> dict[str, object]:
    return {
        "email": str(user.email),
        "full_name": user.full_name,
        "is_active": user.is_active,
    }


def create_user_by_admin(
    *,
    session: Session,
    user_in: UserCreateByAdmin,
    actor_subject: str,
    ip_address: str | None,
) -> User:
    user = User.model_validate(
        user_in, update={"hashed_password": get_password_hash(user_in.password)}
    )
    session.add(user)
    try:
        session.flush()
        session.add(
            AuditEvent(
                actor_subject=actor_subject,
                actor_type="user",
                action="user.created",
                target_type="user",
                target_id=user.id,
                before_data=None,
                after_data=_user_audit_snapshot(user),
                ip_address=ip_address,
            )
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise

    session.refresh(user)
    return user


def apply_user_update(
    *, db_user: User, user_in: UserUpdate | UserUpdateByAdmin
) -> None:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        extra_data["hashed_password"] = get_password_hash(user_data["password"])
    db_user.sqlmodel_update(user_data, update=extra_data)


def update_user_by_admin(
    *,
    session: Session,
    db_user: User,
    user_in: UserUpdateByAdmin,
    actor_subject: str,
    ip_address: str | None,
) -> User:
    before_data = _user_audit_snapshot(db_user)
    password_changed = "password" in user_in.model_fields_set
    apply_user_update(db_user=db_user, user_in=user_in)
    after_data = _user_audit_snapshot(db_user)
    if password_changed:
        before_data["password_changed"] = False
        after_data["password_changed"] = True
    has_changes = before_data != after_data
    session.add(db_user)

    try:
        session.flush()
        if has_changes:
            was_active = bool(before_data["is_active"])
            action = "user.updated"
            if db_user.is_active != was_active:
                action = "user.reactivated" if db_user.is_active else "user.deactivated"
            session.add(
                AuditEvent(
                    actor_subject=actor_subject,
                    actor_type="user",
                    action=action,
                    target_type="user",
                    target_id=db_user.id,
                    before_data=before_data,
                    after_data=after_data,
                    ip_address=ip_address,
                )
            )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise

    session.refresh(db_user)
    return db_user
