"""Create every utility and its login in Supabase (local or hosted) from the planner's org table. Safe to run again."""
import os

import httpx

from app.companies import load
from app.db import connect

DOMAIN = "crewly.test"  # people type a username; auth needs an email
PASSWORD = "crewly123"


def main():
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SECRET_KEY"]
    with connect() as conn:
        orgs = [c for c in load(conn).values() if c["login"]]
    with httpx.Client(timeout=30, headers={"apikey": key}) as c:
        c.post(f"{url}/rest/v1/company", headers={"Prefer": "resolution=merge-duplicates"},  # the directory first, logins point at it
               json=[{k: o[k] for k in ("id", "name", "short", "color", "state", "planner", "login")} for o in orgs]).raise_for_status()
        found = {u["email"]: u["id"] for u in c.get(f"{url}/auth/v1/admin/users", params={"per_page": 1000}).raise_for_status().json()["users"]}
        for o in orgs:
            email = f"{o['login']}@{DOMAIN}"
            meta = {"password": PASSWORD, "app_metadata": {"company_id": o["id"]}, "user_metadata": {"username": o["login"]}}  # app_metadata only admins can change
            if uid := found.get(email):
                c.put(f"{url}/auth/v1/admin/users/{uid}", json=meta).raise_for_status()  # keep the demo password in sync
            else:
                uid = c.post(f"{url}/auth/v1/admin/users", json={"email": email, "email_confirm": True, **meta}).raise_for_status().json()["id"]
            c.post(f"{url}/rest/v1/member", json={"user_id": uid, "company_id": o["id"], "username": o["login"], "name": o["name"]},
                   headers={"Prefer": "resolution=merge-duplicates"}).raise_for_status()
            print(f"{o['id']:12} {o['state'] or '':3} {o['login']} / {PASSWORD}")


if __name__ == "__main__":
    main()
