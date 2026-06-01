from sqlalchemy import create_engine, Column, String, Integer, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./globr.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})


SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    session_token = Column(String, nullable=True)
    created_at = Column(String, nullable=True)

class UserTrip(Base):
    __tablename__ = "user_trips"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    city = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    mode = Column(String)
    itinerary_json = Column(String, nullable=True)
    created_at = Column(String, nullable=True)

class UserSavedPlace(Base):
    __tablename__ = "user_saved_places"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    city = Column(String)
    category = Column(String)
    place_name = Column(String)
    place_json = Column(String)
    saved_at = Column(String, nullable=True)

class ActivityRating(Base):
    __tablename__ = "activity_ratings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    activity_name = Column(String)
    city = Column(String)
    category = Column(String)
    elo_score = Column(Float, default=1000.0)
    matches = Column(Integer, default=0)

class TripShare(Base):
    __tablename__ = "trip_shares"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, index=True)
    owner_id = Column(Integer, index=True)
    # Who it's shared with. For email shares, recipient_email is set.
    # For link shares, share_token is set and recipient_email may be null.
    recipient_email = Column(String, nullable=True, index=True)
    share_token = Column(String, nullable=True, index=True)
    permission = Column(String, default="view")  # "view" | "edit"
    created_at = Column(String, nullable=True)

def init_db():
    Base.metadata.create_all(bind=engine)