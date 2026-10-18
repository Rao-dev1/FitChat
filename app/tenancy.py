"""Per-user data isolation, enforced in one place.

Every table that holds personal data inherits `UserOwned` (a `user_id` column). Two hooks on the database session do
the rest, so no individual query can forget to filter:

* every SELECT / bulk UPDATE / bulk DELETE on a user-owned table gets `WHERE user_id = <this session's user>`;
* every new row is stamped with the session's user, and a row for a different user is refused.

A session with no user matches nothing and cannot insert (it fails closed instead of leaking).
The session's user is `session.info["uid"]`, set by `open_session()` / the `get_db` dependency.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from .models import UserOwned

NO_USER = "!no-user!"  # not a valid user id (real ids are UUIDs or "local")
LOCAL_USER = "local"


def uid_of(db: Session) -> str:
    uid = db.info.get("uid")
    if not uid:
        raise RuntimeError("This database session has no user.")
    return uid


def key_get(db: Session, model, **key):
    """Fetch by primary key for tables whose key includes the user, e.g. key_get(db, DayStat, day=d)."""
    return db.get(model, {"user_id": uid_of(db), **key})


@event.listens_for(Session, "do_orm_execute")
def _scope_to_user(state) -> None:
    if state.is_column_load or state.is_relationship_load:
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    uid = state.session.info.get("uid") or NO_USER
    state.statement = state.statement.options(
        with_loader_criteria(UserOwned, lambda cls: cls.user_id == uid, include_aliases=True))


@event.listens_for(Session, "before_flush")
def _stamp_user(session: Session, _ctx, _instances) -> None:
    uid = session.info.get("uid")
    for obj in session.new:
        if not isinstance(obj, UserOwned):
            continue
        if not uid:
            raise RuntimeError("Refusing to save personal data without a user.")
        if not obj.user_id:
            obj.user_id = uid
        elif obj.user_id != uid:
            raise RuntimeError("Refusing to save a row that belongs to a different user.")
