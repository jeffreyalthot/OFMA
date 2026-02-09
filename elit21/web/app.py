from __future__ import annotations

import hashlib
import os
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from elit21.db import get_connection, init_db


PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "demo-client-id")
PAYPAL_ENV = os.getenv("PAYPAL_ENV", "sandbox")
SHIPPING_FEE = float(os.getenv("SHIPPING_FEE", "9.99"))


def create_app():
    app = Flask(
        __name__,
        static_folder=str(os.path.join(os.path.dirname(__file__), "..", "assets")),
        template_folder=str(os.path.join(os.path.dirname(__file__), "..", "templates")),
    )
    app.secret_key = os.getenv("ELIT21_SECRET", "elit21-secret")

    init_db()

    def get_cart() -> dict[str, int]:
        cart = session.get("cart")
        if cart is None or not isinstance(cart, dict):
            cart = {}
            session["cart"] = cart
        return cart

    def build_cart_key(product_id: int, color: str, size: str) -> str:
        return f"{product_id}|{color}|{size}"

    def parse_cart_key(cart_key: str) -> tuple[int, str, str]:
        parts = cart_key.split("|", 2)
        if len(parts) != 3:
            raise ValueError("Clé panier invalide.")
        return int(parts[0]), parts[1], parts[2]

    def cart_count() -> int:
        return sum(get_cart().values())

    def load_cart_items():
        cart = get_cart()
        if not cart:
            return [], 0.0
        product_ids = list({parse_cart_key(key)[0] for key in cart.keys()})
        placeholders = ",".join("?" for _ in product_ids)
        conn = get_connection()
        products = conn.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders})",
            product_ids,
        ).fetchall()
        conn.close()
        items = []
        subtotal = 0.0
        products_map = {str(product["id"]): product for product in products}
        for cart_key, quantity in cart.items():
            product_id, color, size = parse_cart_key(cart_key)
            product = products_map.get(str(product_id))
            if not product:
                continue
            line_total = product["price"] * quantity
            subtotal += line_total
            items.append(
                {
                    "product": product,
                    "quantity": quantity,
                    "line_total": line_total,
                    "color": color,
                    "size": size,
                    "cart_key": cart_key,
                }
            )
        return items, subtotal

    @app.context_processor
    def inject_cart_metrics():
        return {"cart_count": cart_count()}

    def login_required(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash("Veuillez vous connecter pour continuer.")
                return redirect(url_for("login"))
            return view_func(*args, **kwargs)

        return wrapper

    @app.route("/")
    def index():
        conn = get_connection()
        products = conn.execute(
            """
            SELECT p.*, (
                SELECT id FROM product_images
                WHERE product_id = p.id
                ORDER BY position LIMIT 1
            ) AS first_image_id
            FROM products p
            WHERE p.status = ?
            ORDER BY p.created_at DESC
            """,
            ("active",),
        ).fetchall()
        conn.close()
        return render_template(
            "index.html",
            products=products,
            paypal_client_id=PAYPAL_CLIENT_ID,
            paypal_env=PAYPAL_ENV,
        )

    @app.route("/product/<int:product_id>")
    def product_detail(product_id: int):
        conn = get_connection()
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        images = conn.execute(
            "SELECT id, mime_type FROM product_images WHERE product_id = ? ORDER BY position",
            (product_id,),
        ).fetchall()
        inventory = conn.execute(
            """
            SELECT color, size, quantity
            FROM product_inventory
            WHERE product_id = ?
            ORDER BY color, size
            """,
            (product_id,),
        ).fetchall()
        conn.close()
        if not product:
            flash("Article introuvable.")
            return redirect(url_for("index"))
        colors = sorted({row["color"] for row in inventory})
        sizes = sorted({row["size"] for row in inventory})
        return render_template(
            "product.html",
            product=product,
            images=images,
            colors=colors,
            sizes=sizes,
            inventory=inventory,
        )

    @app.route("/cart")
    def cart():
        items, subtotal = load_cart_items()
        total = subtotal + (SHIPPING_FEE if items else 0.0)
        return render_template(
            "cart.html",
            items=items,
            subtotal=subtotal,
            shipping_fee=SHIPPING_FEE,
            total=total,
        )

    @app.route("/cart/add/<int:product_id>", methods=["POST"])
    def add_to_cart(product_id: int):
        color = request.form.get("color", "").strip()
        size = request.form.get("size", "").strip()
        conn = get_connection()
        product = conn.execute("SELECT id, status FROM products WHERE id = ?", (product_id,)).fetchone()
        inventory_row = conn.execute(
            """
            SELECT quantity
            FROM product_inventory
            WHERE product_id = ? AND color = ? AND size = ?
            """,
            (product_id, color, size),
        ).fetchone()
        conn.close()
        if not product or product["status"] != "active":
            flash("Article indisponible.")
            return redirect(url_for("index"))
        if not color or not size:
            flash("Veuillez sélectionner une couleur et une taille.")
            return redirect(url_for("product_detail", product_id=product_id))
        if not inventory_row or inventory_row["quantity"] <= 0:
            flash("Article en rupture de stock.")
            return redirect(url_for("product_detail", product_id=product_id))
        cart = get_cart()
        cart_key = build_cart_key(product_id, color, size)
        current_quantity = cart.get(cart_key, 0)
        if current_quantity + 1 > inventory_row["quantity"]:
            flash("Stock insuffisant pour cette variante.")
            return redirect(url_for("product_detail", product_id=product_id))
        cart[cart_key] = current_quantity + 1
        session["cart"] = cart
        flash("Article ajouté au panier.")
        return redirect(url_for("cart"))

    @app.route("/cart/update", methods=["POST"])
    def update_cart_item():
        quantity_str = request.form.get("quantity", "").strip()
        cart_key = request.form.get("cart_key", "").strip()
        if not quantity_str.isdigit():
            flash("Quantité invalide.")
            return redirect(url_for("cart"))
        quantity = int(quantity_str)
        cart = get_cart()
        if cart_key:
            if quantity <= 0:
                cart.pop(cart_key, None)
            else:
                product_id, color, size = parse_cart_key(cart_key)
                conn = get_connection()
                inventory_row = conn.execute(
                    """
                    SELECT quantity
                    FROM product_inventory
                    WHERE product_id = ? AND color = ? AND size = ?
                    """,
                    (product_id, color, size),
                ).fetchone()
                conn.close()
                if not inventory_row or quantity > inventory_row["quantity"]:
                    flash("Stock insuffisant pour cette variante.")
                    return redirect(url_for("cart"))
                cart[cart_key] = quantity
        session["cart"] = cart
        return redirect(url_for("cart"))

    @app.route("/cart/remove", methods=["POST"])
    def remove_cart_item():
        cart_key = request.form.get("cart_key", "").strip()
        cart = get_cart()
        if cart_key:
            cart.pop(cart_key, None)
        session["cart"] = cart
        return redirect(url_for("cart"))

    @app.route("/product/<int:product_id>/image/<int:image_id>")
    def product_image(product_id: int, image_id: int):
        conn = get_connection()
        image = conn.execute(
            "SELECT image_blob, mime_type FROM product_images WHERE id = ? AND product_id = ?",
            (image_id, product_id),
        ).fetchone()
        conn.close()
        if not image:
            return "", 404
        return (image["image_blob"], 200, {"Content-Type": image["mime_type"]})

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            full_name = request.form.get("full_name", "").strip()
            password = request.form.get("password", "")
            if not email or not full_name or not password:
                flash("Tous les champs sont obligatoires.")
                return redirect(url_for("register"))
            password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
            conn = get_connection()
            try:
                conn.execute(
                    "INSERT INTO users (email, password_hash, full_name, created_at) VALUES (?, ?, ?, ?)",
                    (email, password_hash, full_name, datetime.utcnow().isoformat()),
                )
                conn.commit()
            except Exception:
                conn.close()
                flash("Compte déjà existant ou erreur de sauvegarde.")
                return redirect(url_for("register"))
            conn.close()
            flash("Compte créé avec succès. Vous pouvez vous connecter.")
            return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
            conn = get_connection()
            user = conn.execute(
                "SELECT * FROM users WHERE email = ? AND password_hash = ?",
                (email, password_hash),
            ).fetchone()
            conn.close()
            if not user:
                flash("Identifiants invalides.")
                return redirect(url_for("login"))
            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/checkout")
    @login_required
    def checkout():
        items, subtotal = load_cart_items()
        if not items:
            flash("Votre panier est vide.")
            return redirect(url_for("cart"))
        total = subtotal + SHIPPING_FEE
        return render_template(
            "checkout.html",
            paypal_client_id=PAYPAL_CLIENT_ID,
            paypal_env=PAYPAL_ENV,
            items=items,
            subtotal=subtotal,
            shipping_fee=SHIPPING_FEE,
            total=total,
        )

    @app.route("/checkout/place-order", methods=["POST"])
    @login_required
    def place_order():
        customer_name = request.form.get("customer_name", "").strip()
        house_number = request.form.get("house_number", "").strip()
        street = request.form.get("street", "").strip()
        apartment = request.form.get("apartment", "").strip()
        city = request.form.get("city", "").strip()
        province = request.form.get("province", "").strip()
        country = request.form.get("country", "").strip()
        postal_code = request.form.get("postal_code", "").strip()
        required_fields = [
            customer_name,
            house_number,
            street,
            city,
            province,
            country,
            postal_code,
        ]
        if not all(required_fields):
            flash("Veuillez renseigner votre nom et une adresse complète de livraison.")
            return redirect(url_for("checkout"))
        address_line = f"{house_number} {street}".strip()
        if apartment:
            address_line = f"{address_line}, Apt {apartment}"
        address = "\n".join(
            [
                address_line,
                f"{city}, {province}",
                f"{country}, {postal_code}",
            ]
        )
        items, subtotal = load_cart_items()
        if not items:
            flash("Votre panier est vide.")
            return redirect(url_for("cart"))
        total = subtotal + SHIPPING_FEE
        conn = get_connection()
        user = conn.execute(
            "SELECT email FROM users WHERE id = ?",
            (session.get("user_id"),),
        ).fetchone()
        if not user:
            conn.close()
            flash("Compte utilisateur introuvable.")
            return redirect(url_for("checkout"))
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO orders (
                customer_name,
                customer_email,
                customer_address,
                status,
                payment_status,
                shipping_fee,
                total,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_name,
                user["email"],
                address,
                "pending",
                "pending",
                SHIPPING_FEE,
                total,
                datetime.utcnow().isoformat(),
            ),
        )
        order_id = cursor.lastrowid
        for item in items:
            product = item["product"]
            inventory = conn.execute(
                """
                SELECT id, quantity
                FROM product_inventory
                WHERE product_id = ? AND color = ? AND size = ?
                """,
                (product["id"], item["color"], item["size"]),
            ).fetchone()
            if not inventory or inventory["quantity"] < item["quantity"]:
                conn.close()
                flash("Stock insuffisant pour finaliser la commande.")
                return redirect(url_for("cart"))
            cursor.execute(
                """
                INSERT INTO order_items (order_id, product_id, product_name, color, size, quantity, price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    product["id"],
                    product["name"],
                    item["color"],
                    item["size"],
                    item["quantity"],
                    product["price"],
                ),
            )
            cursor.execute(
                "UPDATE product_inventory SET quantity = ? WHERE id = ?",
                (inventory["quantity"] - item["quantity"], inventory["id"]),
            )
            total_stock = conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS total FROM product_inventory WHERE product_id = ?",
                (product["id"],),
            ).fetchone()["total"]
            cursor.execute(
                "UPDATE products SET stock = ? WHERE id = ?",
                (total_stock, product["id"]),
            )
        conn.commit()
        conn.close()
        flash("Commande enregistrée. Procédez au paiement PayPal.")
        return redirect(url_for("checkout"))

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
