import asyncio
import csv
import os
import random
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    ChatAdminRequiredError,
    ChatNotModifiedError,
    FloodWaitError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import EditTitleRequest
from telethon.tl.functions.messages import EditChatTitleRequest
from telethon.tl.types import Channel

# Load .env file if present
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))

API_ID = int("")
API_HASH = ""
SESSION_STRING = ""
CSV_PATH = os.environ.get("CSV_PATH", "migration.csv")
MIN_DELAY = int(os.environ.get("MIN_DELAY", "5"))
MAX_DELAY = int(os.environ.get("MAX_DELAY", "10"))

if not API_ID or not API_HASH:
    print("Error: API_ID and API_HASH environment variables are required.")
    sys.exit(1)


def load_rows() -> list[dict]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(rows: list[dict], fieldnames: list[str]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def main():
    rows = load_rows()

    # Ensure result columns exist
    for row in rows:
        row.setdefault("Rename Status", "")
        row.setdefault("Rename Reason", "")

    fieldnames = list(rows[0].keys()) if rows else []

    to_process = [r for r in rows if r.get("Old Chat ID", "").strip()]

    print(f"Processing {len(to_process)} rows with an Old Chat ID.\n")

    session = StringSession(SESSION_STRING)
    client = TelegramClient(session, API_ID, API_HASH)

    await client.start()

    saved = client.session.save()
    if not SESSION_STRING:
        print("\nSave this session string to skip login next time:")
        print(f'SESSION_STRING="{saved}"\n')

    print("Fetching dialogs to cache access hashes...")
    await client.get_dialogs(limit=None)
    print("Done.\n")

    success = 0
    skipped = 0
    failed = 0

    for row in to_process:
        chat_id = int(row["Old Chat ID"].strip())
        channel_name = row["Channel Name"].strip()
        new_title = f"[ARCHIVED] - {channel_name}"

        try:
            entity = await client.get_entity(chat_id)
        except Exception as e:
            print(
                f"  [FAIL] Cannot get entity for {channel_name} ({chat_id}): {e}"
            )
            row["Rename Status"] = "failed"
            row["Rename Reason"] = f"Cannot get entity: {e}"
            failed += 1
            save_rows(rows, fieldnames)
            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            continue

        current_title = getattr(entity, "title", None)

        if current_title and current_title.startswith("[ARCHIVED]"):
            print(f"  [SKIP] Already archived: {channel_name}")
            row["Rename Status"] = "skipped"
            row["Rename Reason"] = "Already archived"
            skipped += 1
            save_rows(rows, fieldnames)
            await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            continue

        done = False
        while not done:
            try:
                if isinstance(entity, Channel):
                    await client(
                        EditTitleRequest(channel=entity, title=new_title)
                    )
                else:
                    await client(
                        EditChatTitleRequest(chat_id=entity.id, title=new_title)
                    )

                print(f'  [OK] Renamed: "{current_title}" → "{new_title}"')
                row["Rename Status"] = "renamed"
                row["Rename Reason"] = ""
                success += 1
                done = True

            except FloodWaitError as e:
                extra = random.randint(5, 15)
                total = e.seconds + extra
                print(
                    f"  [FLOOD] {channel_name}: waiting {total}s ({e.seconds}s required + {extra}s buffer)..."
                )
                await asyncio.sleep(total)

            except ChatAdminRequiredError:
                print(f"  [FAIL] No admin rights: {channel_name}")
                row["Rename Status"] = "failed"
                row["Rename Reason"] = "No admin rights"
                failed += 1
                done = True

            except ChatNotModifiedError:
                print(f"  [SKIP] Title unchanged (already set): {channel_name}")
                row["Rename Status"] = "skipped"
                row["Rename Reason"] = "Title already set"
                skipped += 1
                done = True

            except Exception as e:
                print(f"  [FAIL] {channel_name}: {e}")
                row["Rename Status"] = "failed"
                row["Rename Reason"] = str(e)
                failed += 1
                done = True

        save_rows(rows, fieldnames)
        await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    await client.disconnect()
    print(f"\nDone. {success} renamed, {skipped} skipped, {failed} failed.")


asyncio.run(main())
