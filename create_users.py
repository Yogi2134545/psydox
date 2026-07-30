"""
Psydox — User Management CLI
Run this script once to add team members.

Usage:
    python create_users.py
"""
import bcrypt, yaml, getpass
from pathlib import Path

USERS_FILE = Path(__file__).parent / "users.yaml"


def load():
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, "r") as f:
        return yaml.safe_load(f) or {}


def save(users):
    with open(USERS_FILE, "w") as f:
        yaml.dump(users, f, default_flow_style=False)


def add_user():
    users = load()
    print("\n── Add / Update User ──────────────────")
    name  = input("Display name : ").strip()
    email = input("Email address: ").strip().lower()
    pwd   = getpass.getpass("Password     : ")
    pwd2  = getpass.getpass("Confirm pwd  : ")
    if pwd != pwd2:
        print("Passwords do not match. Aborted.")
        return
    hashed = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
    users[email] = {"name": name, "password_hash": hashed}
    save(users)
    print(f"✓ Saved user: {name} <{email}>")


def list_users():
    users = load()
    if not users:
        print("No users yet.")
        return
    print("\n── Current Users ──────────────────────")
    for email, u in users.items():
        print(f"  {u.get('name','?'):20s}  {email}")


def remove_user():
    users = load()
    list_users()
    email = input("\nEmail to remove: ").strip().lower()
    if email in users:
        del users[email]
        save(users)
        print(f"✓ Removed {email}")
    else:
        print("Not found.")


def main():
    while True:
        print("\n══ Psydox User Manager ══")
        print("  1. Add / update user")
        print("  2. List users")
        print("  3. Remove user")
        print("  4. Exit")
        choice = input("Choice: ").strip()
        if choice == "1":
            add_user()
        elif choice == "2":
            list_users()
        elif choice == "3":
            remove_user()
        elif choice == "4":
            break


if __name__ == "__main__":
    main()
