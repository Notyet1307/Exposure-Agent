from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.core.security import get_password_hash
from app.domain.models import AuditEvent
from app.models import User, UserUpdate, UserUpdateByAdmin


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
    was_active = db_user.is_active
    apply_user_update(db_user=db_user, user_in=user_in)
    session.add(db_user)

    try:
        session.flush()
        if db_user.is_active != was_active:
            session.add(
                AuditEvent(
                    actor_subject=actor_subject,
                    actor_type="user",
                    action=(
                        "user.reactivated" if db_user.is_active else "user.deactivated"
                    ),
                    target_type="user",
                    target_id=db_user.id,
                    before_data={"is_active": was_active},
                    after_data={"is_active": db_user.is_active},
                    ip_address=ip_address,
                )
            )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise

    session.refresh(db_user)
    return db_user
