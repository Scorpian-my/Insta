import os
from instagrapi import Client

USERNAME = "pynux.art3"
PASSWORD = "Mahyar_85"
SESSION_FILE = "session.json"

cl = Client()

if os.path.exists(SESSION_FILE):
    try:
        cl.load_settings(SESSION_FILE)
        cl.login(USERNAME, PASSWORD)
        cl.get_timeline_feed()
        print("✅ Logged in via session.")
    except Exception as e:
        print("⚠️ Session invalid, re-login...")
        cl.login(USERNAME, PASSWORD)
        cl.dump_settings(SESSION_FILE)
        print("✅ Session renewed.")
else:
    cl.login(USERNAME, PASSWORD)
    cl.dump_settings(SESSION_FILE)
    print("✅ Session saved.")

user_id = cl.user_id_from_username("psg")
stories = cl.user_stories(user_id)

print("📣 لیست منشن‌شده‌ها در استوری‌ها:")
for story in stories:
    if story.mentions:
        print(f"\n📅 تاریخ: {story.taken_at}")
        for mention in story.mentions:
            print(f"🔸 یوزرنیم: @{mention.user.username}")
            print(f"   🧾 نام کامل: {mention.user.full_name}")
            print(f"   🖼️ پروفایل: {mention.user.profile_pic_url}")
