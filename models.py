from sqlalchemy import create_engine, Column, String, Integer, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class ActivityRating(Base):
    __tablename__ = "activity_ratings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    activity_name = Column(String)
    city = Column(String)
    category = Column(String)
    elo_score = Column(Float, default=1000.0)
    matches = Column(Integer, default=0)

def init_db():
    Base.metadata.create_all(bind=engine)