# Globr

A full-stack travel-planning web application that helps first-time travelers decide where to go, budget their trip, and rank their experiences afterward — combining conversational AI, third-party data integration, and a custom ranking algorithm.

**Live application:** [globr-ten.vercel.app](https://globr-ten.vercel.app)

---

## Overview

Globr addresses a common problem: planning a trip is overwhelming for people who don't travel often. The application guides users through the entire journey — destination discovery, itinerary building, budgeting, and post-trip reflection — using AI assistance at each step and a personalized ranking system inspired by Beli.

The project was designed and built end-to-end, including frontend development, REST API design, database modeling, third-party API integration, and cloud deployment.

---

## Key Features

- **Conversational AI travel agent** — A chat-based agent that recommends destinations based on the user's home location, travel style, and season.
- **AI budget advisor** — An assistant that recommends a realistic, category-based budget for a destination using cost-of-living reasoning.
- **Itinerary and list planning** — Day-by-day itineraries or saved lists, populated with live place data (activities, restaurants, hotels) from the Google Places API.
- **Category budgeting** — User-defined budget categories with live total calculation.
- **ELO-based ranking system** — After a trip, users rank visited places through head-to-head comparisons; an ELO algorithm produces a personalized list scored out of 10.
- **Public profiles** — Users post rankings to a public `@username` profile, enabling a social, shareable layer.
- **Authentication and persistence** — Account-based sign-in with trips, plans, and rankings saved per user.

---

## Technical Highlights

- **Full-stack architecture** with a clear separation between a React single-page frontend and a FastAPI backend, communicating over a REST API.
- **Relational data modeling** in PostgreSQL (users, trips, saved places, ratings, posted rankings) using SQLAlchemy ORM.
- **Custom ELO rating algorithm** implemented to convert pairwise user preferences into ranked, scored lists.
- **Third-party API integration** with Google Places (location data) and Groq (LLM inference for the AI agents).
- **Cloud deployment and DevOps** across Vercel (frontend) and Railway (backend and managed PostgreSQL), including environment configuration, CORS, and Git-based continuous deploys.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React |
| Backend | FastAPI (Python) |
| Database | PostgreSQL + SQLAlchemy |
| AI / LLM | Groq |
| External data | Google Places API |
| Deployment | Vercel · Railway |

---

## Architecture

```
travel-app/
├── frontend/          # React single-page application (Vercel)
│   └── src/App.js
└── travel-app/        # FastAPI backend (Railway)
    ├── main.py        # REST API routes
    ├── models.py      # SQLAlchemy models
    ├── requirements.txt
    └── Procfile
```

---

## Running Locally

### Backend

```bash
cd travel-app
pip install -r requirements.txt
```

Create a `.env` file:

```
DATABASE_URL=your_postgres_connection_string
GROQ_API_KEY=your_groq_key
GOOGLE_PLACES_API_KEY=your_google_places_key
```

```bash
uvicorn main:app --reload
```

Interactive API documentation is available at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
```

Create a `.env` file:

```
REACT_APP_API_URL=http://localhost:8000
```

```bash
npm start
```

---

## Roadmap

- Follow system and a feed of connected users' rankings
- Notes and photo attachments on ranked trips
- Trip-vs-trip ranking for a personal trip leaderboard
- Budget recommendations grounded in live pricing data

---

## Author

Built by Anuva Kota as an end-to-end full-stack project spanning product design, API development, database architecture, and cloud deployment.
