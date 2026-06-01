from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import requests
import os
import re
import json
import hashlib
import secrets
from datetime import datetime
from dotenv import load_dotenv
from models import SessionLocal, ActivityRating, init_db, User, UserTrip, UserSavedPlace, TripShare
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

load_dotenv()
init_db()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

security = HTTPBearer(auto_error=False)

# ---- Auth helpers ----

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, hashed = stored.split(":", 1)
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == hashed
    except Exception:
        return False

def create_token(user_id: int) -> str:
    token_data = f"{user_id}:{secrets.token_hex(32)}"
    return token_data

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        return None
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(session_token=credentials.credentials).first()
        return user
    finally:
        db.close()

def require_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user = get_current_user(credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# ---- Auth endpoints ----

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/auth/register")
def register(req: RegisterRequest):
    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(email=req.email.lower().strip()).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        if len(req.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        token = create_token(0)
        user = User(
            email=req.email.lower().strip(),
            name=req.name.strip(),
            password_hash=hash_password(req.password),
            session_token=token,
            created_at=datetime.utcnow().isoformat(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        # Update token with real user id
        user.session_token = create_token(user.id)
        db.commit()
        return {
            "token": user.session_token,
            "user": {"id": user.id, "email": user.email, "name": user.name}
        }
    finally:
        db.close()

@app.post("/auth/login")
def login(req: LoginRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=req.email.lower().strip()).first()
        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        user.session_token = create_token(user.id)
        db.commit()
        return {
            "token": user.session_token,
            "user": {"id": user.id, "email": user.email, "name": user.name}
        }
    finally:
        db.close()

@app.post("/auth/logout")
def logout(user: User = Depends(require_user)):
    db = SessionLocal()
    try:
        db_user = db.query(User).filter_by(id=user.id).first()
        if db_user:
            db_user.session_token = None
            db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.get("/auth/me")
def me(user: User = Depends(require_user)):
    return {"id": user.id, "email": user.email, "name": user.name}


# ---- Saved Places (per user) ----

class SavePlaceRequest(BaseModel):
    city: str
    category: str  # activities | food | hotels
    place: dict

@app.get("/saved/{city}")
def get_saved(city: str, user: User = Depends(require_user)):
    db = SessionLocal()
    try:
        places = db.query(UserSavedPlace).filter_by(user_id=user.id, city=city).all()
        result = {"activities": [], "food": [], "hotels": []}
        for p in places:
            data = json.loads(p.place_json)
            cat = p.category
            if cat in result:
                result[cat].append(data)
        return result
    finally:
        db.close()

@app.post("/saved")
def save_place(req: SavePlaceRequest, user: User = Depends(require_user)):
    db = SessionLocal()
    try:
        existing = db.query(UserSavedPlace).filter_by(
            user_id=user.id, city=req.city, category=req.category,
            place_name=req.place.get("name", "")
        ).first()
        if existing:
            db.delete(existing)
            db.commit()
            return {"saved": False}
        sp = UserSavedPlace(
            user_id=user.id,
            city=req.city,
            category=req.category,
            place_name=req.place.get("name", ""),
            place_json=json.dumps(req.place),
            saved_at=datetime.utcnow().isoformat(),
        )
        db.add(sp)
        db.commit()
        return {"saved": True}
    finally:
        db.close()


# ---- User Trips ----

class SaveTripRequest(BaseModel):
    city: str
    start_date: str
    end_date: str
    mode: str
    itinerary: Optional[dict] = None  # day -> [places]

@app.get("/trips")
def get_trips(user: User = Depends(require_user)):
    db = SessionLocal()
    try:
        trips = db.query(UserTrip).filter_by(user_id=user.id).order_by(UserTrip.created_at.desc()).all()
        return [
            {
                "id": t.id,
                "city": t.city,
                "start_date": t.start_date,
                "end_date": t.end_date,
                "mode": t.mode,
                "itinerary": json.loads(t.itinerary_json) if t.itinerary_json else {},
                "created_at": t.created_at,
            }
            for t in trips
        ]
    finally:
        db.close()

@app.post("/trips")
def save_trip(req: SaveTripRequest, user: User = Depends(require_user)):
    db = SessionLocal()
    try:
        trip = UserTrip(
            user_id=user.id,
            city=req.city,
            start_date=req.start_date,
            end_date=req.end_date,
            mode=req.mode,
            itinerary_json=json.dumps(req.itinerary or {}),
            created_at=datetime.utcnow().isoformat(),
        )
        db.add(trip)
        db.commit()
        db.refresh(trip)
        return {"id": trip.id, "ok": True}
    finally:
        db.close()

@app.delete("/trips/{trip_id}")
def delete_trip(trip_id: int, user: User = Depends(require_user)):
    db = SessionLocal()
    try:
        trip = db.query(UserTrip).filter_by(id=trip_id, user_id=user.id).first()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        db.delete(trip)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ---- Trip Sharing ----

def _serialize_trip(t):
    return {
        "id": t.id,
        "city": t.city,
        "start_date": t.start_date,
        "end_date": t.end_date,
        "mode": t.mode,
        "itinerary": json.loads(t.itinerary_json) if t.itinerary_json else {},
        "created_at": t.created_at,
    }


class ShareTripRequest(BaseModel):
    trip_id: int
    recipient_email: Optional[str] = None  # if provided -> email share
    permission: str = "view"               # "view" | "edit"
    create_link: bool = False              # if true -> also create/return a link token


@app.post("/share")
def share_trip(req: ShareTripRequest, user: User = Depends(require_user)):
    db = SessionLocal()
    try:
        # Verify the trip belongs to the requesting user
        trip = db.query(UserTrip).filter_by(id=req.trip_id, user_id=user.id).first()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")

        if req.permission not in ("view", "edit"):
            raise HTTPException(status_code=400, detail="permission must be 'view' or 'edit'")

        result = {"ok": True}

        # Email share
        if req.recipient_email:
            email = req.recipient_email.lower().strip()
            existing = db.query(TripShare).filter_by(
                trip_id=req.trip_id, recipient_email=email
            ).first()
            if existing:
                existing.permission = req.permission
            else:
                share = TripShare(
                    trip_id=req.trip_id,
                    owner_id=user.id,
                    recipient_email=email,
                    permission=req.permission,
                    created_at=datetime.utcnow().isoformat(),
                )
                db.add(share)
            db.commit()
            result["shared_with"] = email

        # Link share
        if req.create_link:
            token = secrets.token_urlsafe(12)
            share = TripShare(
                trip_id=req.trip_id,
                owner_id=user.id,
                recipient_email=None,
                share_token=token,
                permission=req.permission,
                created_at=datetime.utcnow().isoformat(),
            )
            db.add(share)
            db.commit()
            result["share_token"] = token

        return result
    finally:
        db.close()


@app.get("/shared-with-me")
def shared_with_me(user: User = Depends(require_user)):
    """Trips other people have shared with the current user (by email)."""
    db = SessionLocal()
    try:
        shares = db.query(TripShare).filter_by(recipient_email=user.email.lower().strip()).all()
        out = []
        for s in shares:
            trip = db.query(UserTrip).filter_by(id=s.trip_id).first()
            if not trip:
                continue
            owner = db.query(User).filter_by(id=s.owner_id).first()
            data = _serialize_trip(trip)
            data["permission"] = s.permission
            data["shared_by"] = {"name": owner.name, "email": owner.email} if owner else None
            data["share_id"] = s.id
            out.append(data)
        return out
    finally:
        db.close()


@app.get("/shared/{token}")
def get_shared_by_link(token: str):
    """Public: anyone with the link token can view (frontend gates edit)."""
    db = SessionLocal()
    try:
        share = db.query(TripShare).filter_by(share_token=token).first()
        if not share:
            raise HTTPException(status_code=404, detail="Share link not found")
        trip = db.query(UserTrip).filter_by(id=share.trip_id).first()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        owner = db.query(User).filter_by(id=share.owner_id).first()
        data = _serialize_trip(trip)
        data["permission"] = share.permission
        data["shared_by"] = {"name": owner.name, "email": owner.email} if owner else None
        return data
    finally:
        db.close()


@app.get("/trips/{trip_id}/shares")
def list_shares(trip_id: int, user: User = Depends(require_user)):
    """Owner sees who they've shared a trip with."""
    db = SessionLocal()
    try:
        trip = db.query(UserTrip).filter_by(id=trip_id, user_id=user.id).first()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        shares = db.query(TripShare).filter_by(trip_id=trip_id, owner_id=user.id).all()
        return [
            {
                "id": s.id,
                "recipient_email": s.recipient_email,
                "share_token": s.share_token,
                "permission": s.permission,
                "created_at": s.created_at,
            }
            for s in shares
        ]
    finally:
        db.close()


@app.delete("/share/{share_id}")
def revoke_share(share_id: int, user: User = Depends(require_user)):
    db = SessionLocal()
    try:
        share = db.query(TripShare).filter_by(id=share_id, owner_id=user.id).first()
        if not share:
            raise HTTPException(status_code=404, detail="Share not found")
        db.delete(share)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


class UpdateSharedTripRequest(BaseModel):
    itinerary: Optional[dict] = None
    city: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@app.put("/shared-trips/{trip_id}")
def update_shared_trip(trip_id: int, req: UpdateSharedTripRequest, user: User = Depends(require_user)):
    """A recipient with edit permission can update the trip."""
    db = SessionLocal()
    try:
        share = db.query(TripShare).filter_by(
            trip_id=trip_id, recipient_email=user.email.lower().strip()
        ).first()
        if not share or share.permission != "edit":
            raise HTTPException(status_code=403, detail="You don't have edit access to this trip")
        trip = db.query(UserTrip).filter_by(id=trip_id).first()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        if req.itinerary is not None:
            trip.itinerary_json = json.dumps(req.itinerary)
        if req.city is not None:
            trip.city = req.city
        if req.start_date is not None:
            trip.start_date = req.start_date
        if req.end_date is not None:
            trip.end_date = req.end_date
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ---- Google Places helpers ----

def search_activities(city: str, category: str, query: Optional[str] = None):
    seen = set()
    results = []

    if query:
        keywords = [
            f"{query} in {city}",
            f"best {query} in {city}",
            f"top {query} {city}",
            f"popular {query} {city}",
            f"{query} near {city}",
        ]
    else:
        keyword_map = {
            "tourist_attraction": [
                f"best things to do in {city}",
                f"popular attractions in {city}",
                f"hidden gems in {city}",
                f"most visited places in {city}",
                f"top sights in {city}",
                f"famous landmarks in {city}",
                f"outdoor activities in {city}",
                f"museums in {city}",
            ],
            "restaurant": [
                f"best restaurants in {city}",
                f"popular food spots in {city}",
                f"must eat places in {city}",
                f"trending restaurants in {city}",
                f"best cafes in {city}",
                f"best brunch in {city}",
                f"best bars in {city}",
                f"best desserts in {city}",
            ],
            "lodging": [
                f"best hotels in {city}",
                f"popular places to stay in {city}",
                f"top rated hotels in {city}",
                f"boutique hotels in {city}",
                f"luxury hotels in {city}",
                f"budget hotels in {city}",
            ],
        }
        keywords = keyword_map.get(category, [f"best places in {city}"])

    for keyword in keywords:
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {"query": keyword, "key": GOOGLE_API_KEY}
        res = requests.get(url, params=params).json()
        for p in res.get("results", []):
            name = p.get("name")
            if name and name not in seen:
                seen.add(name)
                results.append({
                    "name": name,
                    "rating": p.get("rating", 0),
                    "address": p.get("formatted_address", ""),
                    "price_level": p.get("price_level", 2),
                    "total_ratings": p.get("user_ratings_total", 0),
                })

    results.sort(key=lambda x: x["total_ratings"], reverse=True)
    return results[:100]


@app.get("/activities")
def get_activities(
    city: str,
    category: str = "tourist_attraction",
    min_rating: float = 0.0,
    max_price: int = 4,
    query: Optional[str] = None,
):
    activities = search_activities(city, category, query=query)
    filtered = [
        a for a in activities
        if a["rating"] >= min_rating and a["price_level"] <= max_price
    ]
    return {"city": city, "count": len(filtered), "activities": filtered}


# ---- Place Details ----

def get_place_id(name: str, city: str) -> Optional[str]:
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    res = requests.get(url, params={"query": f"{name} {city}", "key": GOOGLE_API_KEY}).json()
    results = res.get("results", [])
    if results:
        return results[0].get("place_id")
    return None

def get_place_details(place_id: str) -> dict:
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = ",".join([
        "name", "place_id", "formatted_address", "formatted_phone_number",
        "rating", "user_ratings_total", "price_level",
        "opening_hours", "website", "url",
        "editorial_summary",
        "types", "photos",
        "serves_beer", "serves_wine", "serves_brunch",
        "serves_breakfast", "serves_lunch", "serves_dinner",
        "reservable", "curbside_pickup", "delivery", "dine_in", "takeout",
    ])
    res = requests.get(url, params={"place_id": place_id, "fields": fields, "key": GOOGLE_API_KEY}).json()
    return res.get("result", {})

def estimate_cost(details: dict, category: str) -> dict:
    price_level = details.get("price_level")
    types = details.get("types", [])

    price_map = {0: "Free", 1: "$5–15 per person", 2: "$15–35 per person", 3: "$35–75 per person", 4: "$75+ per person"}
    label = price_map.get(price_level, "Cost varies")

    if any(t in types for t in ["museum", "art_gallery"]):
        label = "$10–25 admission" if price_level is None else label
    elif "amusement_park" in types:
        label = "$30–80 admission" if price_level is None else label
    elif "park" in types or "natural_feature" in types:
        label = "Free" if price_level is None else label
    elif "lodging" in types:
        label = "See website for rates"

    return {
        "price_level": price_level,
        "estimate": label,
        "currency": "USD",
    }

def build_reservation_links(details: dict) -> dict:
    name_encoded = requests.utils.quote(details.get("name", ""))
    google_maps_url = details.get("url", "")
    website = details.get("website", "")
    types = details.get("types", [])

    links = {}

    if website:
        links["website"] = website
    if google_maps_url:
        links["google_maps"] = google_maps_url

    if any(t in types for t in ["restaurant", "food", "cafe", "bar"]):
        links["opentable"] = f"https://www.opentable.com/s/?term={name_encoded}"
        links["yelp"] = f"https://www.yelp.com/search?find_desc={name_encoded}"

    if "lodging" in types:
        links["booking_com"] = f"https://www.booking.com/search.html?ss={name_encoded}"
        links["tripadvisor"] = f"https://www.tripadvisor.com/Search?q={name_encoded}"

    if any(t in types for t in ["tourist_attraction", "museum", "amusement_park", "zoo", "aquarium"]):
        links["tripadvisor"] = f"https://www.tripadvisor.com/Search?q={name_encoded}"
        links["viator"] = f"https://www.viator.com/search/{name_encoded}"

    return links

def build_description(details: dict) -> str:
    editorial = details.get("editorial_summary", {}).get("overview", "")
    if editorial:
        return editorial

    name = details.get("name", "this place")
    address = details.get("formatted_address", "")
    types = ", ".join(details.get("types", [])[:5])
    rating = details.get("rating", "")
    price_level = details.get("price_level")
    price_str = "$" * price_level if price_level else ""

    prompt = (
        f"Write a 2-3 sentence factual description of '{name}' located at {address}. "
        f"It is categorized as: {types}. "
        f"Rating: {rating}/5. Price level: {price_str or 'unknown'}. "
        "Describe what kind of place it is, what visitors can expect, and what it's known for. "
        "Do NOT mention specific people, reviews, or personal experiences. "
        "Keep it general, informative, and neutral like a travel guide entry."
    )

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.1-8b-instant", "max_tokens": 150, "messages": [{"role": "user", "content": prompt}]}
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return f"{name} is a {types.split(',')[0] if types else 'local spot'} located in {address}."

def build_menu_info(details: dict) -> Optional[dict]:
    types = details.get("types", [])
    is_food = any(t in types for t in ["restaurant", "food", "cafe", "bar", "bakery", "meal_takeaway"])
    if not is_food:
        return None

    menu: dict = {}
    website = details.get("website", "")
    name_encoded = requests.utils.quote(details.get("name", ""))

    if website:
        menu["likely_menu_url"] = website.rstrip("/") + "/menu"

    menu["yelp_menu"] = f"https://www.yelp.com/menu/{name_encoded.lower().replace('%20', '-')}"

    features = []
    for key, label in [
        ("serves_breakfast", "Breakfast"), ("serves_brunch", "Brunch"),
        ("serves_lunch", "Lunch"), ("serves_dinner", "Dinner"),
        ("serves_beer", "Beer"), ("serves_wine", "Wine"),
        ("dine_in", "Dine-in"), ("takeout", "Takeout"),
        ("delivery", "Delivery"), ("curbside_pickup", "Curbside pickup"),
        ("reservable", "Reservations accepted"),
    ]:
        if details.get(key):
            features.append(label)

    menu["features"] = features
    return menu


@app.get("/place-details")
def place_details(name: str, city: str, category: str = "tourist_attraction"):
    place_id = get_place_id(name, city)
    if not place_id:
        raise HTTPException(status_code=404, detail=f"Could not find '{name}' in {city}")

    details = get_place_details(place_id)
    if not details:
        raise HTTPException(status_code=404, detail="Place details not found")

    hours_raw = details.get("opening_hours", {})
    hours = {
        "open_now": hours_raw.get("open_now"),
        "weekday_text": hours_raw.get("weekday_text", []),
    }

    photos = [
        f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photoreference={p['photo_reference']}&key={GOOGLE_API_KEY}"
        for p in details.get("photos", [])[:5]
    ]

    return {
        "name": details.get("name"),
        "address": details.get("formatted_address"),
        "phone": details.get("formatted_phone_number"),
        "rating": details.get("rating"),
        "total_ratings": details.get("user_ratings_total"),
        "types": details.get("types", []),
        "description": build_description(details),
        "cost": estimate_cost(details, category),
        "hours": hours,
        "menu": build_menu_info(details),
        "links": build_reservation_links(details),
        "photos": photos,
    }


# ---- ELO helpers ----

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


# ---- ELO endpoints ----

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


# ---- Destination Suggestions ----

@app.get("/destinations")
def get_destinations(
    hometown: str,
    distance: str = "anywhere",
    season: str = "Flexible",
    duration: str = "",
):
    distance_context = {
        "nearby":        f"cities or regions within a 2-hour drive or short train ride from {hometown}",
        "domestic":      f"destinations within the same country as {hometown} — do NOT suggest international destinations",
        "international": f"international countries and cities — do NOT suggest anything in or near {hometown} or its country",
        "anywhere":      "anywhere in the world including exotic or off-the-beaten-path destinations",
    }

    scope = distance_context.get(distance, distance_context["anywhere"])

    prompt = f"""You are a world-class travel advisor. Recommend exactly 5 travel destinations for someone based in {hometown}.

Constraints:
- Distance scope: {scope}
- Travel season: {season}
- Trip duration: {duration or "flexible"}
- Choose destinations with the BEST weather and atmosphere for {season}
- Do NOT suggest {hometown} itself or the immediate surrounding region

You MUST respond with ONLY a raw JSON array. No markdown, no code fences, no explanation, no text before or after.

Example format:
[{{"city":"Paris","country":"France","weather":"Mild, 55°F, occasional rain","reason":"Spring blooms and fewer tourists make it magical in this season."}}]

Now give 5 destinations:"""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.1-8b-instant", "max_tokens": 600, "messages": [{"role": "user", "content": prompt}]}
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        print(f"Groq raw response: {raw[:200]}")

        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        raw = raw.strip()

        start = raw.find('[')
        end = raw.rfind(']')
        if start != -1 and end != -1:
            raw = raw[start:end+1]

        destinations = json.loads(raw)
        return {"destinations": destinations[:5]}

    except Exception as e:
        print(f"Destinations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/route")
def get_route(places: str, mode: str = "walking", city: str = ""):
    place_list = [p.strip() for p in places.split('|') if p.strip()]
    if len(place_list) < 2:
        return {"legs": [], "total_duration": 0, "total_distance": 0, "api_key": GOOGLE_API_KEY}

    origin = place_list[0]
    destination = place_list[-1]
    waypoints = place_list[1:-1]

    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "key": GOOGLE_API_KEY,
    }
    if waypoints:
        params["waypoints"] = "|".join(waypoints)

    try:
        res = requests.get(url, params=params).json()
        if res.get("status") != "OK":
            print(f"Google Directions error: {res.get('status')} - {res.get('error_message', '')}")
            raise HTTPException(status_code=400, detail=f"Directions API: {res.get('status')} - {res.get('error_message', '')}")

        legs = []
        total_duration = 0
        total_distance = 0
        for leg in res["routes"][0]["legs"]:
            dur = leg["duration"]["value"]
            dist = leg["distance"]["value"]
            total_duration += dur
            total_distance += dist
            legs.append({
                "from": leg["start_address"],
                "to": leg["end_address"],
                "duration_secs": dur,
                "duration_text": leg["duration"]["text"],
                "distance_meters": dist,
                "distance_text": leg["distance"]["text"],
            })

        return {
            "legs": legs,
            "total_duration": total_duration,
            "total_distance": total_distance,
            "api_key": GOOGLE_API_KEY,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Route error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)