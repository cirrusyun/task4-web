from __future__ import annotations

import os
from datetime import date

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()


class ValidationError(Exception):
    pass


def _dsn() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    return " ".join(
        [
            f"host={os.getenv('PGHOST', 'localhost')}",
            f"port={os.getenv('PGPORT', '5432')}",
            f"dbname={os.getenv('PGDATABASE', 'cs307_project')}",
            f"user={os.getenv('PGUSER', 'cs307')}",
            f"password={os.getenv('PGPASSWORD', 'cs307')}",
        ]
    )


def _connect():
    return psycopg2.connect(_dsn(), cursor_factory=RealDictCursor)


def get_dashboard_stats():
    sql = """
        SELECT
            (SELECT COUNT(*) FROM flight) AS flights,
            (SELECT COUNT(*) FROM flight_instance) AS flight_instances,
            (SELECT COUNT(*) FROM ticket_inventory) AS inventory_rows,
            (SELECT COUNT(*) FROM passenger) AS passengers,
            (SELECT COUNT(*) FROM ticket_order WHERE order_status = 'booked') AS active_orders,
            (SELECT MIN(flight_date) FROM flight_instance) AS first_date,
            (SELECT MAX(flight_date) FROM flight_instance) AS last_date
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()


def get_search_options():
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT city_name FROM airport ORDER BY city_name")
        cities = [row["city_name"] for row in cur.fetchall()]

        cur.execute(
            """
            SELECT airline_code, airline_name
            FROM airline
            ORDER BY airline_code
            """
        )
        airlines = cur.fetchall()

    return {"cities": cities, "airlines": airlines}


def authenticate_passenger(passenger_name: str, mobile_number: str):
    sql = """
        SELECT passenger_id, passenger_name, mobile_number
        FROM passenger
        WHERE mobile_number = %s
          AND LOWER(passenger_name) = LOWER(%s)
        LIMIT 1
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (mobile_number, passenger_name))
        passenger = cur.fetchone()

    if passenger is None:
        raise ValidationError("Passenger name and mobile number do not match our records.")

    return passenger


def search_tickets(
    departure_city: str,
    arrival_city: str,
    flight_date: str,
    airline: str = "",
    departure_after: str = "",
    arrival_before: str = "",
    arrival_next_day: bool = False,
):
    _parse_date(flight_date)
    departure_after = departure_after or None
    arrival_before = arrival_before or None
    airline = airline or None

    if departure_after:
        _parse_time(departure_after)
    if arrival_before:
        _parse_time(arrival_before)

    sql = """
        SELECT
            fi.flight_instance_id,
            fi.flight_date,
            f.flight_number,
            al.airline_code,
            al.airline_name,
            src.airport_name AS source_airport_name,
            src.city_name AS source_city,
            src.iata_code AS source_iata_code,
            dst.airport_name AS destination_airport_name,
            dst.city_name AS destination_city,
            dst.iata_code AS destination_iata_code,
            f.departure_time,
            f.arrival_time,
            f.arrival_day_offset,
            MAX(CASE WHEN ct.cabin_name = 'Economy' THEN ti.ticket_inventory_id END) AS economy_inventory_id,
            MAX(CASE WHEN ct.cabin_name = 'Economy' THEN ti.price END) AS economy_price,
            MAX(CASE WHEN ct.cabin_name = 'Economy' THEN ti.remain_count END) AS economy_remain,
            MAX(CASE WHEN ct.cabin_name = 'Business' THEN ti.ticket_inventory_id END) AS business_inventory_id,
            MAX(CASE WHEN ct.cabin_name = 'Business' THEN ti.price END) AS business_price,
            MAX(CASE WHEN ct.cabin_name = 'Business' THEN ti.remain_count END) AS business_remain
        FROM flight_instance fi
        JOIN flight f ON fi.flight_id = f.flight_id
        JOIN airline al ON f.airline_id = al.airline_id
        JOIN airport src ON f.source_airport_id = src.airport_id
        JOIN airport dst ON f.destination_airport_id = dst.airport_id
        JOIN ticket_inventory ti ON ti.flight_instance_id = fi.flight_instance_id
        JOIN cabin_type ct ON ct.cabin_type_id = ti.cabin_type_id
        WHERE LOWER(src.city_name) = LOWER(%s)
          AND LOWER(dst.city_name) = LOWER(%s)
          AND fi.flight_date = %s
          AND (
                %s IS NULL
                OR LOWER(al.airline_code) = LOWER(%s)
                OR LOWER(al.airline_name) = LOWER(%s)
              )
          AND (%s IS NULL OR f.departure_time >= %s)
          AND (%s IS NULL OR (f.arrival_day_offset = %s AND f.arrival_time <= %s))
        GROUP BY
            fi.flight_instance_id,
            fi.flight_date,
            f.flight_number,
            al.airline_code,
            al.airline_name,
            src.airport_name,
            src.city_name,
            src.iata_code,
            dst.airport_name,
            dst.city_name,
            dst.iata_code,
            f.departure_time,
            f.arrival_time,
            f.arrival_day_offset
        ORDER BY
            MAX(CASE WHEN ct.cabin_name = 'Economy' THEN ti.price END) ASC NULLS LAST,
            f.departure_time ASC,
            f.flight_number ASC
    """

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            (
                departure_city,
                arrival_city,
                flight_date,
                airline,
                airline,
                airline,
                departure_after,
                departure_after,
                arrival_before,
                1 if arrival_next_day else 0,
                arrival_before,
            ),
        )
        return cur.fetchall()


def generate_tickets(start_date: str, end_date: str):
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if end < start:
        raise ValidationError("End date must not be earlier than start date.")

    days = (end - start).days + 1
    if days > 31:
        raise ValidationError("Generation is limited to a 31-day window per run.")

    instance_sql = """
        WITH inserted AS (
            INSERT INTO flight_instance (flight_date, flight_id)
            SELECT gs::date, f.flight_id
            FROM flight AS f
            CROSS JOIN generate_series(%s::date, %s::date, INTERVAL '1 day') AS gs
            ON CONFLICT (flight_id, flight_date) DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*) AS created_instances
        FROM inserted
    """

    inventory_sql = """
        WITH template_inventory AS (
            SELECT DISTINCT ON (fi.flight_id, ti.cabin_type_id)
                fi.flight_id,
                ti.cabin_type_id,
                ti.price,
                ti.remain_count
            FROM flight_instance fi
            JOIN ticket_inventory ti ON ti.flight_instance_id = fi.flight_instance_id
            ORDER BY
                fi.flight_id,
                ti.cabin_type_id,
                fi.flight_date DESC,
                fi.flight_instance_id DESC
        ),
        target_instances AS (
            SELECT flight_instance_id, flight_id
            FROM flight_instance
            WHERE flight_date BETWEEN %s AND %s
        ),
        inserted AS (
            INSERT INTO ticket_inventory (price, remain_count, flight_instance_id, cabin_type_id)
            SELECT
                tpl.price,
                tpl.remain_count,
                tgt.flight_instance_id,
                tpl.cabin_type_id
            FROM target_instances AS tgt
            JOIN template_inventory AS tpl
              ON tpl.flight_id = tgt.flight_id
            ON CONFLICT (flight_instance_id, cabin_type_id) DO NOTHING
            RETURNING 1
        )
        SELECT COUNT(*) AS created_inventory_rows
        FROM inserted
    """

    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS flight_count FROM flight")
        flight_count = cur.fetchone()["flight_count"]
        if flight_count == 0:
            raise ValidationError("No flight templates are available yet. Import data first.")

        cur.execute(instance_sql, (start, end))
        created_instances = cur.fetchone()["created_instances"]

        cur.execute(inventory_sql, (start, end))
        created_inventory_rows = cur.fetchone()["created_inventory_rows"]

        conn.commit()

    return {
        "days": days,
        "created_instances": created_instances,
        "created_inventory_rows": created_inventory_rows,
    }


def get_contacts(passenger_id: int):
    sql = """
        SELECT contact_id, contact_name, mobile_number
        FROM contact
        WHERE passenger_id = %s
        ORDER BY contact_name
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (passenger_id,))
        return cur.fetchall()


def add_contact(passenger_id: int, contact_name: str, mobile_number: str):
    if not contact_name or not mobile_number:
        raise ValidationError("Contact name and mobile number are required.")
    sql = """
        INSERT INTO contact (contact_name, mobile_number, passenger_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (passenger_id, mobile_number) DO NOTHING
        RETURNING contact_id
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (contact_name, mobile_number, passenger_id))
        result = cur.fetchone()
        if result is None:
            raise ValidationError("A contact with this mobile number already exists.")
        conn.commit()
        return result["contact_id"]


def delete_contact(passenger_id: int, contact_id: int):
    sql = """
        DELETE FROM contact
        WHERE contact_id = %s AND passenger_id = %s
        RETURNING contact_id
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (contact_id, passenger_id))
        if cur.fetchone() is None:
            raise ValidationError("Contact not found.")
        conn.commit()


def book_ticket(passenger_id: int, ticket_inventory_id: int, contact_id: int | None = None):
    select_sql = """
        SELECT
            ti.ticket_inventory_id,
            ti.price,
            ti.remain_count,
            ct.cabin_name
        FROM ticket_inventory ti
        JOIN cabin_type ct ON ct.cabin_type_id = ti.cabin_type_id
        WHERE ti.ticket_inventory_id = %s
        FOR UPDATE
    """
    insert_sql = """
        INSERT INTO ticket_order (paid_price, passenger_id, ticket_inventory_id, contact_id)
        VALUES (%s, %s, %s, %s)
        RETURNING order_id
    """
    update_sql = """
        UPDATE ticket_inventory
        SET remain_count = remain_count - 1
        WHERE ticket_inventory_id = %s
    """

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(select_sql, (ticket_inventory_id,))
        inventory = cur.fetchone()
        if inventory is None:
            raise ValidationError("That fare option no longer exists.")
        if inventory["remain_count"] <= 0:
            raise ValidationError("That cabin is sold out.")

        cur.execute(insert_sql, (inventory["price"], passenger_id, ticket_inventory_id, contact_id))
        order_id = cur.fetchone()["order_id"]
        cur.execute(update_sql, (ticket_inventory_id,))
        conn.commit()

    return {
        "order_id": order_id,
        "cabin_name": inventory["cabin_name"],
        "paid_price": inventory["price"],
    }


def get_orders_for_passenger(passenger_id: int):
    sql = """
        SELECT
            o.order_id,
            o.booked_at,
            o.paid_price,
            o.order_status,
            ct.cabin_name,
            fi.flight_date,
            f.flight_number,
            f.departure_time,
            f.arrival_time,
            f.arrival_day_offset,
            src.city_name AS source_city,
            src.airport_name AS source_airport_name,
            dst.city_name AS destination_city,
            dst.airport_name AS destination_airport_name,
            al.airline_name,
            c.contact_name,
            c.mobile_number AS contact_mobile
        FROM ticket_order o
        JOIN ticket_inventory ti ON ti.ticket_inventory_id = o.ticket_inventory_id
        JOIN cabin_type ct ON ct.cabin_type_id = ti.cabin_type_id
        JOIN flight_instance fi ON fi.flight_instance_id = ti.flight_instance_id
        JOIN flight f ON f.flight_id = fi.flight_id
        JOIN airline al ON al.airline_id = f.airline_id
        JOIN airport src ON src.airport_id = f.source_airport_id
        JOIN airport dst ON dst.airport_id = f.destination_airport_id
        LEFT JOIN contact c ON c.contact_id = o.contact_id
        WHERE o.passenger_id = %s
        ORDER BY o.booked_at DESC, o.order_id DESC
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (passenger_id,))
        return cur.fetchall()


def cancel_order(passenger_id: int, order_id: int):
    lookup_sql = """
        SELECT order_id, order_status, ticket_inventory_id
        FROM ticket_order
        WHERE order_id = %s
          AND passenger_id = %s
        FOR UPDATE
    """
    cancel_sql = """
        UPDATE ticket_order
        SET order_status = 'cancelled'
        WHERE order_id = %s
    """
    restore_sql = """
        UPDATE ticket_inventory
        SET remain_count = remain_count + 1
        WHERE ticket_inventory_id = %s
    """

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(lookup_sql, (order_id, passenger_id))
        order = cur.fetchone()
        if order is None:
            raise ValidationError("Order not found for the signed-in passenger.")
        if order["order_status"] != "booked":
            raise ValidationError("Only booked orders can be cancelled.")

        cur.execute(cancel_sql, (order_id,))
        cur.execute(restore_sql, (order["ticket_inventory_id"],))
        conn.commit()


def delete_cancelled_order(passenger_id: int, order_id: int):
    sql = """
        DELETE FROM ticket_order
        WHERE order_id = %s
          AND passenger_id = %s
          AND order_status = 'cancelled'
        RETURNING order_id
    """
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (order_id, passenger_id))
        deleted = cur.fetchone()
        if deleted is None:
            raise ValidationError("Only cancelled orders can be deleted.")
        conn.commit()


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("Dates must use the YYYY-MM-DD format.") from exc


def _parse_time(value: str) -> str:
    if len(value) != 5 or value[2] != ":":
        raise ValidationError("Time filters must use the HH:MM format.")
    return value
