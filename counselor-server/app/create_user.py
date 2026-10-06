import getpass
from sqlalchemy import select
from argon2 import PasswordHasher
from .database import SessionLocal
from .models import User

def main():
    email = input("Email: ").strip().lower()
    name = input("Name: ").strip()
    password = getpass.getpass("Password (12+ characters): ")
    if "@" not in email or not name or len(password) < 12: raise SystemExit("Invalid input")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)): raise SystemExit("User already exists")
        db.add(User(email=email, name=name, password_hash=PasswordHasher().hash(password)))
        db.commit()
    print("User created")
if __name__ == "__main__": main()
