import sqlite3
from datetime import datetime
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

PAGE_CUSTOMIZATION_KEYS = (
    "cart",
    "checkout",
    "checkout_success",
    "experience",
    "index",
    "login",
    "policy",
    "product",
    "register",
    "seo",
)

for page_key in PAGE_CUSTOMIZATION_KEYS:
    DEFAULT_SITE_SETTINGS[f"{page_key}_title_text"] = ""
    DEFAULT_SITE_SETTINGS[f"{page_key}_subtitle_text"] = ""
    DEFAULT_SITE_SETTINGS[f"{page_key}_body_text"] = ""
    DEFAULT_SITE_SETTINGS[f"{page_key}_accent_color"] = "#1f3a7a"
    DEFAULT_SITE_SETTINGS[f"{page_key}_text_align"] = "left"
    DEFAULT_SITE_SETTINGS[f"{page_key}_section_title_text"] = ""
    DEFAULT_SITE_SETTINGS[f"{page_key}_section_subtitle_text"] = ""
    DEFAULT_SITE_SETTINGS[f"{page_key}_section_body_text"] = ""
    DEFAULT_SITE_SETTINGS[f"{page_key}_section_bg_color"] = "#ffffff"
    DEFAULT_SITE_SETTINGS[f"{page_key}_section_text_color"] = "#0c1f4c"
    DEFAULT_SITE_SETTINGS[f"{page_key}_section_button_text"] = "Action"
    DEFAULT_SITE_SETTINGS[f"{page_key}_section_button_bg_color"] = "#1f3a7a"
    DEFAULT_SITE_SETTINGS[f"{page_key}_section_button_text_color"] = "#ffffff"


def table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def add_column_if_missing(
    cursor: sqlite3.Cursor,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    if column_name not in table_columns(cursor, table_name):
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )


def record_schema_migration(cursor: sqlite3.Cursor, version: str, description: str) -> None:
    cursor.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
        VALUES (?, ?, ?)
        """,
        (version, description, datetime.utcnow().isoformat()),
    )


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
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    record_schema_migration(cursor, "0001", "Baseline schema with ad hoc compatibility migrations")

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
            price REAL NOT NULL CHECK (price >= 0),
            status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'inactive', 'archived')),
            stock INTEGER NOT NULL CHECK (stock >= 0),
            color TEXT,
            size TEXT,
            category TEXT,
            archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
            deleted_at TEXT,
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
            paypal_order_id TEXT UNIQUE,
            capture_id TEXT UNIQUE,
            shipping_fee REAL NOT NULL DEFAULT 0 CHECK (shipping_fee >= 0),
            total REAL NOT NULL CHECK (total >= 0),
            created_at TEXT NOT NULL
        )
        """
    )

    add_column_if_missing(cursor, "orders", "shipping_fee", "REAL NOT NULL DEFAULT 0")
    add_column_if_missing(cursor, "orders", "paypal_order_id", "TEXT")
    add_column_if_missing(cursor, "orders", "capture_id", "TEXT")
    record_schema_migration(cursor, "0002", "Add PayPal idempotency columns to orders")

    for column_name in ("color", "size", "category"):
        add_column_if_missing(cursor, "products", column_name, "TEXT")
    add_column_if_missing(cursor, "products", "archived", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(cursor, "products", "deleted_at", "TEXT")
    record_schema_migration(cursor, "0003", "Add product archival fields")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            color TEXT,
            size TEXT,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            price REAL NOT NULL CHECK (price >= 0),
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
            quantity INTEGER NOT NULL CHECK (quantity >= 0),
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
            total REAL NOT NULL CHECK (total >= 0),
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

    for column_name in ("color", "size"):
        add_column_if_missing(cursor, "order_items", column_name, "TEXT")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_status ON products(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_created_at ON products(created_at)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_inventory_lookup "
        "ON product_inventory(product_id, color, size)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_customer_email ON orders(customer_email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_payment_status ON orders(payment_status)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_paypal_order_id ON orders(paypal_order_id) WHERE paypal_order_id IS NOT NULL")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_capture_id ON orders(capture_id) WHERE capture_id IS NOT NULL")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_order_id ON transactions(order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payment_logs_order_event ON payment_logs(order_id, event)")
    record_schema_migration(cursor, "0004", "Add storefront lookup and payment indexes")

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
