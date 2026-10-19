from pymongo.database import Database


def list_active_users(database: Database) -> list[dict]:
    return list(
        database['users'].find(
            {'active': True},
            {'username': 1, 'displayName': 1, 'role': 1, 'active': 1},
        )
    )