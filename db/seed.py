import os
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from db.session import SessionLocal
from db.models import Site, User, Camera
from passlib.context import CryptContext

load_dotenv()

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(p):
    return pwd_ctx.hash(p)


def seed():
    db: Session = SessionLocal()
    try:
        if db.query(User).count() == 0:
            site = Site(name="Site A — Construction", location="Demo site")
            db.add(site)
            db.flush()

            admin = User(
                email="admin@omnix.ai",
                password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "omnix2026")),
                name="Admin",
                role="admin",
                site_id=site.id,
            )

            cam = Camera(
                site_id=site.id,
                name="Camera 1 — Loading Zone",
                location="Loading zone entrance",
                source="0",
                status="offline",
            )

            db.add_all([admin, cam])
            db.commit()
            print("[OMNIX] Seed complete — admin user and Camera 1 created.")
        else:
            print("[OMNIX] DB already seeded, skipping.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()