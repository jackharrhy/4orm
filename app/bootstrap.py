"""Create an initial user + invite for local development.

Usage:
  python -m app.bootstrap --username jack --password secret
"""

import argparse

from sqlalchemy import insert

from app.db import engine
from app.queries.users import create_invite
from app.schema import create_all, inventory_cards, users
from app.security import hash_password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    create_all(engine)
    with engine.begin() as conn:
        existing = (
            conn.execute(users.select().where(users.c.username == args.username))
            .mappings()
            .first()
        )
        if existing:
            user_id = existing["id"]
        else:
            result = conn.execute(
                insert(users).values(
                    username=args.username,
                    password_hash=hash_password(args.password),
                    display_name=args.username,
                )
            )
            user_id = result.inserted_primary_key[0]
            conn.execute(
                insert(inventory_cards).values(
                    user_id=user_id, headline=f"{args.username}'s card"
                )
            )

        invite = create_invite(conn, user_id, max_uses=1)
        print(f"Seed user id={user_id}")
        print(f"Invite code: {invite}")


if __name__ == "__main__":
    main()
