import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "elit21.db"
UPLOADS_PATH = Path(__file__).resolve().parent / "uploads"

CURRENCY_OPTIONS = {
    "CAD": {"name": "Dollar canadien", "symbol": "$ CA"},
    "USD": {"name": "Dollar américain", "symbol": "$ US"},
    "EUR": {"name": "Euro", "symbol": "€"},
    "CNY": {"name": "Yuan chinois", "symbol": "¥"},
    "JPY": {"name": "Yen japonais", "symbol": "¥"},
    "GBP": {"name": "Livre sterling", "symbol": "£"},
}

DEFAULT_SITE_SETTINGS = {
    "site_name": "ELIT21",
    "site_name_font": "Segoe UI",
    "header_bg_color": "#0c1f4c",
    "header_secondary_color": "#1f3a7a",
    "page_bg_color": "#f5f7fb",
    "promo_badge_text": "Marketplace premium",
    "promo_title_text": "Le marché ELIT21 pour des achats d'exception.",
    "promo_description_text": (
        "Découvrez une expérience d'achat fluide, sécurisée et inspirante. ELIT21 propose un "
        "espace de vente moderne prêt à accueillir vos articles premium, avec paiement PayPal."
    ),
    "promo_card_1_title": "PayPal sécurisé",
    "promo_card_1_value": "24/7",
    "promo_card_2_title": "Support VIP",
    "promo_card_2_value": "Premium",
    "promo_card_3_title": "Trust score",
    "promo_card_3_value": "98%",
    "ad_bg_color": "#ffffff",
    "ad_text_color": "#0c1f4c",
    "ad_button_color": "#1f3a7a",
    "currency_code": "CAD",
    "shipping_fee": "9.99",
    "language_code": "fr",
}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS site_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            site_name TEXT NOT NULL,
            site_name_font TEXT NOT NULL,
            header_bg_color TEXT NOT NULL,
            header_secondary_color TEXT NOT NULL,
            page_bg_color TEXT NOT NULL,
            promo_badge_text TEXT NOT NULL,
            promo_title_text TEXT NOT NULL,
            promo_description_text TEXT NOT NULL,
            promo_card_1_title TEXT NOT NULL,
            promo_card_1_value TEXT NOT NULL,
            promo_card_2_title TEXT NOT NULL,
            promo_card_2_value TEXT NOT NULL,
            promo_card_3_title TEXT NOT NULL,
            promo_card_3_value TEXT NOT NULL,
            ad_bg_color TEXT NOT NULL,
            ad_text_color TEXT NOT NULL,
            ad_button_color TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        "SELECT id FROM site_settings WHERE id = 1"
    )
    existing_settings = cursor.fetchone()
    if not existing_settings:
        cursor.execute(
            """
            INSERT INTO site_settings (
                id, site_name, site_name_font, header_bg_color, header_secondary_color,
                page_bg_color, promo_badge_text, promo_title_text, promo_description_text,
                promo_card_1_title, promo_card_1_value, promo_card_2_title, promo_card_2_value,
                promo_card_3_title, promo_card_3_value, ad_bg_color, ad_text_color, ad_button_color
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                DEFAULT_SITE_SETTINGS["site_name"],
                DEFAULT_SITE_SETTINGS["site_name_font"],
                DEFAULT_SITE_SETTINGS["header_bg_color"],
                DEFAULT_SITE_SETTINGS["header_secondary_color"],
                DEFAULT_SITE_SETTINGS["page_bg_color"],
                DEFAULT_SITE_SETTINGS["promo_badge_text"],
                DEFAULT_SITE_SETTINGS["promo_title_text"],
                DEFAULT_SITE_SETTINGS["promo_description_text"],
                DEFAULT_SITE_SETTINGS["promo_card_1_title"],
                DEFAULT_SITE_SETTINGS["promo_card_1_value"],
                DEFAULT_SITE_SETTINGS["promo_card_2_title"],
                DEFAULT_SITE_SETTINGS["promo_card_2_value"],
                DEFAULT_SITE_SETTINGS["promo_card_3_title"],
                DEFAULT_SITE_SETTINGS["promo_card_3_value"],
                DEFAULT_SITE_SETTINGS["ad_bg_color"],
                DEFAULT_SITE_SETTINGS["ad_text_color"],
                DEFAULT_SITE_SETTINGS["ad_button_color"],
            ),
        )

    cursor.execute("PRAGMA table_info(site_settings)")
    setting_columns = {row[1] for row in cursor.fetchall()}
    for column_name, default_value in DEFAULT_SITE_SETTINGS.items():
        if column_name not in setting_columns:
            escaped_default = str(default_value).replace("'", "''")
            cursor.execute(
                f"ALTER TABLE site_settings ADD COLUMN {column_name} TEXT NOT NULL DEFAULT '{escaped_default}'",
            )

    cursor.execute(
        "UPDATE site_settings SET "
        + ", ".join(
            [f"{column_name} = COALESCE({column_name}, ?)" for column_name in DEFAULT_SITE_SETTINGS]
        )
        + " WHERE id = 1",
        tuple(DEFAULT_SITE_SETTINGS.values()),
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            price REAL NOT NULL,
            status TEXT NOT NULL,
            stock INTEGER NOT NULL,
            color TEXT,
            size TEXT,
            category TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS product_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            image_blob BLOB,
            image_path TEXT,
            mime_type TEXT,
            position INTEGER NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("PRAGMA table_info(product_images)")
    product_image_columns = {row[1] for row in cursor.fetchall()}
    if "image_path" not in product_image_columns:
        cursor.execute("ALTER TABLE product_images ADD COLUMN image_path TEXT")
    if "mime_type" not in product_image_columns:
        cursor.execute("ALTER TABLE product_images ADD COLUMN mime_type TEXT")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            customer_address TEXT NOT NULL,
            status TEXT NOT NULL,
            payment_status TEXT NOT NULL,
            shipping_fee REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute("PRAGMA table_info(orders)")
    columns = {row[1] for row in cursor.fetchall()}
    if "shipping_fee" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN shipping_fee REAL NOT NULL DEFAULT 0")

    cursor.execute("PRAGMA table_info(products)")
    product_columns = {row[1] for row in cursor.fetchall()}
    for column_name in ("color", "size", "category"):
        if column_name not in product_columns:
            cursor.execute(f"ALTER TABLE products ADD COLUMN {column_name} TEXT")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            color TEXT,
            size TEXT,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS product_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            color TEXT NOT NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            UNIQUE(product_id, color, size),
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            completed_at TEXT NOT NULL,
            total REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            event TEXT NOT NULL,
            request_payload TEXT,
            response_payload TEXT,
            status TEXT NOT NULL,
            error_message TEXT,
            retries INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE SET NULL
        )
        """
    )

    cursor.execute("PRAGMA table_info(order_items)")
    order_item_columns = {row[1] for row in cursor.fetchall()}
    for column_name in ("color", "size"):
        if column_name not in order_item_columns:
            cursor.execute(f"ALTER TABLE order_items ADD COLUMN {column_name} TEXT")

    conn.commit()
    conn.close()
    UPLOADS_PATH.mkdir(parents=True, exist_ok=True)


def get_site_settings() -> dict[str, str]:
    init_db()
    conn = get_connection()
    row = conn.execute("SELECT * FROM site_settings WHERE id = 1").fetchone()
    conn.close()
    settings = dict(DEFAULT_SITE_SETTINGS)
    if row:
        settings.update({key: str(row[key]) for key in settings.keys() if row[key] is not None})
    return settings


def seed_defaults():
    """No default products to keep the storefront empty."""
    return
