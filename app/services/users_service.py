from pymongo.database import Database

from app.db.users_repo import list_active_users
from app.models.users import UserSummary


def get_active_users(database: Database) -> list[UserSummary]:
    users = list_active_users(database)
    return [
        UserSummary(
            id=str(user['_id']),
            username=user['username'],
            displayName=user.get('displayName', user['username']),
            role=user.get('role', 'viewer'),
            active=user.get('active', True),
        )
        for user in users
    ]