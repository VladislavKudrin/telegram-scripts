import asyncio
import csv
import os
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import (
    ChannelParticipantsSearch,
    InputChannel,
    User,
)

# Load .env file if present
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))

API_ID = int(os.environ.get("API_ID", "") or 0)
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
CSV_PATH = os.environ.get("CSV_PATH", "migration.csv")
USERNAMES_RAW = os.environ.get("USERNAMES_RAW", "") or os.environ.get("USERNAMES", "")

if not API_ID or not API_HASH:
    print("Error: API_ID and API_HASH are required (set in .env or environment).")
    sys.exit(1)

if not USERNAMES_RAW:
    print("Error: USERNAMES_RAW (or USERNAMES) is required — comma-separated list, e.g. alice,bob,carol")
    sys.exit(1)

ALLOWED = {u.strip().lower().lstrip("@") for u in USERNAMES_RAW.split(",") if u.strip()}


def load_rows() -> list[dict]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


async def get_all_participants(client: TelegramClient, channel) -> list[User]:
    """Fetch all participants with pagination."""
    all_users: list[User] = []
    offset = 0
    limit = 200

    while True:
        result = await client(
            GetParticipantsRequest(
                channel=channel,
                filter=ChannelParticipantsSearch(""),
                offset=offset,
                limit=limit,
                hash=0,
            )
        )
        users = [u for u in result.users if isinstance(u, User)]
        all_users.extend(users)
        if len(result.participants) < limit:
            break
        offset += len(result.participants)

    return all_users


async def main():
    rows = load_rows()
    to_check = [r for r in rows if r.get("New Chat ID", "").strip()]

    print(f"Checking {len(to_check)} channel(s)...")
    print(f"Allowed users: {', '.join('@' + u for u in sorted(ALLOWED))}")
    print("Note: bots are ignored. Members without a username → group is NOT empty.\n")

    session = StringSession(SESSION_STRING)
    client = TelegramClient(session, API_ID, API_HASH)

    await client.start()

    saved = client.session.save()
    if not SESSION_STRING:
        print("Save this session string to .env to skip login next time:")
        print(f'SESSION_STRING="{saved}"\n')

    print("Fetching dialogs to cache access hashes...")
    await client.get_dialogs(limit=None)
    print("Done.\n")

    empty_groups: list[dict] = []

    for row in to_check:
        name = row["Channel Name"].strip()
        new_chat_id = row["New Chat ID"].strip()

        try:
            entity = await client.get_entity(int(f"-100{new_chat_id}"))
            users = await get_all_participants(client, entity)

            humans = [u for u in users if not u.bot]
            no_username = [u for u in humans if not u.username]
            with_username = [u for u in humans if u.username]
            non_allowed = [u for u in with_username if u.username.lower() not in ALLOWED]

            if no_username:
                print(
                    f"  [HAS MEMBERS] {name} — "
                    f"{len(no_username)} member(s) without username (cannot verify)"
                )
            elif non_allowed:
                names = ", ".join(f"@{u.username}" for u in non_allowed)
                print(f"  [HAS MEMBERS] {name} — {len(non_allowed)} non-allowed: {names}")
            elif not with_username:
                print(f"  [SKIP] {name} — no human members found")
            else:
                members_str = ", ".join(f"@{u.username}" for u in with_username)
                print(f"  [EMPTY] {name} — {len(with_username)} member(s): {members_str}")
                empty_groups.append({"Channel Name": name, "New Chat ID": new_chat_id})

        except Exception as e:
            print(f"  [ERROR] {name} (id={new_chat_id}): {e}")

    await client.disconnect()

    with open("empty.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Channel Name", "New Chat ID"])
        writer.writeheader()
        writer.writerows(empty_groups)

    print(f"\nDone. {len(empty_groups)} empty group(s) written to empty.csv.")


asyncio.run(main())
