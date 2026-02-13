from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
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


def load_env_file() -> None:
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            cleaned_value = value.strip().strip('\"').strip("'").strip()
            os.environ.setdefault(key, cleaned_value)


load_env_file()


def paypal_debug_enabled() -> bool:
    return os.getenv("PAYPAL_DEBUG", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_paypal_settings() -> dict[str, str]:
    # Read configuration at runtime so .env / process-level updates are used
    # without importing stale values.
    client_id = os.getenv("PAYPAL_CLIENT_ID", "demo-client-id").strip()
    client_secret = (
        os.getenv("PAYPAL_CLIENT_SECRET")
        or os.getenv("PAYPAL_SECRET_KEY_1")
        or ""
    ).strip()
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "env": os.getenv("PAYPAL_ENV", "sandbox").strip().lower(),
    }


def is_placeholder_paypal_credential(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return normalized in {
        "",
        "demo-client-id",
        "demo-client-secret",
        "your-paypal-client-id",
        "your-paypal-client-secret",
        "change-me",
    }


SHIPPING_FEE = float(os.getenv("SHIPPING_FEE", "9.99"))


def paypal_base_url(paypal_env: str) -> str:
    return (
        "https://api-m.paypal.com"
        if paypal_env == "live"
        else "https://api-m.sandbox.paypal.com"
    )


def create_app():
    app = Flask(
        __name__,
        static_folder=str(os.path.join(os.path.dirname(__file__), "..", "assets")),
        template_folder=str(os.path.join(os.path.dirname(__file__), "..", "templates")),
    )
    app.secret_key = os.getenv("ELIT21_SECRET", "elit21-secret")
    app.logger.setLevel(logging.DEBUG if paypal_debug_enabled() else logging.INFO)

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
        paypal_settings = get_paypal_settings()
        if is_placeholder_paypal_credential(paypal_settings["client_id"]):
            return False, "Client PayPal non configuré."
        if is_placeholder_paypal_credential(paypal_settings["client_secret"]):
            return False, "Secret PayPal non configuré."
        return True, ""

    def credential_fingerprint(raw_value: str) -> str:
        if not raw_value:
            return "empty"
        return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:10]

    def paypal_request(path: str, method: str = "GET", payload: dict | None = None):
        is_configured, config_error = ensure_paypal_configured()
        if not is_configured:
            raise RuntimeError(config_error)
        paypal_settings = get_paypal_settings()
        configured_env = paypal_settings["env"]
        paypal_client_id = paypal_settings["client_id"]
        paypal_client_secret = paypal_settings["client_secret"]
        app.logger.debug(
            "[paypal-debug] paypal_request start method=%s path=%s payload_keys=%s env=%s client_id_fp=%s secret_fp=%s",
            method,
            path,
            sorted(list((payload or {}).keys())),
            configured_env,
            credential_fingerprint(paypal_client_id),
            credential_fingerprint(paypal_client_secret),
        )
        auth_value = f"{paypal_client_id}:{paypal_client_secret}".encode("utf-8")
        basic_token = base64.b64encode(auth_value).decode("ascii")
        # Some deployments define HTTPS proxy variables that break PayPal with
        # "Tunnel connection failed: 403 Forbidden". We keep the default network
        # path first, and only retry without proxy for that specific proxy failure.
        direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def open_request(req: urllib.request.Request):
            try:
                return urllib.request.urlopen(req, timeout=20)
            except urllib.error.URLError as exc:
                reason = str(exc.reason).lower()
                if "tunnel connection failed" not in reason:
                    raise
                return direct_opener.open(req, timeout=20)

        def parse_paypal_error_body(raw_body: str) -> tuple[str, str]:
            try:
                parsed = json.loads(raw_body or "{}")
            except json.JSONDecodeError:
                return "", ""
            return str(parsed.get("error") or ""), str(parsed.get("error_description") or "")

        def environment_candidates(env: str) -> list[str]:
            normalized = (env or "sandbox").strip().lower()
            if normalized not in {"sandbox", "live"}:
                normalized = "sandbox"
            candidates = [normalized]
            alternate = "live" if normalized == "sandbox" else "sandbox"
            if os.getenv("PAYPAL_ENV_AUTO_FALLBACK", "1").strip().lower() not in {"0", "false", "no", "off"}:
                candidates.append(alternate)
            return candidates

        candidates = environment_candidates(configured_env)
        chosen_env = configured_env
        token_payload = None
        last_auth_error: RuntimeError | None = None
        for index, candidate_env in enumerate(candidates):
            token_request = urllib.request.Request(
                f"{paypal_base_url(candidate_env)}/v1/oauth2/token",
                data=b"grant_type=client_credentials",
                headers={
                    "Authorization": f"Basic {basic_token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
            try:
                with open_request(token_request) as response:
                    token_payload = json.loads(response.read().decode("utf-8"))
                    chosen_env = candidate_env
                    app.logger.debug(
                        "[paypal-debug] auth token received scope=%s expires_in=%s env=%s",
                        token_payload.get("scope"),
                        token_payload.get("expires_in"),
                        chosen_env,
                    )
                    break
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8")
                error_code, _error_description = parse_paypal_error_body(details)
                app.logger.error(
                    "[paypal-debug] auth http error status=%s env=%s client_id_fp=%s secret_fp=%s body=%s",
                    exc.code,
                    candidate_env,
                    credential_fingerprint(paypal_client_id),
                    credential_fingerprint(paypal_client_secret),
                    details,
                )
                last_auth_error = RuntimeError(
                    "PayPal auth échouée: "
                    f"{details}. Vérifiez PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET "
                    f"et PAYPAL_ENV={candidate_env}."
                )
                if (
                    exc.code == 401
                    and error_code == "invalid_client"
                    and index < len(candidates) - 1
                ):
                    app.logger.warning(
                        "[paypal-debug] auth invalid_client sur env=%s; tentative automatique sur l'autre environnement",
                        candidate_env,
                    )
                    continue
                raise last_auth_error from exc
            except urllib.error.URLError as exc:
                app.logger.error("[paypal-debug] auth network error reason=%s", exc.reason)
                raise RuntimeError(f"Connexion PayPal impossible: {exc.reason}") from exc

        if token_payload is None:
            if last_auth_error is not None:
                raise last_auth_error
            raise RuntimeError("Réponse d'authentification PayPal invalide.")

        if chosen_env != configured_env:
            app.logger.warning(
                "[paypal-debug] PAYPAL_ENV=%s mais credentials valides sur %s. Mettez PAYPAL_ENV=%s pour éviter ce fallback.",
                configured_env,
                chosen_env,
                chosen_env,
            )

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
            f"{paypal_base_url(chosen_env)}{path}",
            data=request_data,
            headers=headers,
            method=method,
        )
        try:
            with open_request(api_request) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
                app.logger.debug(
                    "[paypal-debug] paypal_request success method=%s path=%s status=%s response_keys=%s env=%s",
                    method,
                    path,
                    getattr(response, "status", "unknown"),
                    sorted(list(response_payload.keys())),
                    chosen_env,
                )
                return response_payload
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8")
            app.logger.error(
                "[paypal-debug] api http error method=%s path=%s status=%s body=%s env=%s",
                method,
                path,
                exc.code,
                details,
                chosen_env,
            )
            raise RuntimeError(f"PayPal API échouée: {details}") from exc
        except urllib.error.URLError as exc:
            app.logger.error(
                "[paypal-debug] api network error method=%s path=%s reason=%s",
                method,
                path,
                exc.reason,
            )
            raise RuntimeError(f"Connexion API PayPal impossible: {exc.reason}") from exc

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
            paypal_client_id=get_paypal_settings()["client_id"],
            paypal_env=get_paypal_settings()["env"],
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
            paypal_client_id=get_paypal_settings()["client_id"],
            paypal_env=get_paypal_settings()["env"],
            paypal_debug_enabled=paypal_debug_enabled(),
            items=items,
            subtotal=subtotal,
            shipping_fee=SHIPPING_FEE,
            total=total,
            paypal_configured=ensure_paypal_configured()[0],
        )

    @app.route("/api/checkout/create-paypal-order", methods=["POST"])
    @login_required
    def create_paypal_order():
        def to_money(value: float | Decimal) -> Decimal:
            return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        def money_as_text(value: Decimal) -> str:
            return format(value, ".2f")

        shipping_data = collect_shipping_data(request.json or {})
        app.logger.info(
            "[paypal-debug] create_order requested user_id=%s cart_size=%s shipping_city=%s",
            session.get("user_id"),
            len(get_cart()),
            (request.json or {}).get("city", ""),
        )
        if not shipping_data:
            app.logger.warning("[paypal-debug] create_order rejected: incomplete shipping data")
            return jsonify({"error": "Adresse de livraison incomplète."}), 400
        items, subtotal = load_cart_items()
        if not items:
            app.logger.warning("[paypal-debug] create_order rejected: empty cart")
            return jsonify({"error": "Votre panier est vide."}), 400
        subtotal_money = to_money(subtotal)
        shipping_fee_money = to_money(SHIPPING_FEE)
        total_money = to_money(subtotal_money + shipping_fee_money)
        paypal_items = []
        for item in items:
            unit_amount = to_money(item["product"]["price"])
            paypal_items.append(
                {
                    "name": item["product"]["name"][:127],
                    "description": f"Couleur: {item['color']} / Taille: {item['size']}"[:127],
                    "sku": f"{item['product']['id']}-{item['color']}-{item['size']}"[:127],
                    "unit_amount": {
                        "currency_code": "EUR",
                        "value": money_as_text(unit_amount),
                    },
                    "quantity": str(item["quantity"]),
                    "category": "PHYSICAL_GOODS",
                }
            )
        conn = get_connection()
        user = conn.execute(
            "SELECT email FROM users WHERE id = ?",
            (session.get("user_id"),),
        ).fetchone()
        if not user:
            conn.close()
            app.logger.warning("[paypal-debug] create_order rejected: missing user for session")
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
                float(total_money),
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
                app.logger.warning(
                    "[paypal-debug] create_order rejected: stock issue product_id=%s color=%s size=%s needed=%s",
                    product["id"],
                    item["color"],
                    item["size"],
                    item["quantity"],
                )
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
            app.logger.info(
                "[paypal-debug] paypal order creation started local_order_id=%s total=%s",
                order_id,
                money_as_text(total_money),
            )
            paypal_order = paypal_request(
                "/v2/checkout/orders",
                method="POST",
                payload={
                    "intent": "CAPTURE",
                    "purchase_units": [
                        {
                            "reference_id": str(order_id),
                            "invoice_id": f"ELIT21-{order_id}",
                            "amount": {
                                "currency_code": "EUR",
                                "value": money_as_text(total_money),
                                "breakdown": {
                                    "item_total": {
                                        "currency_code": "EUR",
                                        "value": money_as_text(subtotal_money),
                                    },
                                    "shipping": {
                                        "currency_code": "EUR",
                                        "value": money_as_text(shipping_fee_money),
                                    },
                                },
                            },
                            "description": f"Commande ELIT21 #{order_id}",
                            "items": paypal_items,
                        }
                    ],
                    "application_context": {
                        "brand_name": "ELIT21",
                        "shipping_preference": "NO_SHIPPING",
                        "user_action": "PAY_NOW",
                        "return_url": url_for("paypal_return", _external=True),
                        "cancel_url": url_for("paypal_cancel", _external=True),
                    },
                },
            )
        except RuntimeError as exc:
            conn.rollback()
            conn.close()
            app.logger.exception(
                "[paypal-debug] paypal order creation failed local_order_id=%s",
                order_id,
            )
            return jsonify({"error": str(exc)}), 502
        paypal_order_id = paypal_order.get("id")
        if not paypal_order_id:
            conn.rollback()
            conn.close()
            app.logger.error(
                "[paypal-debug] paypal order creation invalid response local_order_id=%s payload=%s",
                order_id,
                paypal_order,
            )
            return jsonify({"error": "Réponse PayPal invalide."}), 502
        cursor.execute(
            "UPDATE orders SET payment_status = ? WHERE id = ?",
            (f"paypal_order:{paypal_order_id}", order_id),
        )
        conn.commit()
        conn.close()
        approval_url = None
        for link in paypal_order.get("links") or []:
            if link.get("rel") == "approve":
                approval_url = link.get("href")
                break
        app.logger.info(
            "[paypal-debug] paypal order created local_order_id=%s paypal_order_id=%s has_approve_url=%s",
            order_id,
            paypal_order_id,
            bool(approval_url),
        )
        return jsonify(
            {
                "id": paypal_order_id,
                "local_order_id": order_id,
                "approve_url": approval_url,
            }
        )

    def capture_paypal_order_for_current_user(
        paypal_order_id: str,
        local_order_id: int | None,
    ) -> tuple[dict, int]:
        if not paypal_order_id:
            app.logger.warning("[paypal-debug] capture_order rejected: missing paypal_order_id")
            return {"error": "Paramètres de paiement manquants."}, 400
        conn = get_connection()
        current_user = conn.execute(
            "SELECT email FROM users WHERE id = ?", (session.get("user_id"),)
        ).fetchone()
        if not current_user:
            conn.close()
            app.logger.warning("[paypal-debug] capture_order rejected: no current user")
            return {"error": "Accès non autorisé à cette commande."}, 403
        order = None
        if local_order_id:
            order = conn.execute(
                "SELECT * FROM orders WHERE id = ?",
                (local_order_id,),
            ).fetchone()
        if not order:
            order = conn.execute(
                """
                SELECT *
                FROM orders
                WHERE payment_status = ? AND customer_email = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (f"paypal_order:{paypal_order_id}", current_user["email"]),
            ).fetchone()
        if not order:
            conn.close()
            app.logger.warning("[paypal-debug] capture_order rejected: order not found")
            return {"error": "Commande introuvable."}, 404
        if order["customer_email"] != current_user["email"]:
            conn.close()
            app.logger.warning(
                "[paypal-debug] capture_order rejected: email mismatch local_order_id=%s",
                order["id"],
            )
            return {"error": "Accès non autorisé à cette commande."}, 403
        if f"paypal_order:{paypal_order_id}" != order["payment_status"]:
            conn.close()
            app.logger.warning(
                "[paypal-debug] capture_order rejected: payment status mismatch local_order_id=%s status=%s",
                order["id"],
                order["payment_status"],
            )
            return {"error": "Commande PayPal incohérente."}, 409
        local_order_id = order["id"]
        try:
            capture = paypal_request(
                f"/v2/checkout/orders/{paypal_order_id}/capture",
                method="POST",
                payload={},
            )
        except RuntimeError as exc:
            conn.close()
            app.logger.exception(
                "[paypal-debug] paypal capture failed local_order_id=%s paypal_order_id=%s",
                local_order_id,
                paypal_order_id,
            )
            return {"error": str(exc)}, 502
        status = capture.get("status")
        purchase_units = capture.get("purchase_units") or []
        capture_id = None
        capture_amount = None
        capture_currency = None
        reference_id = None
        if purchase_units:
            reference_id = purchase_units[0].get("reference_id")
            payments = purchase_units[0].get("payments") or {}
            captures = payments.get("captures") or []
            if captures:
                capture_id = captures[0].get("id")
                amount_info = captures[0].get("amount") or {}
                capture_amount = amount_info.get("value")
                capture_currency = amount_info.get("currency_code")
        if status != "COMPLETED":
            conn.close()
            app.logger.error(
                "[paypal-debug] paypal capture incomplete local_order_id=%s paypal_order_id=%s status=%s payload=%s",
                local_order_id,
                paypal_order_id,
                status,
                capture,
            )
            return {"error": "Le paiement PayPal n'est pas confirmé."}, 409
        expected_reference = str(local_order_id)
        expected_total = Decimal(str(order["total"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        expected_total_text = format(expected_total, ".2f")
        if reference_id and reference_id != expected_reference:
            conn.close()
            app.logger.error(
                "[paypal-debug] capture_order rejected: reference mismatch local_order_id=%s expected=%s got=%s",
                local_order_id,
                expected_reference,
                reference_id,
            )
            return {"error": "Commande PayPal incohérente (reference)."}, 409
        if capture_currency and capture_currency != "EUR":
            conn.close()
            app.logger.error(
                "[paypal-debug] capture_order rejected: currency mismatch local_order_id=%s expected=EUR got=%s",
                local_order_id,
                capture_currency,
            )
            return {"error": "Devise PayPal inattendue."}, 409
        if capture_amount and capture_amount != expected_total_text:
            conn.close()
            app.logger.error(
                "[paypal-debug] capture_order rejected: amount mismatch local_order_id=%s expected=%s got=%s",
                local_order_id,
                expected_total_text,
                capture_amount,
            )
            return {"error": "Montant PayPal incohérent."}, 409
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
                app.logger.warning(
                    "[paypal-debug] capture_order rejected: stock issue post-capture local_order_id=%s product_id=%s",
                    local_order_id,
                    item["product_id"],
                )
                return {"error": "Stock insuffisant après confirmation de paiement."}, 409
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
        app.logger.info(
            "[paypal-debug] capture_order completed local_order_id=%s paypal_order_id=%s capture_id=%s",
            local_order_id,
            paypal_order_id,
            capture_id,
        )
        session["cart"] = {}
        return {
            "ok": True,
            "redirect_url": url_for("checkout_success", order_id=local_order_id),
        }, 200

    @app.route("/api/checkout/capture-paypal-order", methods=["POST"])
    @login_required
    def capture_paypal_order():
        payload = request.json or {}
        paypal_order_id = (payload.get("paypal_order_id") or "").strip()
        local_order_id = payload.get("local_order_id")
        app.logger.info(
            "[paypal-debug] capture_order requested user_id=%s local_order_id=%s paypal_order_id=%s",
            session.get("user_id"),
            local_order_id,
            paypal_order_id,
        )
        response, status_code = capture_paypal_order_for_current_user(
            paypal_order_id=paypal_order_id,
            local_order_id=local_order_id,
        )
        return jsonify(response), status_code

    @app.route("/checkout/paypal/return")
    @login_required
    def paypal_return():
        paypal_order_id = (request.args.get("token") or "").strip()
        local_order_id_raw = request.args.get("local_order_id")
        local_order_id = int(local_order_id_raw) if (local_order_id_raw or "").isdigit() else None
        app.logger.info(
            "[paypal-debug] paypal return user_id=%s local_order_id=%s paypal_order_id=%s payer_id=%s",
            session.get("user_id"),
            local_order_id,
            paypal_order_id,
            request.args.get("PayerID"),
        )
        response, status_code = capture_paypal_order_for_current_user(
            paypal_order_id=paypal_order_id,
            local_order_id=local_order_id,
        )
        if status_code != 200:
            flash(response.get("error") or "Paiement PayPal non confirmé.")
            return redirect(url_for("checkout"))
        return redirect(response["redirect_url"])

    @app.route("/checkout/paypal/cancel")
    @login_required
    def paypal_cancel():
        app.logger.info(
            "[paypal-debug] paypal cancel user_id=%s token=%s",
            session.get("user_id"),
            request.args.get("token"),
        )
        flash("Paiement PayPal annulé. Vous pouvez réessayer.")
        return redirect(url_for("checkout"))

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
