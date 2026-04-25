from __future__ import annotations

import os
from datetime import date, time
from functools import wraps
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from db import (
    ValidationError,
    authenticate_passenger,
    book_ticket,
    cancel_order,
    delete_cancelled_order,
    generate_tickets,
    get_dashboard_stats,
    get_orders_for_passenger,
    get_search_options,
    search_tickets,
)

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-before-deploy")
    app.config["APP_NAME"] = os.getenv("APP_NAME", "SkyLedger")

    @app.template_filter("clock")
    def clock_filter(value: time | None) -> str:
        if value is None:
            return "—"
        return value.strftime("%H:%M")

    @app.template_filter("money")
    def money_filter(value) -> str:
        if value is None:
            return "—"
        return f"{float(value):,.2f}"

    @app.template_filter("date_label")
    def date_label_filter(value: date | None) -> str:
        if value is None:
            return "—"
        return value.strftime("%Y-%m-%d")

    @app.context_processor
    def inject_globals():
        return {"app_name": app.config["APP_NAME"]}

    @app.before_request
    def load_user():
        if session.get("passenger_id"):
            g.user = {
                "passenger_id": session["passenger_id"],
                "passenger_name": session.get("passenger_name"),
                "mobile_number": session.get("mobile_number"),
            }
        else:
            g.user = None

    @app.route("/")
    def dashboard():
        stats = get_dashboard_stats()
        return render_template("dashboard.html", stats=stats)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        next_url = request.values.get("next") or url_for("dashboard")

        if request.method == "POST":
            passenger_name = request.form.get("passenger_name", "").strip()
            mobile_number = request.form.get("mobile_number", "").strip()

            if not passenger_name or not mobile_number:
                flash("Passenger name and mobile number are required.", "error")
                return render_template("login.html", next_url=next_url)

            try:
                passenger = authenticate_passenger(passenger_name, mobile_number)
            except ValidationError as exc:
                flash(str(exc), "error")
                return render_template("login.html", next_url=next_url)

            session.clear()
            session["passenger_id"] = passenger["passenger_id"]
            session["passenger_name"] = passenger["passenger_name"]
            session["mobile_number"] = passenger["mobile_number"]
            flash(f"Signed in as {passenger['passenger_name']}.", "success")
            return redirect(_safe_redirect_target(next_url, "dashboard"))

        return render_template("login.html", next_url=next_url)

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "info")
        return redirect(url_for("dashboard"))

    @app.route("/search")
    def search():
        filters = {
            "departure_city": request.args.get("departure_city", "").strip(),
            "arrival_city": request.args.get("arrival_city", "").strip(),
            "flight_date": request.args.get("flight_date", "").strip(),
            "airline": request.args.get("airline", "").strip(),
            "departure_after": request.args.get("departure_after", "").strip(),
            "arrival_before": request.args.get("arrival_before", "").strip(),
        }
        arrival_next_day = request.args.get("arrival_next_day") == "1"

        options = get_search_options()
        results = []
        search_performed = any(filters.values())

        if search_performed:
            missing_required = [
                label
                for key, label in (
                    ("departure_city", "departure city"),
                    ("arrival_city", "arrival city"),
                    ("flight_date", "date"),
                )
                if not filters[key]
            ]

            if missing_required:
                flash(
                    "Search requires: " + ", ".join(missing_required) + ".",
                    "warning",
                )
            else:
                try:
                    results = search_tickets(**filters, arrival_next_day=arrival_next_day)
                except ValidationError as exc:
                    flash(str(exc), "error")

        return render_template(
            "search.html",
            filters=filters,
            arrival_next_day=arrival_next_day,
            results=results,
            cities=options["cities"],
            airlines=options["airlines"],
            search_performed=search_performed,
        )

    @app.post("/generate")
    def generate():
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()

        try:
            summary = generate_tickets(start_date, end_date)
        except ValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("dashboard"))

        flash(
            (
                f"Ticket generation complete for {summary['days']} day(s): "
                f"{summary['created_instances']} new flight instances and "
                f"{summary['created_inventory_rows']} new inventory rows."
            ),
            "success",
        )
        return redirect(url_for("dashboard"))

    @app.post("/book")
    @login_required
    def book():
        ticket_inventory_id = request.form.get("ticket_inventory_id", type=int)
        return_to = request.form.get("return_to") or url_for("search")

        if not ticket_inventory_id:
            flash("Missing ticket selection.", "error")
            return redirect(_safe_redirect_target(return_to, "search"))

        try:
            booking = book_ticket(g.user["passenger_id"], ticket_inventory_id)
        except ValidationError as exc:
            flash(str(exc), "error")
            return redirect(_safe_redirect_target(return_to, "search"))

        flash(
            (
                f"Order #{booking['order_id']} confirmed: "
                f"{booking['cabin_name']} cabin at {money_filter(booking['paid_price'])}."
            ),
            "success",
        )
        return redirect(url_for("orders"))

    @app.route("/orders")
    @login_required
    def orders():
        orders_data = get_orders_for_passenger(g.user["passenger_id"])
        return render_template("orders.html", orders=orders_data)

    @app.post("/orders/<int:order_id>/cancel")
    @login_required
    def cancel(order_id: int):
        try:
            cancel_order(g.user["passenger_id"], order_id)
        except ValidationError as exc:
            flash(str(exc), "error")
        else:
            flash(f"Order #{order_id} was cancelled and seat inventory was restored.", "success")
        return redirect(url_for("orders"))

    @app.post("/orders/<int:order_id>/delete")
    @login_required
    def delete_order(order_id: int):
        try:
            delete_cancelled_order(g.user["passenger_id"], order_id)
        except ValidationError as exc:
            flash(str(exc), "error")
        else:
            flash(f"Cancelled order #{order_id} was permanently deleted.", "info")
        return redirect(url_for("orders"))

    return app


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("passenger_id"):
            flash("Please sign in before booking or managing orders.", "warning")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def _safe_redirect_target(target: str | None, fallback_endpoint: str) -> str:
    if not target:
        return url_for(fallback_endpoint)

    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return url_for(fallback_endpoint)

    return target


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
