from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from elit21.config import load_app_config
from elit21.db import CURRENCY_OPTIONS, get_connection, get_site_settings, init_db
from elit21.i18n import normalize_language, tr
from elit21.services.media_service import resolve_image_path


def load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
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


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    if stored_hash.startswith("pbkdf2:") or stored_hash.startswith("scrypt:"):
        return check_password_hash(stored_hash, password)
    legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return legacy_hash == stored_hash


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
    app_config = load_app_config()
    app.secret_key = app_config.secret_key
    app.logger.setLevel(logging.DEBUG if paypal_debug_enabled() else logging.INFO)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=app_config.session_cookie_secure,
    )

    login_attempts: dict[str, list[datetime]] = {}
    login_limit_window = timedelta(minutes=10)
    login_limit_max_attempts = 5
    blocked_endpoints = {
        "create_paypal_order",
        "capture_paypal_order",
    }

    @app.before_request
    def enforce_https_and_sensitive_rate_limit():
        if not request.is_secure and request.headers.get("X-Forwarded-Proto", "http") != "https":
            if app_config.force_https:
                url = request.url.replace("http://", "https://", 1)
                return redirect(url, code=308)
            if request.endpoint in blocked_endpoints:
                return jsonify({"error": "HTTPS requis pour cette action."}), 400

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "script-src 'self' https://www.paypal.com https://www.sandbox.paypal.com; "
            "style-src 'self' 'unsafe-inline'; "
            "frame-src https://www.paypal.com https://www.sandbox.paypal.com; "
            "connect-src 'self' https://www.paypal.com https://www.sandbox.paypal.com; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none';"
        )
        if app_config.hsts_enabled:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

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
            raise ValueError("Invalid cart key.")
        return int(parts[0]), parts[1], parts[2]

    def current_language() -> str:
        return normalize_language(get_site_settings().get("language_code"))

    def t(key: str) -> str:
        return tr(current_language(), key)

    def cart_count() -> int:
        return sum(get_cart().values())

    def log_payment_event(
        *,
        event: str,
        status: str,
        order_id: int | None = None,
        request_payload: dict | None = None,
        response_payload: dict | None = None,
        error_message: str | None = None,
        retries: int = 0,
    ) -> None:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO payment_logs (
                order_id, event, request_payload, response_payload, status, error_message, retries, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                event,
                json.dumps(request_payload or {}, ensure_ascii=False),
                json.dumps(response_payload or {}, ensure_ascii=False),
                status,
                error_message,
                retries,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

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

    def get_site_settings_payload() -> dict[str, str]:
        return get_site_settings()

    def get_page_customization(page_id: str) -> dict[str, str]:
        settings = get_site_settings_payload()
        normalized = (page_id or "index").strip()
        return {
            "page_id": normalized,
            "title": settings.get(f"{normalized}_title_text", "").strip(),
            "subtitle": settings.get(f"{normalized}_subtitle_text", "").strip(),
            "body": settings.get(f"{normalized}_body_text", "").strip(),
            "accent_color": settings.get(f"{normalized}_accent_color", "#1f3a7a").strip() or "#1f3a7a",
            "text_align": settings.get(f"{normalized}_text_align", "left").strip() or "left",
            "section_title": settings.get(f"{normalized}_section_title_text", "").strip(),
            "section_subtitle": settings.get(f"{normalized}_section_subtitle_text", "").strip(),
            "section_body": settings.get(f"{normalized}_section_body_text", "").strip(),
            "section_button_text": settings.get(f"{normalized}_section_button_text", "").strip(),
            "section_bg_color": settings.get(f"{normalized}_section_bg_color", "#ffffff").strip() or "#ffffff",
            "section_text_color": settings.get(f"{normalized}_section_text_color", "#0c1f4c").strip() or "#0c1f4c",
            "section_button_bg_color": settings.get(f"{normalized}_section_button_bg_color", "#1f3a7a").strip() or "#1f3a7a",
            "section_button_text_color": settings.get(f"{normalized}_section_button_text_color", "#ffffff").strip() or "#ffffff",
        }

    def get_shipping_fee() -> float:
        settings = get_site_settings_payload()
        raw_shipping_fee = str(settings.get("shipping_fee") or "0").strip()
        try:
            shipping_fee = Decimal(raw_shipping_fee)
        except Exception:
            shipping_fee = Decimal("0")
        return float(shipping_fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def get_currency_payload() -> dict[str, str]:
        settings = get_site_settings_payload()
        currency_code = str(settings.get("currency_code") or "CAD").upper()
        if currency_code not in CURRENCY_OPTIONS:
            currency_code = "CAD"
        currency_meta = CURRENCY_OPTIONS[currency_code]
        return {
            "code": currency_code,
            "name": currency_meta["name"],
            "symbol": currency_meta["symbol"],
            "label": f"{currency_meta['symbol']} ({currency_code})",
        }

    def format_money(value: float | Decimal) -> str:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{get_currency_payload()['label']} {amount:.2f}"

    def load_cart_items() -> tuple[list[dict], float]:
        cart = get_cart()
        if not cart:
            return [], 0.0

        valid_entries: list[tuple[str, int, str, str, int]] = []
        for key, quantity in cart.items():
            try:
                product_id, color, size = parse_cart_key(key)
            except (TypeError, ValueError):
                continue
            valid_entries.append((key, product_id, color, size, quantity))

        if not valid_entries:
            return [], 0.0

        product_ids = list({entry[1] for entry in valid_entries})
        placeholders = ",".join("?" for _ in product_ids)
        conn = get_connection()
        products = conn.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders}) AND status = ? AND archived = 0",
            [*product_ids, "active"],
        ).fetchall()
        conn.close()
        items = []
        subtotal = 0.0
        products_map = {str(product["id"]): product for product in products}
        for cart_key, product_id, color, size, quantity in valid_entries:
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

    def serialize_product(product, first_image_id: int | None = None) -> dict:
        image_id = first_image_id if first_image_id is not None else product["first_image_id"]
        return {
            "id": product["id"],
            "name": product["name"],
            "description": product["description"],
            "price": float(product["price"]),
            "status": product["status"],
            "stock": int(product["stock"]),
            "color": product["color"],
            "size": product["size"],
            "category": product["category"],
            "created_at": product["created_at"],
            "first_image_id": image_id,
            "image_url": (
                url_for("product_image", product_id=product["id"], image_id=image_id)
                if image_id
                else None
            ),
        }

    def fetch_active_products(*, category: str | None = None, limit: int | None = None):
        conn = get_connection()
        query = """
            SELECT p.*, (
                SELECT id FROM product_images
                WHERE product_id = p.id
                ORDER BY position LIMIT 1
            ) AS first_image_id
            FROM products p
            WHERE p.status = ? AND p.archived = 0
        """
        parameters: list[object] = ["active"]
        if category:
            query += " AND p.category = ?"
            parameters.append(category)
        query += " ORDER BY p.created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        products = conn.execute(query, tuple(parameters)).fetchall()
        conn.close()
        return products

    def build_experience_snapshot() -> dict[str, object]:
        products = fetch_active_products()
        total_products = len(products)
        categories: dict[str, int] = {}
        price_tiers = {"entry": 0, "core": 0, "premium": 0}
        avg_price = Decimal("0")

        if total_products:
            avg_price = sum(Decimal(str(product["price"])) for product in products) / Decimal(total_products)

        for product in products:
            category = (product["category"] or "Unclassified").strip() or "Unclassified"
            categories[category] = categories.get(category, 0) + 1
            price = float(product["price"])
            if price < 50:
                price_tiers["entry"] += 1
            elif price < 200:
                price_tiers["core"] += 1
            else:
                price_tiers["premium"] += 1

        recent_products = [
            {
                "id": product["id"],
                "name": product["name"],
                "description": product["description"],
                "price": float(product["price"]),
                "first_image_id": product["first_image_id"],
            }
            for product in products[:6]
        ]

        catalog_health = 0
        if total_products:
            weighted_diversity = min(len(categories) * 15, 60)
            weighted_premium_mix = min(price_tiers["premium"] * 8, 20)
            weighted_core_mix = min(price_tiers["core"] * 3, 20)
            catalog_health = min(weighted_diversity + weighted_premium_mix + weighted_core_mix, 100)

        return {
            "total_products": total_products,
            "total_categories": len(categories),
            "avg_price": float(avg_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "catalog_health": catalog_health,
            "top_categories": sorted(
                [{"name": name, "count": count} for name, count in categories.items()],
                key=lambda item: item["count"],
                reverse=True,
            )[:5],
            "price_tiers": price_tiers,
            "recent_products": recent_products,
        }

    @app.context_processor
    def inject_cart_metrics():
        settings = get_site_settings_payload()
        language_code = normalize_language(settings.get("language_code"))
        page_id = request.endpoint or "index"
        page_mapping = {
            "seo_page": "seo",
            "product_detail": "product",
        }
        resolved_page_id = page_mapping.get(page_id, page_id)
        return {
            "cart_count": cart_count(),
            "site_settings": settings,
            "currency": get_currency_payload(),
            "format_money": format_money,
            "current_language": language_code,
            "tr": lambda key: tr(language_code, key),
            "page_customization": get_page_customization(resolved_page_id),
        }

    def login_required(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash(t("auth_login_required"))
                return redirect(url_for("login"))
            return view_func(*args, **kwargs)

        return wrapper

    @app.route("/api/site-settings")
    def api_site_settings():
        return jsonify(get_site_settings_payload())

    @app.route("/api/products")
    def api_products():
        category = request.args.get("category", "").strip() or None
        limit_raw = request.args.get("limit", "").strip()
        limit: int | None = None
        if limit_raw:
            if not limit_raw.isdigit():
                return jsonify({"error": "Le paramètre limit doit être un entier positif."}), 400
            limit = max(1, min(int(limit_raw), 100))

        products = fetch_active_products(category=category, limit=limit)
        return jsonify(
            {
                "count": len(products),
                "products": [serialize_product(product) for product in products],
            }
        )

    @app.route("/api/products/<int:product_id>")
    def api_product_detail(product_id: int):
        conn = get_connection()
        product = conn.execute(
            """
            SELECT p.*, (
                SELECT id FROM product_images
                WHERE product_id = p.id
                ORDER BY position LIMIT 1
            ) AS first_image_id
            FROM products p
            WHERE p.id = ? AND p.status = ? AND p.archived = 0
            """,
            (product_id, "active"),
        ).fetchone()
        if not product:
            conn.close()
            return jsonify({"error": "Produit introuvable."}), 404
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

        payload = serialize_product(product)
        payload["images"] = [
            {
                "id": image["id"],
                "mime_type": image["mime_type"],
                "url": url_for("product_image", product_id=product_id, image_id=image["id"]),
            }
            for image in images
        ]
        payload["inventory"] = [
            {"color": row["color"], "size": row["size"], "quantity": int(row["quantity"])}
            for row in inventory
        ]
        return jsonify(payload)

    @app.route("/api/experience")
    def api_experience():
        return jsonify(build_experience_snapshot())

    @app.route("/")
    def index():
        products = fetch_active_products()
        snapshot = build_experience_snapshot()
        return render_template(
            "index.html",
            products=products,
            snapshot=snapshot,
            paypal_client_id=get_paypal_settings()["client_id"],
            paypal_env=get_paypal_settings()["env"],
            site_settings=get_site_settings_payload(),
            page_id="index",
        )

    @app.route("/policy")
    def policy():
        return render_template("policy.html", page_id="policy")

    @app.route("/seo")
    def seo_page():
        return render_template("seo.html", page_id="seo")

    @app.route("/robots.txt")
    def robots_txt():
        robots = "\n".join(
            [
                "User-agent: *",
                "Allow: /",
                f"Sitemap: {url_for('sitemap_xml', _external=True)}",
            ]
        )
        return app.response_class(robots, mimetype="text/plain")

    @app.route("/sitemap.xml")
    def sitemap_xml():
        pages = [
            url_for("index", _external=True),
            url_for("policy", _external=True),
            url_for("seo_page", _external=True),
            url_for("experience", _external=True),
        ]
        xml_urls = "\n".join(
            [f"<url><loc>{page}</loc></url>" for page in pages]
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{xml_urls}\n"
            "</urlset>"
        )
        return app.response_class(xml, mimetype="application/xml")

    @app.route("/experience")
    def experience():
        snapshot = build_experience_snapshot()
        return render_template("experience.html", snapshot=snapshot, page_id="experience")

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
            flash(t("product_not_found"))
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
            page_id="product",
        )

    @app.route("/cart")
    def cart():
        items, subtotal = load_cart_items()
        shipping_fee = get_shipping_fee()
        total = subtotal + (shipping_fee if items else 0.0)
        return render_template(
            "cart.html",
            items=items,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            total=total,
            page_id="cart",
        )

    @app.route("/cart/add/<int:product_id>", methods=["POST"])
    def add_to_cart(product_id: int):
        color = request.form.get("color", "").strip()
        size = request.form.get("size", "").strip()
        conn = get_connection()
        product = conn.execute("SELECT id, status, archived FROM products WHERE id = ?", (product_id,)).fetchone()
        inventory_row = conn.execute(
            """
            SELECT quantity
            FROM product_inventory
            WHERE product_id = ? AND color = ? AND size = ?
            """,
            (product_id, color, size),
        ).fetchone()
        conn.close()
        if not product or product["status"] != "active" or product["archived"]:
            flash(t("product_unavailable"))
            return redirect(url_for("index"))
        if not color or not size:
            flash(t("select_color_size"))
            return redirect(url_for("product_detail", product_id=product_id))
        if not inventory_row or inventory_row["quantity"] <= 0:
            flash(t("out_of_stock"))
            return redirect(url_for("product_detail", product_id=product_id))
        cart = get_cart()
        cart_key = build_cart_key(product_id, color, size)
        current_quantity = cart.get(cart_key, 0)
        if current_quantity + 1 > inventory_row["quantity"]:
            flash(t("insufficient_stock_variant"))
            return redirect(url_for("product_detail", product_id=product_id))
        cart[cart_key] = current_quantity + 1
        session["cart"] = cart
        flash(t("added_to_cart"))
        return redirect(url_for("cart"))

    @app.route("/cart/update", methods=["POST"])
    def update_cart_item():
        quantity_str = request.form.get("quantity", "").strip()
        cart_key = request.form.get("cart_key", "").strip()
        if not quantity_str.isdigit():
            flash(t("invalid_quantity"))
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
                    flash(t("insufficient_stock_variant"))
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
            "SELECT image_blob, image_path, mime_type FROM product_images WHERE id = ? AND product_id = ?",
            (image_id, product_id),
        ).fetchone()
        conn.close()
        if not image:
            return "", 404
        if image["image_path"]:
            path = resolve_image_path(image["image_path"])
            if path.exists():
                return send_file(path, mimetype=image["mime_type"] or "image/jpeg")
        if image["image_blob"] is not None:
            return send_file(io.BytesIO(image["image_blob"]), mimetype=image["mime_type"] or "image/jpeg")
        return "", 404

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            full_name = request.form.get("full_name", "").strip()
            password = request.form.get("password", "")
            if not email or not full_name or not password:
                flash(t("all_fields_required"))
                return redirect(url_for("register"))
            password_hash = hash_password(password)
            conn = get_connection()
            try:
                conn.execute(
                    "INSERT INTO users (email, password_hash, full_name, created_at) VALUES (?, ?, ?, ?)",
                    (email, password_hash, full_name, datetime.utcnow().isoformat()),
                )
                conn.commit()
            except Exception:
                conn.close()
                flash(t("account_exists_or_save_error"))
                return redirect(url_for("register"))
            conn.close()
            flash(t("account_created_login"))
            return redirect(url_for("login"))
        return render_template("register.html", page_id="register")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            now = datetime.utcnow()
            attempts = login_attempts.get(email, [])
            attempts = [attempt for attempt in attempts if now - attempt < login_limit_window]
            if len(attempts) >= login_limit_max_attempts:
                flash("Trop de tentatives. Réessayez dans quelques minutes.")
                return redirect(url_for("login"))
            conn = get_connection()
            user = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            conn.close()
            if not user or not verify_password(password, str(user["password_hash"])):
                attempts.append(now)
                login_attempts[email] = attempts
                flash(t("invalid_credentials"))
                return redirect(url_for("login"))
            login_attempts.pop(email, None)
            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            return redirect(url_for("index"))
        return render_template("login.html", page_id="login")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/checkout")
    @login_required
    def checkout():
        items, subtotal = load_cart_items()
        if not items:
            flash(t("empty_cart"))
            return redirect(url_for("cart"))
        shipping_fee = get_shipping_fee()
        total = subtotal + shipping_fee
        currency = get_currency_payload()
        return render_template(
            "checkout.html",
            paypal_client_id=get_paypal_settings()["client_id"],
            paypal_env=get_paypal_settings()["env"],
            paypal_debug_enabled=paypal_debug_enabled(),
            items=items,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            total=total,
            paypal_configured=ensure_paypal_configured()[0],
            paypal_currency_code=currency["code"],
            page_id="checkout",
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
            return jsonify({"error": t("shipping_address_incomplete")}), 400
        items, subtotal = load_cart_items()
        if not items:
            app.logger.warning("[paypal-debug] create_order rejected: empty cart")
            return jsonify({"error": "Votre panier est vide."}), 400
        subtotal_money = to_money(subtotal)
        shipping_fee = get_shipping_fee()
        shipping_fee_money = to_money(shipping_fee)
        total_money = to_money(subtotal_money + shipping_fee_money)
        currency_code = get_currency_payload()["code"]
        paypal_items = []
        for item in items:
            unit_amount = to_money(item["product"]["price"])
            paypal_items.append(
                {
                    "name": item["product"]["name"][:127],
                    "description": f"Couleur: {item['color']} / Taille: {item['size']}"[:127],
                    "sku": f"{item['product']['id']}-{item['color']}-{item['size']}"[:127],
                    "unit_amount": {
                        "currency_code": currency_code,
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
                shipping_fee,
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
                return jsonify({"error": t("insufficient_stock_checkout")}), 409
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
                                "currency_code": currency_code,
                                "value": money_as_text(total_money),
                                "breakdown": {
                                    "item_total": {
                                        "currency_code": currency_code,
                                        "value": money_as_text(subtotal_money),
                                    },
                                    "shipping": {
                                        "currency_code": currency_code,
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
            log_payment_event(
                event="create_paypal_order",
                status="error",
                order_id=order_id,
                request_payload={"currency_code": currency_code, "total": money_as_text(total_money)},
                error_message=str(exc),
            )
            app.logger.exception(
                "[paypal-debug] paypal order creation failed local_order_id=%s",
                order_id,
            )
            return jsonify({"error": str(exc)}), 502
        paypal_order_id = paypal_order.get("id")
        if not paypal_order_id:
            conn.rollback()
            conn.close()
            log_payment_event(
                event="create_paypal_order",
                status="error",
                order_id=order_id,
                response_payload=paypal_order,
                error_message="missing_paypal_order_id",
            )
            app.logger.error(
                "[paypal-debug] paypal order creation invalid response local_order_id=%s payload=%s",
                order_id,
                paypal_order,
            )
            return jsonify({"error": t("invalid_paypal_response")}), 502
        cursor.execute(
            "UPDATE orders SET payment_status = ?, paypal_order_id = ? WHERE id = ?",
            (f"paypal_order:{paypal_order_id}", paypal_order_id, order_id),
        )
        conn.commit()
        conn.close()
        log_payment_event(
            event="create_paypal_order",
            status="success",
            order_id=order_id,
            response_payload={"paypal_order_id": paypal_order_id},
        )
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
                WHERE (paypal_order_id = ? OR payment_status = ?) AND customer_email = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (paypal_order_id, f"paypal_order:{paypal_order_id}", current_user["email"]),
            ).fetchone()
        if not order:
            conn.close()
            app.logger.warning("[paypal-debug] capture_order rejected: order not found")
            return {"error": t("order_not_found")}, 404
        if order["customer_email"] != current_user["email"]:
            conn.close()
            app.logger.warning(
                "[paypal-debug] capture_order rejected: email mismatch local_order_id=%s",
                order["id"],
            )
            return {"error": "Accès non autorisé à cette commande."}, 403
        if str(order["payment_status"]).startswith("paid:"):
            conn.close()
            app.logger.info(
                "[paypal-debug] capture_order idempotent return local_order_id=%s",
                order["id"],
            )
            return {
                "ok": True,
                "redirect_url": url_for("checkout_success", order_id=order["id"]),
            }, 200
        expected_payment_status = f"paypal_order:{paypal_order_id}"
        if order["paypal_order_id"] and order["paypal_order_id"] != paypal_order_id:
            conn.close()
            app.logger.warning(
                "[paypal-debug] capture_order rejected: paypal id mismatch local_order_id=%s",
                order["id"],
            )
            return {"error": t("paypal_order_mismatch")}, 409
        if not order["paypal_order_id"] and expected_payment_status != order["payment_status"]:
            conn.close()
            app.logger.warning(
                "[paypal-debug] capture_order rejected: payment status mismatch local_order_id=%s status=%s",
                order["id"],
                order["payment_status"],
            )
            return {"error": t("paypal_order_mismatch")}, 409
        local_order_id = order["id"]
        try:
            capture = paypal_request(
                f"/v2/checkout/orders/{paypal_order_id}/capture",
                method="POST",
                payload={},
            )
        except RuntimeError as exc:
            conn.close()
            log_payment_event(
                event="capture_paypal_order",
                status="error",
                order_id=local_order_id,
                request_payload={"paypal_order_id": paypal_order_id},
                error_message=str(exc),
            )
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
        expected_currency = get_currency_payload()["code"]
        if reference_id and reference_id != expected_reference:
            conn.close()
            app.logger.error(
                "[paypal-debug] capture_order rejected: reference mismatch local_order_id=%s expected=%s got=%s",
                local_order_id,
                expected_reference,
                reference_id,
            )
            return {"error": t("paypal_order_mismatch_reference")}, 409
        if capture_currency and capture_currency != expected_currency:
            conn.close()
            app.logger.error(
                "[paypal-debug] capture_order rejected: currency mismatch local_order_id=%s expected=%s got=%s",
                local_order_id,
                expected_currency,
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
        try:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute(
                "SELECT * FROM orders WHERE id = ?",
                (local_order_id,),
            ).fetchone()
            if not order:
                conn.rollback()
                conn.close()
                return {"error": t("order_not_found")}, 404
            if str(order["payment_status"]).startswith("paid:"):
                conn.rollback()
                conn.close()
                app.logger.info(
                    "[paypal-debug] capture_order idempotent after paypal local_order_id=%s",
                    local_order_id,
                )
                return {
                    "ok": True,
                    "redirect_url": url_for("checkout_success", order_id=local_order_id),
                }, 200
            if order["capture_id"] and capture_id and order["capture_id"] != capture_id:
                conn.rollback()
                conn.close()
                return {"error": "Cette commande est déjà associée à une autre capture PayPal."}, 409

            order_items = conn.execute(
                "SELECT * FROM order_items WHERE order_id = ?",
                (local_order_id,),
            ).fetchall()
            cursor = conn.cursor()
            for item in order_items:
                inventory = conn.execute(
                    """
                    SELECT id
                    FROM product_inventory
                    WHERE product_id = ? AND color = ? AND size = ?
                    """,
                    (item["product_id"], item["color"], item["size"]),
                ).fetchone()
                if not inventory:
                    conn.rollback()
                    conn.close()
                    app.logger.warning(
                        "[paypal-debug] capture_order rejected: missing stock row local_order_id=%s product_id=%s",
                        local_order_id,
                        item["product_id"],
                    )
                    return {"error": t("insufficient_stock_after_payment")}, 409
                cursor.execute(
                    """
                    UPDATE product_inventory
                    SET quantity = quantity - ?
                    WHERE id = ? AND quantity >= ?
                    """,
                    (item["quantity"], inventory["id"], item["quantity"]),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    conn.close()
                    app.logger.warning(
                        "[paypal-debug] capture_order rejected: concurrent stock issue local_order_id=%s product_id=%s",
                        local_order_id,
                        item["product_id"],
                    )
                    return {"error": t("insufficient_stock_after_payment")}, 409
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
                SET status = ?, payment_status = ?, paypal_order_id = COALESCE(paypal_order_id, ?), capture_id = COALESCE(capture_id, ?)
                WHERE id = ? AND payment_status NOT LIKE 'paid:%'
                """,
                (
                    "confirmed",
                    f"paid:{capture_id or paypal_order_id}",
                    paypal_order_id,
                    capture_id,
                    local_order_id,
                ),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                conn.close()
                return {
                    "ok": True,
                    "redirect_url": url_for("checkout_success", order_id=local_order_id),
                }, 200
            cursor.execute(
                "INSERT INTO transactions (order_id, completed_at, total) VALUES (?, ?, ?)",
                (local_order_id, datetime.utcnow().isoformat(), order["total"]),
            )
            conn.commit()
            conn.close()
        except Exception:
            conn.rollback()
            conn.close()
            app.logger.exception(
                "[paypal-debug] capture_order transaction failed local_order_id=%s paypal_order_id=%s",
                local_order_id,
                paypal_order_id,
            )
            return {"error": "Erreur transactionnelle pendant la confirmation PayPal."}, 500
        log_payment_event(
            event="capture_paypal_order",
            status="success",
            order_id=local_order_id,
            request_payload={"paypal_order_id": paypal_order_id},
            response_payload={"capture_id": capture_id, "status": status},
        )
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
            flash(response.get("error") or t("paypal_payment_not_confirmed"))
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
        flash(t("paypal_payment_cancelled_retry"))
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
            flash(t("order_not_confirmed"))
            return redirect(url_for("checkout"))
        return render_template("checkout_success.html", order=order, page_id="checkout_success")

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
