from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from elit21.db import get_connection, init_db


PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "demo-client-id")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_ENV = os.getenv("PAYPAL_ENV", "sandbox").lower()
SHIPPING_FEE = float(os.getenv("SHIPPING_FEE", "9.99"))


def paypal_base_url() -> str:
    return (
        "https://api-m.paypal.com"
        if PAYPAL_ENV == "live"
        else "https://api-m.sandbox.paypal.com"
    )


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

    def ensure_paypal_configured() -> tuple[bool, str]:
        if not PAYPAL_CLIENT_ID or PAYPAL_CLIENT_ID == "demo-client-id":
            return False, "Client PayPal non configuré."
        if not PAYPAL_CLIENT_SECRET:
            return False, "Secret PayPal non configuré."
        return True, ""

    def paypal_request(path: str, method: str = "GET", payload: dict | None = None):
        is_configured, config_error = ensure_paypal_configured()
        if not is_configured:
            raise RuntimeError(config_error)
        auth_value = f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}".encode("utf-8")
        basic_token = base64.b64encode(auth_value).decode("ascii")
        token_request = urllib.request.Request(
            f"{paypal_base_url()}/v1/oauth2/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {basic_token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(token_request, timeout=20) as response:
                token_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8")
            raise RuntimeError(f"PayPal auth échouée: {details}") from exc
        access_token = token_payload.get("access_token")
        if not access_token:
            raise RuntimeError("Réponse d'authentification PayPal invalide.")
        request_data = None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if payload is not None:
            request_data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        api_request = urllib.request.Request(
            f"{paypal_base_url()}{path}",
            data=request_data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(api_request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8")
            raise RuntimeError(f"PayPal API échouée: {details}") from exc

    def collect_shipping_data(form_data):
        customer_name = form_data.get("customer_name", "").strip()
        house_number = form_data.get("house_number", "").strip()
        street = form_data.get("street", "").strip()
        apartment = form_data.get("apartment", "").strip()
        city = form_data.get("city", "").strip()
        province = form_data.get("province", "").strip()
        country = form_data.get("country", "").strip()
        postal_code = form_data.get("postal_code", "").strip()
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
            return None
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
        return {
            "customer_name": customer_name,
            "address": address,
            "city": city,
            "country": country,
            "postal_code": postal_code,
        }

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
            paypal_configured=ensure_paypal_configured()[0],
        )

    @app.route("/api/checkout/create-paypal-order", methods=["POST"])
    @login_required
    def create_paypal_order():
        shipping_data = collect_shipping_data(request.json or {})
        if not shipping_data:
            return jsonify({"error": "Adresse de livraison incomplète."}), 400
        items, subtotal = load_cart_items()
        if not items:
            return jsonify({"error": "Votre panier est vide."}), 400
        total = subtotal + SHIPPING_FEE
        conn = get_connection()
        user = conn.execute(
            "SELECT email FROM users WHERE id = ?",
            (session.get("user_id"),),
        ).fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "Compte utilisateur introuvable."}), 404
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
                shipping_data["customer_name"],
                user["email"],
                shipping_data["address"],
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
                return jsonify({"error": "Stock insuffisant pour finaliser la commande."}), 409
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
        try:
            paypal_order = paypal_request(
                "/v2/checkout/orders",
                method="POST",
                payload={
                    "intent": "CAPTURE",
                    "purchase_units": [
                        {
                            "reference_id": str(order_id),
                            "amount": {
                                "currency_code": "EUR",
                                "value": f"{total:.2f}",
                            },
                            "description": f"Commande ELIT21 #{order_id}",
                        }
                    ],
                    "application_context": {
                        "brand_name": "ELIT21",
                        "shipping_preference": "NO_SHIPPING",
                        "user_action": "PAY_NOW",
                    },
                },
            )
        except RuntimeError as exc:
            conn.rollback()
            conn.close()
            return jsonify({"error": str(exc)}), 502
        paypal_order_id = paypal_order.get("id")
        if not paypal_order_id:
            conn.rollback()
            conn.close()
            return jsonify({"error": "Réponse PayPal invalide."}), 502
        cursor.execute(
            "UPDATE orders SET payment_status = ? WHERE id = ?",
            (f"paypal_order:{paypal_order_id}", order_id),
        )
        conn.commit()
        conn.close()
        return jsonify({"id": paypal_order_id, "local_order_id": order_id})

    @app.route("/api/checkout/capture-paypal-order", methods=["POST"])
    @login_required
    def capture_paypal_order():
        payload = request.json or {}
        paypal_order_id = (payload.get("paypal_order_id") or "").strip()
        local_order_id = payload.get("local_order_id")
        if not paypal_order_id or not local_order_id:
            return jsonify({"error": "Paramètres de paiement manquants."}), 400
        conn = get_connection()
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (local_order_id,),
        ).fetchone()
        if not order:
            conn.close()
            return jsonify({"error": "Commande introuvable."}), 404
        current_user = conn.execute(
            "SELECT email FROM users WHERE id = ?", (session.get("user_id"),)
        ).fetchone()
        if not current_user or order["customer_email"] != current_user["email"]:
            conn.close()
            return jsonify({"error": "Accès non autorisé à cette commande."}), 403
        if f"paypal_order:{paypal_order_id}" != order["payment_status"]:
            conn.close()
            return jsonify({"error": "Commande PayPal incohérente."}), 409
        try:
            capture = paypal_request(
                f"/v2/checkout/orders/{paypal_order_id}/capture",
                method="POST",
                payload={},
            )
        except RuntimeError as exc:
            conn.close()
            return jsonify({"error": str(exc)}), 502
        status = capture.get("status")
        purchase_units = capture.get("purchase_units") or []
        capture_id = None
        if purchase_units:
            payments = purchase_units[0].get("payments") or {}
            captures = payments.get("captures") or []
            if captures:
                capture_id = captures[0].get("id")
        if status != "COMPLETED":
            conn.close()
            return jsonify({"error": "Le paiement PayPal n'est pas confirmé."}), 409
        order_items = conn.execute(
            "SELECT * FROM order_items WHERE order_id = ?",
            (local_order_id,),
        ).fetchall()
        for item in order_items:
            inventory = conn.execute(
                """
                SELECT id, quantity
                FROM product_inventory
                WHERE product_id = ? AND color = ? AND size = ?
                """,
                (item["product_id"], item["color"], item["size"]),
            ).fetchone()
            if not inventory or inventory["quantity"] < item["quantity"]:
                conn.close()
                return jsonify({"error": "Stock insuffisant après confirmation de paiement."}), 409
        cursor = conn.cursor()
        for item in order_items:
            inventory = conn.execute(
                "SELECT id, quantity FROM product_inventory WHERE product_id = ? AND color = ? AND size = ?",
                (item["product_id"], item["color"], item["size"]),
            ).fetchone()
            cursor.execute(
                "UPDATE product_inventory SET quantity = ? WHERE id = ?",
                (inventory["quantity"] - item["quantity"], inventory["id"]),
            )
            total_stock = conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS total FROM product_inventory WHERE product_id = ?",
                (item["product_id"],),
            ).fetchone()["total"]
            cursor.execute(
                "UPDATE products SET stock = ? WHERE id = ?",
                (total_stock, item["product_id"]),
            )
        cursor.execute(
            """
            UPDATE orders
            SET status = ?, payment_status = ?
            WHERE id = ?
            """,
            ("confirmed", f"paid:{capture_id or paypal_order_id}", local_order_id),
        )
        cursor.execute(
            "INSERT INTO transactions (order_id, completed_at, total) VALUES (?, ?, ?)",
            (local_order_id, datetime.utcnow().isoformat(), order["total"]),
        )
        conn.commit()
        conn.close()
        session["cart"] = {}
        return jsonify(
            {
                "ok": True,
                "redirect_url": url_for("checkout_success", order_id=local_order_id),
            }
        )

    @app.route("/checkout/success/<int:order_id>")
    @login_required
    def checkout_success(order_id: int):
        conn = get_connection()
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        current_user = conn.execute(
            "SELECT email FROM users WHERE id = ?", (session.get("user_id"),)
        ).fetchone()
        conn.close()
        if (
            not order
            or not current_user
            or order["customer_email"] != current_user["email"]
            or not str(order["payment_status"]).startswith("paid:")
        ):
            flash("Commande non confirmée.")
            return redirect(url_for("checkout"))
        return render_template("checkout_success.html", order=order)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
