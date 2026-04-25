# Task 4 Web App

This directory contains an isolated website implementation for **CS307 Project 1 Task 4**.

## Features

- Generate tickets for a date range using existing `flight` templates
- Search tickets by departure city, arrival city, and date
- Optional search filters for airline, departure time, and arrival time
- Passenger sign-in using existing passenger records
- Book economy or business tickets
- View passenger-owned orders only
- Cancel booked orders and delete cancelled orders

## Local Development

1. Copy `.env.example` to `.env`.
2. Keep the local PostgreSQL connection values or update them if needed.
3. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Run the web app:

   ```bash
   python3 app.py
   ```

5. Open `http://127.0.0.1:5000`.

## Docker Deployment

1. Copy `.env.example` to `.env`.
2. Set `SECRET_KEY`, `DOMAIN`, and either:
   - `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD`, or
   - `DATABASE_URL`
3. Start the stack:

   ```bash
   docker compose up -d --build
   ```

The compose file deploys:

- `web`: Flask + Gunicorn
- `caddy`: HTTPS reverse proxy for your domain

## Notes

- The app defaults to the **local** database used in this project.
- No cloud database settings are hard-coded.
- Ticket generation is capped at a **31-day range per run** to avoid accidental oversized inserts.
