import os
import random
import time
from datetime import datetime, timedelta
from decimal import Decimal
from concurrent.futures import ProcessPoolExecutor

import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "ecommerce",
    "autocommit": False,
}
BATCH_SIZE = 10_000


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def bulk_insert(conn, query, rows):
    if not rows:
        return 0

    total_inserted = 0
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start:start + BATCH_SIZE]
        if not chunk:
            continue
        cursor = conn.cursor()
        cursor.executemany(query, chunk)
        cursor.close()
        conn.commit()
        total_inserted += len(chunk)
    return total_inserted


def fetch_ids(conn, table_name, pk_column):
    cursor = conn.cursor()
    cursor.execute(f"SELECT {pk_column} FROM {table_name}")
    ids = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return ids


def seed_categories(conn, count=100):
    rows = []
    for i in range(1, count + 1):
        rows.append((f"Category {i}", f"Description for category {i}"))
    query = "INSERT INTO categories (name, description) VALUES (%s, %s)"
    bulk_insert(conn, query, rows)
    return fetch_ids(conn, "categories", "category_id")


def seed_warehouses(conn, count=10):
    rows = []
    for i in range(1, count + 1):
        rows.append((f"Warehouse {i}", f"Jakarta {i}"))
    query = "INSERT INTO warehouses (name, location) VALUES (%s, %s)"
    bulk_insert(conn, query, rows)
    return fetch_ids(conn, "warehouses", "warehouse_id")


def seed_products(conn, category_ids, warehouse_ids, count=5000):
    rows = []
    rng = random.Random(42)
    for i in range(1, count + 1):
        category_id = category_ids[rng.randrange(len(category_ids))]
        warehouse_id = warehouse_ids[rng.randrange(len(warehouse_ids))]
        rows.append(
            (
                category_id,
                warehouse_id,
                f"Product {i}",
                f"SKU-{i:06d}",
                Decimal(str(round(rng.uniform(10, 1000), 2))),
                rng.randint(0, 200),
                f"Description for product {i}",
            )
        )
    query = """
        INSERT INTO products
        (category_id, warehouse_id, name, sku, price, stock_quantity, description)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    bulk_insert(conn, query, rows)
    return fetch_ids(conn, "products", "product_id")


def seed_customers(conn, count=10_000):
    rows = []
    for i in range(1, count + 1):
        rows.append(
            (
                f"Customer {i}",
                f"customer{i}@example.com",
                f"0812{(i % 100000):05d}",
                f"Address {i}",
                f"City {i % 50}",
            )
        )
    query = """
        INSERT INTO customers (full_name, email, phone, address, city)
        VALUES (%s, %s, %s, %s, %s)
    """
    bulk_insert(conn, query, rows)
    return fetch_ids(conn, "customers", "customer_id")


def seed_orders(conn, customer_ids, count=100_000):
    rows = []
    rng = random.Random(7)
    for i in range(1, count + 1):
        customer_id = customer_ids[rng.randrange(len(customer_ids))]
        status = rng.choice(["pending", "processing", "shipped", "delivered", "cancelled"])
        total_amount = Decimal(str(round(rng.uniform(50, 5000), 2)))
        rows.append(
            (
                customer_id,
                status,
                total_amount,
                f"Shipping address {i}",
            )
        )
    query = """
        INSERT INTO orders (customer_id, status, total_amount, shipping_address)
        VALUES (%s, %s, %s, %s)
    """
    bulk_insert(conn, query, rows)
    return fetch_ids(conn, "orders", "order_id")


def seed_payments(conn, order_ids):
    rows = []
    rng = random.Random(11)
    for order_id in order_ids:
        method = rng.choice(["credit_card", "bank_transfer", "e_wallet", "cash_on_delivery"])
        status = rng.choice(["pending", "paid", "failed", "refunded"])
        amount = Decimal(str(round(rng.uniform(20, 5000), 2)))
        paid_at = None if status != "paid" else datetime.now() - timedelta(days=rng.randint(0, 30))
        rows.append((order_id, method, amount, status, paid_at))
    query = """
        INSERT INTO payments
        (order_id, payment_method, amount, status, paid_at)
        VALUES (%s, %s, %s, %s, %s)
    """
    bulk_insert(conn, query, rows)


def seed_shipments(conn, order_ids, warehouse_ids):
    rows = []
    rng = random.Random(13)
    for order_id in order_ids:
        warehouse_id = warehouse_ids[rng.randrange(len(warehouse_ids))]
        status = rng.choice(["pending", "packed", "shipped", "delivered", "returned"])
        tracking_number = f"TRK-{order_id:08d}"
        shipped_at = None if status in {"pending", "packed"} else datetime.now() - timedelta(days=rng.randint(0, 20))
        delivered_at = datetime.now() - timedelta(days=rng.randint(0, 10)) if status == "delivered" else None
        rows.append((order_id, warehouse_id, tracking_number, status, shipped_at, delivered_at))
    query = """
        INSERT INTO shipments
        (order_id, warehouse_id, tracking_number, status, shipped_at, delivered_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    bulk_insert(conn, query, rows)


def _insert_order_items_worker(worker_id, start_row, end_row, db_config, order_ids, product_ids):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    rng = random.Random(99 + worker_id)
    query = """
        INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal)
        VALUES (%s, %s, %s, %s, %s)
    """

    rows = []
    inserted = 0
    for _ in range(start_row, end_row):
        order_id = order_ids[rng.randrange(len(order_ids))]
        product_id = product_ids[rng.randrange(len(product_ids))]
        quantity = rng.randint(1, 5)
        unit_price = Decimal(str(round(rng.uniform(10, 1000), 2)))
        subtotal = Decimal(str(round(float(unit_price) * quantity, 2)))
        rows.append((order_id, product_id, quantity, unit_price, subtotal))

        if len(rows) >= BATCH_SIZE:
            cursor.executemany(query, rows)
            conn.commit()
            inserted += len(rows)
            rows.clear()

    if rows:
        cursor.executemany(query, rows)
        conn.commit()
        inserted += len(rows)

    cursor.close()
    conn.close()
    return inserted


def seed_order_items_parallel(order_ids, product_ids, total_rows=1_000_000, workers=None):
    if workers is None:
        workers = min(8, max(1, os.cpu_count() or 4))

    rows_per_worker = total_rows // workers
    remainder = total_rows % workers

    tasks = []
    start = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for worker_id in range(workers):
            current_rows = rows_per_worker + (1 if worker_id < remainder else 0)
            if current_rows <= 0:
                continue
            end = start + current_rows
            tasks.append(
                executor.submit(
                    _insert_order_items_worker,
                    worker_id,
                    start,
                    end,
                    DB_CONFIG,
                    order_ids,
                    product_ids,
                )
            )
            start = end

        for future in tasks:
            future.result()


def sync_sales_summary(conn, target_date=None):
    if target_date is None:
        target_date = datetime.now().date()

    query = """
        INSERT INTO sales_summary (customer_name, gudang_name, kategori_name, tanggal, total_sales)
        SELECT
            c.full_name AS customer_name,
            w.name AS gudang_name,
            cat.name AS kategori_name,
            DATE(o.order_date) AS tanggal,
            SUM(oi.quantity * p.price) AS total_sales
        FROM orders o
        JOIN customers c ON c.customer_id = o.customer_id
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN products p ON p.product_id = oi.product_id
        JOIN categories cat ON cat.category_id = p.category_id
        JOIN shipments s ON s.order_id = o.order_id
        JOIN warehouses w ON w.warehouse_id = s.warehouse_id
        JOIN payments pay ON pay.order_id = o.order_id
        WHERE pay.status = 'paid'
          AND DATE(o.order_date) = %s
        GROUP BY
            c.full_name,
            w.name,
            cat.name,
            DATE(o.order_date)
        ON DUPLICATE KEY UPDATE
            total_sales = VALUES(total_sales)
    """

    cursor = conn.cursor()
    cursor.execute(query, (target_date,))
    conn.commit()
    cursor.close()
    return cursor.rowcount


def main():
    conn = get_connection()
    try:
        print("Inserting categories...")
        category_ids = seed_categories(conn)

        print("Inserting warehouses...")
        warehouse_ids = seed_warehouses(conn)

        print("Inserting products...")
        product_ids = seed_products(conn, category_ids, warehouse_ids)

        print("Inserting customers...")
        customer_ids = seed_customers(conn)

        print("Inserting orders...")
        order_ids = seed_orders(conn, customer_ids)

        print("Inserting payments...")
        seed_payments(conn, order_ids)

        print("Inserting shipments...")
        seed_shipments(conn, order_ids, warehouse_ids)

        print("Inserting order items in parallel...")
        seed_order_items_parallel(order_ids, product_ids, total_rows=1_000_000, workers=4)

        print("Syncing daily sales summary...")
        rows_affected = sync_sales_summary(conn)
        print(f"Sales summary synced successfully. Rows affected: {rows_affected}")

        print("Seeder completed successfully.")
    except Error as exc:
        conn.rollback()
        print(f"MySQL error: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
