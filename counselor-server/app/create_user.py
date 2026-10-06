import getpass
import sys
from sqlalchemy import select
from argon2 import PasswordHasher
from .database import SessionLocal
from .models import User

def read_utf8(prompt):
    value = input(prompt).strip()
    value.encode("utf-8", errors="strict")
    return value

def main():
    # Windows Docker terminals can inherit an ASCII stdin with surrogateescape.
    # Decode UTF-8 explicitly and reject invalid bytes before touching the DB.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    try:
        email = read_utf8("Email: ").lower()
        name = read_utf8("Name: ")
        password = getpass.getpass("Password (12+ characters): ")
        password.encode("utf-8", errors="strict")
    except UnicodeError:
        raise SystemExit("Invalid terminal encoding. Run chcp 65001 in PowerShell, then retry with python -X utf8.")
    if "@" not in email or not name or len(password) < 12:
        raise SystemExit("Invalid input")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("User already exists")
        db.add(User(email=email, name=name, password_hash=PasswordHasher().hash(password)))
        db.commit()
    print("User created")

if __name__ == "__main__":
    main()
