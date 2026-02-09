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


def create_app():
    app = Flask(
        __name__,
        static_folder=str(os.path.join(os.path.dirname(__file__), "..", "assets")),
        template_folder=str(os.path.join(os.path.dirname(__file__), "..", "templates")),
    )
    app.secret_key = os.getenv("ELIT21_SECRET", "elit21-secret")

    init_db()

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
        conn.close()
        if not product:
            flash("Article introuvable.")
            return redirect(url_for("index"))
        return render_template("product.html", product=product, images=images)

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
        return render_template(
            "checkout.html",
            paypal_client_id=PAYPAL_CLIENT_ID,
            paypal_env=PAYPAL_ENV,
        )

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=True)
