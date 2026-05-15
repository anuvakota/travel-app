from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import os
from dotenv import load_dotenv
from models import SessionLocal, ActivityRating, init_db

load_dotenv()
init_db()

app = FastAPI()

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

# --- Google Places helpers ---

def get_location(city: str):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": city, "key": GOOGLE_API_KEY}
    res = requests.get(url, params=params).json()
    if not res["results"]:
        raise HTTPException(status_code=404, detail="City not found")
    return res["results"][0]["geometry"]["location"]

def search_activities(lat: float, lng: float, category: str):
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": 5000,
        "type": category,
        "key": GOOGLE_API_KEY,
    }
    res = requests.get(url, params=params).json()
    return [
        {
            "name": p["name"],
            "rating": p.get("rating", 0),
            "address": p.get("vicinity", ""),
            "category": category,
            "price_level": p.get("price_level", 0),
        }
        for p in res.get("results", [])[:10]
    ]

@app.get("/activities")
def get_activities(
    city: str,
    category: str = "tourist_attraction",
    min_rating: float = 0.0,
    max_price: int = 4,
):
    location = get_location(city)
    activities = search_activities(location["lat"], location["lng"], category)
    filtered = [
        a for a in activities
        if a["rating"] >= min_rating and a["price_level"] <= max_price
    ]
    return {"city": city, "count": len(filtered), "activities": filtered}

# --- ELO helpers ---

K = 32

def expected_score(rating_a: float, rating_b: float):
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

def update_elo(winner_rating: float, loser_rating: float):
    expected = expected_score(winner_rating, loser_rating)
    new_winner = winner_rating + K * (1 - expected)
    new_loser = loser_rating + K * (0 - (1 - expected))
    return round(new_winner, 1), round(new_loser, 1)

def get_or_create_rating(db, user_id: str, activity_name: str, city: str, category: str):
    rating = db.query(ActivityRating).filter_by(
        user_id=user_id,
        activity_name=activity_name,
        city=city
    ).first()
    if not rating:
        rating = ActivityRating(
            user_id=user_id,
            activity_name=activity_name,
            city=city,
            category=category,
            elo_score=1000.0,
            matches=0
        )
        db.add(rating)
        db.commit()
        db.refresh(rating)
    return rating

# --- ELO endpoints ---

class MatchupResult(BaseModel):
    user_id: str
    winner_name: str
    loser_name: str
    city: str
    category: str

@app.post("/matchup")
def record_matchup(result: MatchupResult):
    db = SessionLocal()
    try:
        winner = get_or_create_rating(db, result.user_id, result.winner_name, result.city, result.category)
        loser = get_or_create_rating(db, result.user_id, result.loser_name, result.city, result.category)

        new_winner_score, new_loser_score = update_elo(winner.elo_score, loser.elo_score)

        winner.elo_score = new_winner_score
        winner.matches += 1
        loser.elo_score = new_loser_score
        loser.matches += 1

        db.commit()
        return {
            "winner": {"name": result.winner_name, "new_score": new_winner_score},
            "loser": {"name": result.loser_name, "new_score": new_loser_score}
        }
    finally:
        db.close()

@app.get("/rankings/{user_id}/{city}")
def get_rankings(user_id: str, city: str):
    db = SessionLocal()
    try:
        ratings = db.query(ActivityRating).filter_by(
            user_id=user_id,
            city=city
        ).order_by(ActivityRating.elo_score.desc()).all()
        return {
            "user_id": user_id,
            "city": city,
            "rankings": [
                {"rank": i+1, "name": r.activity_name, "elo_score": r.elo_score, "matches": r.matches}
                for i, r in enumerate(ratings)
            ]
        }
    finally:
        db.close()