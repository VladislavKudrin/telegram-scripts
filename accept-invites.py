import asyncio
import csv
import os
import random
import re
import sys
from pathlib import Path

# Load .env file if present
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    InviteHashExpiredError,
    InviteRequestSentError,
    UserAlreadyParticipantError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.messages import ImportChatInviteRequest

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
CSV_PATH = os.environ.get("CSV_PATH", "migration.csv")
MIN_DELAY = int(os.environ.get("MIN_DELAY", "25"))   # seconds
MAX_DELAY = int(os.environ.get("MAX_DELAY", "40"))   # seconds
BREAK_EVERY = int(os.environ.get("BREAK_EVERY", "10"))
BREAK_DURATION = int(os.environ.get("BREAK_DURATION", "300"))  # seconds

if not API_ID or not API_HASH:
    print("Error: API_ID and API_HASH environment variables are required.")
    print("Get them from https://my.telegram.org")
    sys.exit(1)


def extract_invite_hash(link: str) -> str | None:
    m = re.search(r"t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)", link)
    return m.group(1) if m else None


def load_rows() -> list[dict]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


async def main():
    rows = load_rows()
    to_join = [r for r in rows if r.get("Invite Link", "").strip()]

    print(f"Found {len(to_join)} invite link(s) to accept.\n")
    if not to_join:
        print("Nothing to do.")
        return

    session = StringSession(SESSION_STRING)
    client = TelegramClient(session, API_ID, API_HASH)

    await client.start()

    saved = client.session.save()
    if not SESSION_STRING:
        print("\nSave this session string to skip login next time:")
        print(f'SESSION_STRING="{saved}"\n')

    success = 0
    failed = 0

    for row in to_join:
        link = row["Invite Link"].strip()
        name = row["Channel Name"].strip()
        invite_hash = extract_invite_hash(link)

        if not invite_hash:
            print(f"  [SKIP] Could not parse invite hash from: {link}")
            failed += 1
            continue

        joined = False
        while not joined:
            try:
                await client(ImportChatInviteRequest(invite_hash))
                print(f"  [OK] Joined: {name}")
                success += 1
                joined = True

            except FloodWaitError as e:
                extra = random.randint(10, 30)
                total = e.seconds + extra
                print(f"  [FLOOD] {name}: waiting {total}s ({e.seconds}s required + {extra}s buffer)...")
                await asyncio.sleep(total)

            except UserAlreadyParticipantError:
                print(f"  [SKIP] Already a member: {name}")
                success += 1
                joined = True

            except InviteHashExpiredError:
                print(f"  [EXPIRED] Invite link expired: {name}")
                failed += 1
                joined = True

            except InviteRequestSentError:
                print(f"  [PENDING] Join request sent (needs admin approval): {name}")
                success += 1
                joined = True

            except Exception as e:
                print(f"  [FAIL] {name}: {e}")
                failed += 1
                joined = True

        if success > 0 and success % BREAK_EVERY == 0:
            print(f"\n  [BREAK] {success} joins done — pausing {BREAK_DURATION}s to reset rate limits...\n")
            await asyncio.sleep(BREAK_DURATION)
        else:
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            await asyncio.sleep(delay)

    await client.disconnect()
    print(f"\nDone. {success} succeeded, {failed} failed.")


asyncio.run(main())
