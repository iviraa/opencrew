"""Create the two company logins in Supabase (local or hosted). Safe to run again."""
import os

import httpx

import app.db  # noqa: F401  loads .env

DOMAIN = "crewly.test"  # people type a username; auth needs an email
PASSWORD = "crewly123"
PEOPLE = [  # username, company, display name
    ("dominion", "desc", "Dominion Energy SC"),
    ("georgia", "gpc", "Georgia Power"),
]


def main():
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SECRET_KEY"]
    with httpx.Client(timeout=30, headers={"apikey": key}) as c:
        found = {u["email"]: u["id"] for u in c.get(f"{url}/auth/v1/admin/users", params={"per_page": 1000}).raise_for_status().json()["users"]}
        for username, company, name in PEOPLE:
            email = f"{username}@{DOMAIN}"
            meta = {"password": PASSWORD, "app_metadata": {"company_id": company}, "user_metadata": {"username": username}}  # app_metadata only admins can change
            if uid := found.get(email):
                c.put(f"{url}/auth/v1/admin/users/{uid}", json=meta).raise_for_status()  # keep the demo password in sync
            else:
                uid = c.post(f"{url}/auth/v1/admin/users", json={"email": email, "email_confirm": True, **meta}).raise_for_status().json()["id"]
            c.post(f"{url}/rest/v1/member", json={"user_id": uid, "company_id": company, "username": username, "name": name},
                   headers={"Prefer": "resolution=merge-duplicates"}).raise_for_status()
            print(f"{company:5} {username} / {PASSWORD}")


if __name__ == "__main__":
    main()
