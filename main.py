import base64
import asyncio
import aiohttp
import aiosqlite
from datetime import datetime
import pytz
import sys
import pandas as pd
import random
import time
import sqlite3
from typing import List, Tuple
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment
from openpyxl import load_workbook
import os

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DB_NAME = "Instagram.db"
EXCEL_FILE = "InstagramData.xlsx"


def encode_auth(username: str) -> str:
    raw = f"-1::{username}::rJP2tBRKf6ktbRqPUBtRE9klgBWb7d"
    base64_str = base64.b64encode(raw.encode()).decode()
    return base64_str.replace("+", "-").replace("/", "_").rstrip("=")


async def fetch_story(session: aiohttp.ClientSession, username: str) -> dict | None:
    encoded_auth = encode_auth(username)
    url = "https://anonstories.com/api/v1/story"
    headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": "https://anonstories.com",
        "referer": "https://anonstories.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "x-requested-with": "XMLHttpRequest",
    }
    data = {"auth": encoded_auth}
    async with session.post(url, headers=headers, data=data) as resp:
        if resp.status == 200:
            return await resp.json()
        return None


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                full_name TEXT,
                is_private TEXT,
                is_verified TEXT,
                profile_pic_url TEXT,
                follower_count INTEGER,
                following_count INTEGER,
                mention TEXT,
                time TEXT
            )
        """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users_invalid (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                error_message TEXT,
                time TEXT
            )
        """
        )
        await db.commit()


async def save_user_data(username: str, data: dict | None):
    tz_iran = pytz.timezone("Asia/Tehran")
    now = datetime.now(tz_iran).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(DB_NAME) as db:
        try:
            if not data:
                raise ValueError("No data returned")

            user_info = data.get("user_info", {})
            if not user_info:
                raise ValueError("No user_info found")

            full_name = user_info.get("full_name", "")
            is_private = str(user_info.get("is_private", False))
            is_verified = str(user_info.get("is_verified", False))
            profile_pic_url = user_info.get("profile_pic_url", "")
            follower_count = user_info.get("followers", 0)
            following_count = user_info.get("following", 0)
            stories = data.get("stories", [])

            mentions = list({m for story in stories for m in story.get("mentions", [])})

            if not mentions:
                mentions = [None]

            for mention in mentions:
                await db.execute(
                    """
                    INSERT INTO users (username, full_name, is_private, is_verified,
                    profile_pic_url, follower_count, following_count, mention, time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        username,
                        full_name,
                        is_private,
                        is_verified,
                        profile_pic_url,
                        follower_count,
                        following_count,
                        mention,
                        now,
                    ),
                )

            await db.commit()
            return True

        except Exception as e:
            await db.execute(
                """
                INSERT INTO users_invalid (username, error_message, time)
                VALUES (?, ?, ?)
            """,
                (username, str(e), now),
            )
            await db.commit()
            return False


async def export_excel():
    conn = sqlite3.connect(DB_NAME)

    def save_sheet(df, sheet_name, writer):
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]

        header_font = Font(bold=True)
        alignment = Alignment(horizontal="center", vertical="center")

        for i, column in enumerate(df.columns, 1):
            col_letter = get_column_letter(i)
            ws.column_dimensions[col_letter].width = 20
            cell = ws.cell(row=1, column=i)
            cell.font = header_font
            cell.alignment = alignment

    df_users = pd.read_sql("SELECT * FROM users", conn)
    df_invalid = pd.read_sql("SELECT * FROM users_invalid", conn)

    translations = {
        "username": "نام کاربری",
        "full_name": "نام کامل",
        "is_private": "خصوصی",
        "is_verified": "تأیید شده",
        "profile_pic_url": "عکس پروفایل",
        "mention": "منشن",
        "follower_count": "تعداد فالوئر",
        "following_count": "تعداد فالووینگ",
        "time": "زمان دریافت",
        "error_message": "پیام خطا",
    }

    df_users_fa = df_users.rename(columns=translations)
    df_invalid_fa = df_invalid.rename(columns=translations)

    with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
        save_sheet(df_users, "Users (EN)", writer)
        save_sheet(df_users_fa, "کاربران (FA)", writer)
        save_sheet(df_invalid, "Invalid (EN)", writer)
        save_sheet(df_invalid_fa, "نامعتبرها (FA)", writer)

    conn.close()


async def process_usernames(usernames: List[str]) -> Tuple[int, int]:
    success, fail = 0, 0
    async with aiohttp.ClientSession() as session:
        for i, username in enumerate(usernames, 1):
            try:
                data = await fetch_story(session, username)
                if await save_user_data(username, data):
                    print(f"✅ {username} saved.")
                    success += 1
                else:
                    print(f"❌ Failed saving {username}")
                    fail += 1
            except Exception as e:
                print(f"❌ Exception for {username}: {e}")
                await save_user_data(username, None)
                fail += 1
            await asyncio.sleep(random.uniform(1, 2))
            print(f"⏳ Remaining: {len(usernames)-i}")

    return success, fail


async def main():
    start = time.perf_counter()
    await init_db()

    # خواندن نام‌کاربری‌ها از فایل اکسل
    if not os.path.exists("1.xlsx"):
        print("❌ فایل 1.xlsx پیدا نشد.")
        return

    try:
        df = pd.read_excel("1.xlsx", header=None)
        usernames = df.iloc[:, 0].dropna().astype(str).tolist()
    except Exception as e:
        print(f"❌ خطا در خواندن فایل اکسل: {e}")
        return

    success, fail = await process_usernames(usernames)

    # تلاش مجدد تا ۵ بار
    max_retries = 5
    total_retry_success = 0

    for attempt in range(1, max_retries + 1):
        print(f"\n🔁 Retry attempt {attempt}...")

        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT username FROM users_invalid") as cursor:
                invalid_usernames = [row[0] async for row in cursor]

        invalid_usernames = list(set(invalid_usernames))

        if not invalid_usernames:
            print("✅ No more failed usernames to retry.")
            break

        retry_success, _ = await process_usernames(invalid_usernames)
        total_retry_success += retry_success

    await export_excel()
    duration = int(time.perf_counter() - start)

    print(f"\n📊 Total Success: {success + total_retry_success}")
    print(f"❌ Total Fail after retries: {len(invalid_usernames)}")
    print(f"🕒 Time Taken: {duration} seconds")
    print(f"📁 Excel Saved as: {EXCEL_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
