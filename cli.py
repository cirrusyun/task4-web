"""
CS307 Spring 2026 Project 1 - Task 4 CLI
Command-line interface for flight ticket CRUD operations.

Usage:
    python3 cli.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from db import (
    ValidationError,
    authenticate_passenger,
    book_ticket,
    cancel_order,
    delete_cancelled_order,
    generate_tickets,
    get_orders_for_passenger,
    get_search_options,
    search_tickets,
)

# ── helpers ───────────────────────────────────────────────────────────────────

_logged_in_passenger: dict | None = None


def _prompt(label: str, required: bool = True) -> str:
    while True:
        value = input(f"  {label}: ").strip()
        if value or not required:
            return value
        print("  [!] This field is required.")


def _separator():
    print("-" * 60)


def _header(title: str):
    _separator()
    print(f"  {title}")
    _separator()


# ── features ──────────────────────────────────────────────────────────────────

def do_generate_tickets():
    _header("Generate Tickets")
    print("  Generate flight instances and inventory for a date range.")
    print()
    start_date = _prompt("Start date (YYYY-MM-DD)")
    end_date   = _prompt("End date   (YYYY-MM-DD)")

    print()
    print("  Processing ...")
    try:
        result = generate_tickets(start_date, end_date)
    except ValidationError as e:
        print(f"  [!] Error: {e}")
        return

    print()
    print(f"  >> Generation complete for {result['days']} day(s):")
    print(f"     - Flight instances created : {result['created_instances']}")
    print(f"     - Inventory rows created   : {result['created_inventory_rows']}")


def do_search_flights():
    _header("Search Flights")
    print("  Required fields: departure city, arrival city, date.")
    print("  Optional fields: airline, departure after, arrival before.")
    print()

    options = get_search_options()
    cities = options["cities"]
    airlines = options["airlines"]

    print(f"  Available cities ({len(cities)} total, showing first 10):")
    print("  " + ", ".join(cities[:10]) + (" ..." if len(cities) > 10 else ""))
    print()

    departure_city  = _prompt("Departure city")
    arrival_city    = _prompt("Arrival city")
    flight_date     = _prompt("Date (YYYY-MM-DD)")
    airline         = _prompt("Airline code/name (Enter to skip)", required=False)
    departure_after = _prompt("Departure after HH:MM (Enter to skip)", required=False)
    arrival_before  = _prompt("Arrival before HH:MM (Enter to skip)", required=False)

    print()
    print("  Searching ...")
    try:
        results = search_tickets(
            departure_city, arrival_city, flight_date,
            airline, departure_after, arrival_before,
        )
    except ValidationError as e:
        print(f"  [!] Error: {e}")
        return

    print()
    if not results:
        print("  No flights found.")
        return

    print(f"  >> {len(results)} flight(s) found:\n")
    print(f"  {'#':<4} {'Flight':<10} {'Airline':<20} {'Dep':>6} {'Arr':>6} {'Eco Price':>10} {'Eco Seats':>10} {'Biz Price':>10} {'Biz Seats':>10}")
    print("  " + "-" * 90)
    for i, r in enumerate(results, 1):
        dep = str(r["departure_time"])[:5]
        arr = str(r["arrival_time"])[:5]
        if r["arrival_day_offset"]:
            arr += "+1"
        eco_price = f"{float(r['economy_price']):,.2f}"  if r["economy_price"]  else "—"
        eco_seats = str(r["economy_remain"])              if r["economy_remain"] is not None else "—"
        biz_price = f"{float(r['business_price']):,.2f}" if r["business_price"] is not None else "—"
        biz_seats = str(r["business_remain"])             if r["business_remain"] is not None else "—"
        print(f"  {i:<4} {r['flight_number']:<10} {r['airline_name']:<20} {dep:>6} {arr:>6} {eco_price:>10} {eco_seats:>10} {biz_price:>10} {biz_seats:>10}")

    return results


def do_book_ticket(results: list | None = None):
    global _logged_in_passenger

    if _logged_in_passenger is None:
        print()
        print("  [!] You must be signed in to book a ticket.")
        do_login()
        if _logged_in_passenger is None:
            return

    if results is None:
        results = do_search_flights()
        if not results:
            return

    print()
    flight_no = _prompt("Enter flight # to book (number from the list above)")
    try:
        idx = int(flight_no) - 1
        flight = results[idx]
    except (ValueError, IndexError):
        print("  [!] Invalid selection.")
        return

    print()
    print(f"  Flight : {flight['flight_number']}  {flight['source_city']} → {flight['destination_city']}")
    print(f"  Date   : {flight['flight_date']}")
    print(f"  Economy: {float(flight['economy_price']):,.2f}  (seats: {flight['economy_remain']})")
    print(f"  Business: {float(flight['business_price']):,.2f}  (seats: {flight['business_remain']})")
    print()

    cabin = _prompt("Cabin class (economy / business)")
    cabin = cabin.lower()
    if cabin in ("economy", "e"):
        inv_id = flight["economy_inventory_id"]
    elif cabin in ("business", "b"):
        inv_id = flight["business_inventory_id"]
    else:
        print("  [!] Invalid cabin class.")
        return

    print()
    print("  Booking ...")
    try:
        result = book_ticket(_logged_in_passenger["passenger_id"], inv_id)
    except ValidationError as e:
        print(f"  [!] Error: {e}")
        return

    print()
    print(f"  >> Order #{result['order_id']} confirmed!")
    print(f"     Cabin     : {result['cabin_name']}")
    print(f"     Paid price: {float(result['paid_price']):,.2f}")


def do_manage_orders():
    global _logged_in_passenger

    if _logged_in_passenger is None:
        print()
        print("  [!] You must be signed in to manage orders.")
        do_login()
        if _logged_in_passenger is None:
            return

    while True:
        _header(f"Order Management  [{_logged_in_passenger['passenger_name']}]")
        print("  1. View my orders")
        print("  2. Cancel an order")
        print("  3. Delete a cancelled order")
        print("  0. Back to main menu")
        print()
        choice = _prompt(">> Select")

        if choice == "1":
            _show_orders()
        elif choice == "2":
            _show_orders()
            print()
            order_id = _prompt("Enter Order ID to cancel")
            try:
                cancel_order(_logged_in_passenger["passenger_id"], int(order_id))
                print(f"  >> Order #{order_id} cancelled and seat inventory restored.")
            except (ValidationError, ValueError) as e:
                print(f"  [!] Error: {e}")
        elif choice == "3":
            _show_orders()
            print()
            order_id = _prompt("Enter Order ID to delete")
            try:
                delete_cancelled_order(_logged_in_passenger["passenger_id"], int(order_id))
                print(f"  >> Order #{order_id} permanently deleted.")
            except (ValidationError, ValueError) as e:
                print(f"  [!] Error: {e}")
        elif choice == "0":
            break
        else:
            print("  [!] Invalid option.")


def _show_orders():
    orders = get_orders_for_passenger(_logged_in_passenger["passenger_id"])
    print()
    if not orders:
        print("  No orders found.")
        return
    print(f"  {'ID':<8} {'Status':<12} {'Flight':<10} {'Date':<12} {'Cabin':<10} {'Price':>10}  Route")
    print("  " + "-" * 80)
    for o in orders:
        route = f"{o['source_city']} → {o['destination_city']}"
        price = f"{float(o['paid_price']):,.2f}"
        print(f"  {o['order_id']:<8} {o['order_status']:<12} {o['flight_number']:<10} {str(o['flight_date']):<12} {o['cabin_name']:<10} {price:>10}  {route}")


def do_login():
    global _logged_in_passenger
    _header("Sign In")
    name   = _prompt("Passenger name")
    mobile = _prompt("Mobile number")
    try:
        _logged_in_passenger = dict(authenticate_passenger(name, mobile))
        print(f"  >> Signed in as {_logged_in_passenger['passenger_name']}.")
    except ValidationError as e:
        print(f"  [!] {e}")


def do_logout():
    global _logged_in_passenger
    if _logged_in_passenger:
        print(f"  >> Signed out from {_logged_in_passenger['passenger_name']}.")
        _logged_in_passenger = None
    else:
        print("  [!] Not signed in.")


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 60)
    print("   SkyLedger - Flight Ticket Management System (CLI)")
    print("=" * 60)

    while True:
        print()
        user_label = f"[{_logged_in_passenger['passenger_name']}]" if _logged_in_passenger else "[Guest]"
        print(f"  Logged in as: {user_label}")
        print()
        print("  Please select an operation:")
        print("  1. Generate tickets")
        print("  2. Search flights")
        print("  3. Book a ticket")
        print("  4. Manage orders")
        print("  5. Sign in / Switch user")
        print("  6. Sign out")
        print("  0. Exit")
        print()

        choice = _prompt(">> Input")

        if choice == "1":
            do_generate_tickets()
        elif choice == "2":
            do_search_flights()
        elif choice == "3":
            results = do_search_flights()
            if results:
                print()
                book = _prompt("Book a ticket from results? (y/n)", required=False)
                if book.lower() == "y":
                    do_book_ticket(results)
        elif choice == "4":
            do_manage_orders()
        elif choice == "5":
            do_login()
        elif choice == "6":
            do_logout()
        elif choice == "0":
            print()
            print("  Goodbye!")
            sys.exit(0)
        else:
            print("  [!] Invalid option, please try again.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Goodbye!")
        sys.exit(0)
