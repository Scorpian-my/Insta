import pandas as pd
import os
import json
import sqlite3
from datetime import datetime
import pytz
from seleniumwire import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import gzip
import zlib

DB_NAME = "Instagram.db"
INFO_JSON = "info.json"
EXCEL_FILE = "1.xlsx"
SHEET_NAME = "user_list"  # یا هر شیت دلخواه

# ساخت جدول دیتابیس اگر وجود ندارد
conn = sqlite3.connect(DB_NAME)
c = conn.cursor()
c.execute('''
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
''')
c.execute('''
    CREATE TABLE IF NOT EXISTS users_invalid (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        reason TEXT,
        time TEXT
    )
''')
c.execute('''
    CREATE TABLE IF NOT EXISTS users_error (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        reason TEXT,
        time TEXT
    )
''')
conn.commit()
conn.close()

# خواندن یوزرنیم‌ها از اکسل
df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
usernames = df['username'].dropna().tolist()

def save_user_and_mentions_from_json(json_file, db_name):
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    user = None
    try:
        user = data["userInfo"]["result"][0]["user"]
    except Exception:
        user = None
    if user:
        tz_iran = pytz.timezone("Asia/Tehran")
        now = datetime.now(tz_iran).strftime("%Y-%m-%d %H:%M:%S")
        stories_data = data.get("stories")
        if not isinstance(stories_data, dict):
            stories = []
        else:
            stories = stories_data.get("result", [])
        def extract_mentions(story):
            mentions = set()
            stickers = story.get("story_bloks_stickers", [])
            for sticker in stickers:
                ig_mention = (
                    sticker.get("bloks_sticker", {})
                    .get("sticker_data", {})
                    .get("ig_mention", {})
                )
                if ig_mention and ig_mention.get("username"):
                    mentions.add(ig_mention["username"])
            return mentions
        mentions = set()
        for story in stories:
            mentions.update(extract_mentions(story))
        if not mentions:
            mentions = [None]
        for mention in mentions:
            c.execute(
                """
                INSERT INTO users (username, full_name, is_private, is_verified, profile_pic_url, follower_count, following_count, mention, time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user.get("username"),
                    user.get("full_name"),
                    str(user.get("is_private")),
                    str(user.get("is_verified")),
                    user.get("profile_pic_url"),
                    user.get("follower_count"),
                    user.get("following_count"),
                    mention,
                    now,
                ),
            )
        conn.commit()
    conn.close()

for idx, username in enumerate(usernames, 1):
    print(f"در حال پردازش یوزرنیم {idx} از {len(usernames)}: {username}")
    # حذف فایل info.json قبلی اگر وجود دارد
    if os.path.exists(INFO_JSON):
        os.remove(INFO_JSON)

    # --- عملیات Selenium مشابه 0.py ---
    options = {"enable_har": True}
    driver = webdriver.Chrome(seleniumwire_options=options)
    driver.implicitly_wait(10)
    try:
        driver.get("https://storiesig.info/en/")
        wait = WebDriverWait(driver, 15)
        input_box = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input.search.search-form__input"))
        )
        input_box.clear()
        input_box.send_keys(username)
        search_btn = driver.find_element(By.CSS_SELECTOR, "button.search-form__button")
        main_window = driver.current_window_handle
        before_windows = set(driver.window_handles)
        search_btn.click()
        time.sleep(1)
        after_windows = set(driver.window_handles)
        new_windows = after_windows - before_windows
        for win in new_windows:
            driver.switch_to.window(win)
            driver.close()
        driver.switch_to.window(main_window)
        time.sleep(3)
        # اضافه کردن منطق کلیک روی دکمه استوری
        try:
            stories_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, '//button[normalize-space(text())="stories"]'))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", stories_button)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", stories_button)
            time.sleep(2)
        except Exception as e:
            # اگر دکمه استوری نبود، ادامه بده (مثلاً کاربر استوری ندارد)
            pass
        target_url_stories = "https://api-wh.storiesig.info/api/v1/instagram/stories"
        target_url_userinfo = "https://api-wh.storiesig.info/api/v1/instagram/userInfo"
        userinfo_json = None
        stories_json = None
        for request in driver.requests:
            if request.response:
                url = request.url
                content_type = request.response.headers.get("Content-Type", "").lower()
                encoding = request.response.headers.get("Content-Encoding", "").lower()
                body = request.response.body
                if encoding == "gzip":
                    body = gzip.decompress(body)
                elif encoding == "deflate":
                    body = zlib.decompress(body)
                if "application/json" in content_type:
                    try:
                        text = body.decode("utf-8")
                    except Exception:
                        continue  # اگر decode نشد، این درخواست را نادیده بگیر
                    if target_url_userinfo in url:
                        try:
                            userinfo_json = json.loads(text)
                        except Exception:
                            pass
                    elif target_url_stories in url:
                        try:
                            stories_json = json.loads(text)
                        except Exception:
                            pass
            if userinfo_json and stories_json:
                break
        if userinfo_json or stories_json:
            combined = {"userInfo": userinfo_json, "stories": stories_json}
            with open(INFO_JSON, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, indent=2)
    finally:
        driver.quit()

    # --- ذخیره در دیتابیس با مدیریت خطاها و دسته‌بندی دقیق ---
    tz_iran = pytz.timezone("Asia/Tehran")
    now = datetime.now(tz_iran).strftime("%Y-%m-%d %H:%M:%S")
    # اگر فایل info.json ساخته نشده
    if not os.path.exists(INFO_JSON):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(
            "INSERT INTO users_invalid (username, reason, time) VALUES (?, ?, ?)",
            (username, "not found", now)
        )
        conn.commit()
        conn.close()
        continue
    # اگر فایل ساخته شده، اما userInfo یا user وجود ندارد
    with open(INFO_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    user = None
    try:
        user = data["userInfo"]["result"][0]["user"]
    except Exception as e:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(
            "INSERT INTO users_error (username, reason, time) VALUES (?, ?, ?)",
            (username, f"userInfo missing", now)
        )
        conn.commit()
        conn.close()
        continue
    # اگر user هست اما username وجود ندارد
    if not user.get("username"):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(
            "INSERT INTO users_invalid (username, reason, time) VALUES (?, ?, ?)",
            (username, "username field missing in userInfo", now)
        )
        conn.commit()
        conn.close()
        continue
    # اگر پیج پرایوت است
    if user.get("is_private") == True:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(
            "INSERT INTO users_invalid (username, reason, time) VALUES (?, ?, ?)",
            (username, "private account", now)
        )
        conn.commit()
        conn.close()
        continue
    # ذخیره اطلاعات معتبر در users (حتی اگر استوری ندارد)
    save_user_and_mentions_from_json(INFO_JSON, DB_NAME)

    # حذف فایل info.json برای یوزرنیم بعدی
    if os.path.exists(INFO_JSON):
        os.remove(INFO_JSON)

print("✅ عملیات برای همه یوزرنیم‌ها انجام شد و داده‌ها در دیتابیس ذخیره شدند.")