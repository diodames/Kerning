from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(config.DATABASE_URL, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
        if "weekly" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN weekly INTEGER NOT NULL DEFAULT 1")
        if "send_dow" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN send_dow INTEGER NOT NULL DEFAULT 1")
        if "send_slot" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN send_slot VARCHAR(16) NOT NULL DEFAULT 'morning'"
            )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
