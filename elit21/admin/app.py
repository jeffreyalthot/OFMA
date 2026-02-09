from __future__ import annotations

import io
from datetime import datetime
from tkinter import (
    Tk,
    StringVar,
    Text,
    ttk,
    filedialog,
    messagebox,
    Label,
)

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover - optional dependency
    Image = None
    ImageTk = None

from elit21.db import get_connection, init_db


MAX_IMAGES = 8


class AdminApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("ELIT21 - Gestionnaire")
        self.root.geometry("1200x750")

        init_db()

        self.selected_images: list[tuple[bytes, str]] = []
        self.image_previews: list[ImageTk.PhotoImage] = []

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        self.dashboard_tab = ttk.Frame(notebook)
        self.products_tab = ttk.Frame(notebook)
        self.orders_tab = ttk.Frame(notebook)
        self.transactions_tab = ttk.Frame(notebook)

        notebook.add(self.dashboard_tab, text="Dashboard Finance")
        notebook.add(self.products_tab, text="Gestion Articles")
        notebook.add(self.orders_tab, text="Gestion Commandes")
        notebook.add(self.transactions_tab, text="Transactions Complétées")

        self._build_dashboard()
        self._build_products_tab()
        self._build_orders_tab()
        self._build_transactions_tab()

        self.refresh_all()

    def _build_dashboard(self) -> None:
        self.dashboard_cards = {}
        container = ttk.Frame(self.dashboard_tab, padding=20)
        container.pack(fill="both", expand=True)

        for label in (
            "Total commandes",
            "Commandes en traitement",
            "Chiffre d'affaires",
            "Articles actifs",
        ):
            frame = ttk.Frame(container, padding=15, relief="ridge")
            frame.pack(side="left", padx=10, pady=10, expand=True, fill="both")
            ttk.Label(frame, text=label, font=("Segoe UI", 12, "bold")).pack(anchor="w")
            value_label = ttk.Label(frame, text="0", font=("Segoe UI", 24, "bold"))
            value_label.pack(anchor="w", pady=10)
            self.dashboard_cards[label] = value_label

    def _build_products_tab(self) -> None:
        container = ttk.Frame(self.products_tab, padding=20)
        container.pack(fill="both", expand=True)

        form_frame = ttk.Labelframe(container, text="Ajouter un article", padding=15)
        form_frame.pack(side="left", fill="y", padx=10)

        self.product_name = StringVar()
        self.product_price = StringVar()
        self.product_stock = StringVar()
        self.product_status = StringVar(value="pending")

        ttk.Label(form_frame, text="Nom").pack(anchor="w")
        ttk.Entry(form_frame, textvariable=self.product_name, width=35).pack(anchor="w")

        ttk.Label(form_frame, text="Description").pack(anchor="w", pady=(10, 0))
        self.product_description = Text(form_frame, width=40, height=6)
        self.product_description.pack(anchor="w")

        ttk.Label(form_frame, text="Prix (€)").pack(anchor="w", pady=(10, 0))
        ttk.Entry(form_frame, textvariable=self.product_price, width=20).pack(anchor="w")

        ttk.Label(form_frame, text="Stock").pack(anchor="w", pady=(10, 0))
        ttk.Entry(form_frame, textvariable=self.product_stock, width=20).pack(anchor="w")

        ttk.Label(form_frame, text="Statut").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(
            form_frame,
            textvariable=self.product_status,
            values=["pending", "active", "inactive"],
            state="readonly",
            width=18,
        ).pack(anchor="w")

        ttk.Button(form_frame, text="Ajouter images", command=self.load_images).pack(
            anchor="w", pady=10
        )
        self.images_label = ttk.Label(form_frame, text="0 image(s) sélectionnée(s)")
        self.images_label.pack(anchor="w")

        ttk.Button(form_frame, text="Enregistrer", command=self.save_product).pack(
            anchor="w", pady=15
        )

        list_frame = ttk.Labelframe(container, text="Articles", padding=15)
        list_frame.pack(side="left", fill="both", expand=True)

        columns = ("id", "name", "status", "price", "stock")
        self.products_tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        for col in columns:
            self.products_tree.heading(col, text=col.capitalize())
            self.products_tree.column(col, width=120)
        self.products_tree.pack(side="left", fill="both", expand=True)
        self.products_tree.bind("<<TreeviewSelect>>", self.show_product_preview)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.products_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.products_tree.configure(yscrollcommand=scrollbar.set)

        preview_frame = ttk.Labelframe(container, text="Aperçu image", padding=15)
        preview_frame.pack(side="left", fill="y", padx=10)
        self.preview_label = Label(preview_frame, text="Aucune image")
        self.preview_label.pack()

    def _build_orders_tab(self) -> None:
        container = ttk.Frame(self.orders_tab, padding=20)
        container.pack(fill="both", expand=True)

        list_frame = ttk.Frame(container)
        list_frame.pack(side="left", fill="both", expand=True)

        columns = ("id", "client", "status", "payment", "total", "date")
        self.orders_tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        for col in columns:
            self.orders_tree.heading(col, text=col.capitalize())
            self.orders_tree.column(col, width=140)
        self.orders_tree.pack(side="left", fill="both", expand=True)
        self.orders_tree.bind("<<TreeviewSelect>>", self.show_order_detail)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.orders_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.orders_tree.configure(yscrollcommand=scrollbar.set)

        detail_frame = ttk.Labelframe(container, text="Détail commande", padding=15)
        detail_frame.pack(side="left", fill="both", padx=15)

        self.order_detail_label = ttk.Label(detail_frame, text="Sélectionnez une commande")
        self.order_detail_label.pack(anchor="w")

        items_frame = ttk.Labelframe(detail_frame, text="Articles commandés", padding=10)
        items_frame.pack(fill="both", expand=True, pady=10)
        item_columns = ("article", "quantite", "prix")
        self.order_items_tree = ttk.Treeview(items_frame, columns=item_columns, show="headings", height=6)
        self.order_items_tree.heading("article", text="Article")
        self.order_items_tree.heading("quantite", text="Qté")
        self.order_items_tree.heading("prix", text="Prix")
        self.order_items_tree.column("article", width=180)
        self.order_items_tree.column("quantite", width=60)
        self.order_items_tree.column("prix", width=80)
        self.order_items_tree.pack(side="left", fill="both", expand=True)
        items_scrollbar = ttk.Scrollbar(items_frame, orient="vertical", command=self.order_items_tree.yview)
        items_scrollbar.pack(side="right", fill="y")
        self.order_items_tree.configure(yscrollcommand=items_scrollbar.set)

        ttk.Button(detail_frame, text="Marquer en traitement", command=lambda: self.update_order_status("processing")).pack(
            fill="x", pady=5
        )
        ttk.Button(detail_frame, text="Marquer acceptée", command=lambda: self.update_order_status("accepted")).pack(
            fill="x", pady=5
        )
        ttk.Button(detail_frame, text="Marquer complétée", command=self.complete_order).pack(
            fill="x", pady=5
        )

    def _build_transactions_tab(self) -> None:
        container = ttk.Frame(self.transactions_tab, padding=20)
        container.pack(fill="both", expand=True)

        columns = ("id", "order_id", "total", "completed_at")
        self.transactions_tree = ttk.Treeview(container, columns=columns, show="headings")
        for col in columns:
            self.transactions_tree.heading(col, text=col.capitalize())
            self.transactions_tree.column(col, width=180)
        self.transactions_tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.transactions_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.transactions_tree.configure(yscrollcommand=scrollbar.set)

    def load_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Sélectionner des images",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")],
        )
        if not paths:
            return
        self.selected_images.clear()
        self.image_previews.clear()

        for path in paths[:MAX_IMAGES]:
            with open(path, "rb") as file:
                data = file.read()
            mime_type = "image/jpeg"
            if path.lower().endswith(".png"):
                mime_type = "image/png"
            elif path.lower().endswith(".webp"):
                mime_type = "image/webp"
            self.selected_images.append((data, mime_type))

        self.images_label.config(text=f"{len(self.selected_images)} image(s) sélectionnée(s)")

    def save_product(self) -> None:
        name = self.product_name.get().strip()
        description = self.product_description.get("1.0", "end").strip()
        price = self.product_price.get().strip()
        stock = self.product_stock.get().strip()
        status = self.product_status.get().strip()

        if not name or not description or not price or not stock:
            messagebox.showerror("Erreur", "Tous les champs sont requis.")
            return

        try:
            price_value = float(price)
            stock_value = int(stock)
        except ValueError:
            messagebox.showerror("Erreur", "Prix ou stock invalide.")
            return

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO products (name, description, price, status, stock, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, price_value, status, stock_value, datetime.utcnow().isoformat()),
        )
        product_id = cursor.lastrowid

        for idx, (data, mime_type) in enumerate(self.selected_images):
            cursor.execute(
                "INSERT INTO product_images (product_id, image_blob, mime_type, position) VALUES (?, ?, ?, ?)",
                (product_id, data, mime_type, idx),
            )

        conn.commit()
        conn.close()

        self.product_name.set("")
        self.product_description.delete("1.0", "end")
        self.product_price.set("")
        self.product_stock.set("")
        self.product_status.set("pending")
        self.selected_images.clear()
        self.images_label.config(text="0 image(s) sélectionnée(s)")

        self.refresh_all()
        messagebox.showinfo("Succès", "Article enregistré.")

    def refresh_all(self) -> None:
        self.refresh_dashboard()
        self.refresh_products()
        self.refresh_orders()
        self.refresh_transactions()

    def refresh_dashboard(self) -> None:
        conn = get_connection()
        total_orders = conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
        processing_orders = conn.execute(
            "SELECT COUNT(*) AS count FROM orders WHERE status = ?",
            ("processing",),
        ).fetchone()["count"]
        revenue = conn.execute("SELECT COALESCE(SUM(total), 0) AS total FROM transactions").fetchone()["total"]
        active_products = conn.execute(
            "SELECT COUNT(*) AS count FROM products WHERE status = ?",
            ("active",),
        ).fetchone()["count"]
        conn.close()

        self.dashboard_cards["Total commandes"].config(text=str(total_orders))
        self.dashboard_cards["Commandes en traitement"].config(text=str(processing_orders))
        self.dashboard_cards["Chiffre d'affaires"].config(text=f"€ {revenue:.2f}")
        self.dashboard_cards["Articles actifs"].config(text=str(active_products))

    def refresh_products(self) -> None:
        for item in self.products_tree.get_children():
            self.products_tree.delete(item)

        conn = get_connection()
        products = conn.execute(
            "SELECT id, name, status, price, stock FROM products ORDER BY created_at DESC"
        ).fetchall()
        conn.close()

        for product in products:
            self.products_tree.insert(
                "",
                "end",
                values=(
                    product["id"],
                    product["name"],
                    product["status"],
                    f"€ {product['price']:.2f}",
                    product["stock"],
                ),
            )
        self.preview_label.config(text="Aucune image", image="")
        self.preview_label.image = None

    def show_product_preview(self, _event=None) -> None:
        selected = self.products_tree.selection()
        if not selected:
            return
        product_id = int(self.products_tree.item(selected[0])["values"][0])
        conn = get_connection()
        image = conn.execute(
            "SELECT image_blob, mime_type FROM product_images WHERE product_id = ? ORDER BY position LIMIT 1",
            (product_id,),
        ).fetchone()
        conn.close()

        if not image:
            self.preview_label.config(text="Aucune image", image="")
            self.preview_label.image = None
            return

        if Image is None or ImageTk is None:
            self.preview_label.config(text="Pillow requis pour l'aperçu", image="")
            self.preview_label.image = None
            return

        data = image["image_blob"]
        img = Image.open(io.BytesIO(data))
        img.thumbnail((220, 220))
        photo = ImageTk.PhotoImage(img)
        self.preview_label.config(image=photo, text="")
        self.preview_label.image = photo

    def refresh_orders(self) -> None:
        for item in self.orders_tree.get_children():
            self.orders_tree.delete(item)

        conn = get_connection()
        orders = conn.execute(
            "SELECT * FROM orders WHERE status != ? ORDER BY created_at DESC",
            ("completed",),
        ).fetchall()
        conn.close()

        for order in orders:
            self.orders_tree.insert(
                "",
                "end",
                iid=str(order["id"]),
                values=(
                    order["id"],
                    order["customer_name"],
                    order["status"],
                    order["payment_status"],
                    f"€ {order['total']:.2f}",
                    order["created_at"],
                ),
            )

    def refresh_transactions(self) -> None:
        for item in self.transactions_tree.get_children():
            self.transactions_tree.delete(item)

        conn = get_connection()
        transactions = conn.execute(
            "SELECT * FROM transactions ORDER BY completed_at DESC"
        ).fetchall()
        conn.close()

        for tx in transactions:
            self.transactions_tree.insert(
                "",
                "end",
                values=(tx["id"], tx["order_id"], f"€ {tx['total']:.2f}", tx["completed_at"]),
            )

    def show_order_detail(self, _event=None) -> None:
        selected = self.orders_tree.selection()
        if not selected:
            return
        order_id = int(selected[0])
        conn = get_connection()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        items = conn.execute(
            "SELECT product_name, quantity, price FROM order_items WHERE order_id = ?",
            (order_id,),
        ).fetchall()
        conn.close()

        if not order:
            return
        for row in self.order_items_tree.get_children():
            self.order_items_tree.delete(row)
        for item in items:
            self.order_items_tree.insert(
                "",
                "end",
                values=(
                    item["product_name"],
                    item["quantity"],
                    f"€ {item['price']:.2f}",
                ),
            )
        detail = (
            f"Client: {order['customer_name']}\n"
            f"Email: {order['customer_email']}\n"
            f"Adresse complète: {order['customer_address']}\n"
            f"Date achat: {order['created_at']}\n"
            f"Statut: {order['status']}\n"
            f"Paiement: {order['payment_status']}\n"
            f"Livraison: € {order['shipping_fee']:.2f}\n"
            f"Total TTC: € {order['total']:.2f}"
        )
        self.order_detail_label.config(text=detail)

    def update_order_status(self, status: str) -> None:
        selected = self.orders_tree.selection()
        if not selected:
            messagebox.showwarning("Info", "Sélectionnez une commande.")
            return
        order_id = int(selected[0])
        conn = get_connection()
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        conn.commit()
        conn.close()
        self.refresh_orders()
        self.refresh_dashboard()
        self.show_order_detail()

    def complete_order(self) -> None:
        selected = self.orders_tree.selection()
        if not selected:
            messagebox.showwarning("Info", "Sélectionnez une commande.")
            return
        order_id = int(selected[0])
        conn = get_connection()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            conn.close()
            return
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", ("completed", order_id))
        conn.execute(
            "INSERT INTO transactions (order_id, completed_at, total) VALUES (?, ?, ?)",
            (order_id, datetime.utcnow().isoformat(), order["total"]),
        )
        conn.commit()
        conn.close()
        self.refresh_all()


def main():
    root = Tk()
    app = AdminApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
