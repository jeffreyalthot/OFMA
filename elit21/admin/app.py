from __future__ import annotations

import io
import html
from datetime import datetime
from tkinter import (
    Canvas,
    Tk,
    IntVar,
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
COLOR_OPTIONS = [
    "",
    "Noir",
    "Blanc",
    "Rouge",
    "Bleu",
    "Vert",
    "Jaune",
    "Orange",
    "Rose",
    "Violet",
    "Gris",
    "Marron",
    "Beige",
    "Marine",
    "Turquoise",
]
SIZE_OPTIONS = ["", "S", "M", "L", "XL", "XXL"]
CATEGORY_OPTIONS = [
    "",
    "Chapeaux",
    "Chandails",
    "Vestes",
    "Polars",
    "Pantalons",
    "Gants",
    "Souliers",
    "Chaussettes",
]

COLOR_SWATCHES = {
    "Noir": "#000000",
    "Blanc": "#ffffff",
    "Rouge": "#e74c3c",
    "Bleu": "#3498db",
    "Vert": "#2ecc71",
    "Jaune": "#f1c40f",
    "Orange": "#e67e22",
    "Rose": "#fd79a8",
    "Violet": "#9b59b6",
    "Gris": "#95a5a6",
    "Marron": "#8e6e53",
    "Beige": "#f5f5dc",
    "Marine": "#2c3e50",
    "Turquoise": "#1abc9c",
}


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
        self.inventory_tab = ttk.Frame(notebook)
        self.orders_tab = ttk.Frame(notebook)
        self.transactions_tab = ttk.Frame(notebook)

        notebook.add(self.dashboard_tab, text="Dashboard Finance")
        notebook.add(self.products_tab, text="Gestion Articles")
        notebook.add(self.inventory_tab, text="Gestion Inventaire")
        notebook.add(self.orders_tab, text="Gestion Commandes")
        notebook.add(self.transactions_tab, text="Transactions Complétées")

        self._build_dashboard()
        self._build_products_tab()
        self._build_inventory_tab()
        self._build_orders_tab()
        self._build_transactions_tab()

        self.refresh_all()

    def _build_dashboard(self) -> None:
        self.dashboard_cards = {}
        container = ttk.Frame(self.dashboard_tab, padding=20)
        container.pack(fill="both", expand=True)

        cards_frame = ttk.Frame(container)
        cards_frame.pack(fill="x", anchor="n")

        for label in (
            "Total commandes",
            "Commandes en traitement",
            "Chiffre d'affaires",
            "Articles actifs",
        ):
            frame = ttk.Frame(cards_frame, padding=10, relief="ridge")
            frame.pack(side="left", padx=8, pady=(2, 8), expand=True, fill="x")
            ttk.Label(frame, text=label, font=("Segoe UI", 12, "bold")).pack(anchor="w")
            value_label = ttk.Label(frame, text="0", font=("Segoe UI", 24, "bold"))
            value_label.pack(anchor="w", pady=6)
            self.dashboard_cards[label] = value_label

        charts_frame = ttk.Frame(container)
        charts_frame.pack(fill="both", expand=True, pady=(0, 12))

        bar_card = ttk.Labelframe(charts_frame, text="Ventes & Commandes (7 jours)", padding=10)
        bar_card.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.sales_canvas = ttk.Frame(bar_card)
        self.sales_canvas.pack(fill="both", expand=True)
        self.sales_chart = Canvas(self.sales_canvas, bg="#ffffff", highlightthickness=0)
        self.sales_chart.pack(fill="both", expand=True)

        pie_card = ttk.Labelframe(charts_frame, text="Répartition revenus / jour (7 jours)", padding=10)
        pie_card.pack(side="left", fill="both", expand=True)
        self.revenue_pie = Canvas(pie_card, bg="#ffffff", highlightthickness=0)
        self.revenue_pie.pack(fill="both", expand=True)

        export_frame = ttk.Labelframe(container, text="Export transactions", padding=12)
        export_frame.pack(fill="x", side="bottom")

        ttk.Label(export_frame, text="Plage de dates :").pack(side="left", padx=(0, 8))
        self.export_days = IntVar(value=7)
        for value in (1, 7, 15, 30):
            ttk.Radiobutton(
                export_frame,
                text=f"{value} jour" if value == 1 else f"{value} jours",
                value=value,
                variable=self.export_days,
            ).pack(side="left", padx=4)

        ttk.Button(
            export_frame,
            text="Exporter transactions (Excel)",
            command=self.export_transactions_excel,
        ).pack(side="right")

    def _build_products_tab(self) -> None:
        container = ttk.Frame(self.products_tab, padding=20)
        container.pack(fill="both", expand=True)

        form_frame = ttk.Labelframe(container, text="Ajouter/Gérer un article", padding=15)
        form_frame.pack(side="left", fill="y", padx=10)

        self.editing_product_id: int | None = None
        self.product_name = StringVar()
        self.product_price = StringVar()
        self.product_stock = StringVar()
        self.product_status = StringVar(value="pending")
        self.product_color = StringVar()
        self.product_size = StringVar()
        self.product_category = StringVar()

        ttk.Label(form_frame, text="Nom").pack(anchor="w")
        ttk.Entry(form_frame, textvariable=self.product_name, width=35).pack(anchor="w")

        ttk.Label(form_frame, text="Description").pack(anchor="w", pady=(10, 0))
        self.product_description = Text(form_frame, width=40, height=6)
        self.product_description.pack(anchor="w")

        ttk.Label(form_frame, text="Prix (€)").pack(anchor="w", pady=(10, 0))
        ttk.Entry(form_frame, textvariable=self.product_price, width=20).pack(anchor="w")

        ttk.Label(form_frame, text="Stock").pack(anchor="w", pady=(10, 0))
        ttk.Entry(form_frame, textvariable=self.product_stock, width=20).pack(anchor="w")

        ttk.Label(form_frame, text="Couleur").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(
            form_frame,
            textvariable=self.product_color,
            values=COLOR_OPTIONS,
            state="readonly",
            width=18,
        ).pack(anchor="w")

        ttk.Label(form_frame, text="Taille").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(
            form_frame,
            textvariable=self.product_size,
            values=SIZE_OPTIONS,
            state="readonly",
            width=18,
        ).pack(anchor="w")

        ttk.Label(form_frame, text="Catégorie").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(
            form_frame,
            textvariable=self.product_category,
            values=CATEGORY_OPTIONS,
            state="readonly",
            width=18,
        ).pack(anchor="w")

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
            anchor="w", pady=10
        )
        ttk.Button(form_frame, text="Nouveau", command=self.reset_product_form).pack(
            anchor="w", pady=(0, 15)
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

    def _build_inventory_tab(self) -> None:
        container = ttk.Frame(self.inventory_tab, padding=20)
        container.pack(fill="both", expand=True)

        form_frame = ttk.Labelframe(container, text="Mise à jour inventaire", padding=15)
        form_frame.pack(side="left", fill="y", padx=10)

        self.inventory_product = StringVar()
        self.inventory_color = StringVar()
        self.inventory_size = StringVar()
        self.inventory_quantity = StringVar()
        self.inventory_status = StringVar()
        self.inventory_products: dict[str, int] = {}

        ttk.Label(form_frame, text="Article").pack(anchor="w")
        self.inventory_product_combo = ttk.Combobox(
            form_frame,
            textvariable=self.inventory_product,
            state="readonly",
            width=28,
        )
        self.inventory_product_combo.pack(anchor="w")

        ttk.Label(form_frame, text="Couleur").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(
            form_frame,
            textvariable=self.inventory_color,
            values=COLOR_OPTIONS,
            state="readonly",
            width=18,
        ).pack(anchor="w")

        ttk.Label(form_frame, text="Taille").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(
            form_frame,
            textvariable=self.inventory_size,
            values=SIZE_OPTIONS,
            state="readonly",
            width=18,
        ).pack(anchor="w")

        ttk.Label(form_frame, text="Quantité").pack(anchor="w", pady=(10, 0))
        ttk.Entry(form_frame, textvariable=self.inventory_quantity, width=12).pack(anchor="w")

        ttk.Label(form_frame, text="Statut").pack(anchor="w", pady=(10, 0))
        ttk.Combobox(
            form_frame,
            textvariable=self.inventory_status,
            values=["pending", "active", "inactive"],
            state="readonly",
            width=18,
        ).pack(anchor="w")

        ttk.Button(
            form_frame,
            text="Mettre à jour inventaire",
            command=self.update_inventory,
        ).pack(anchor="w", pady=15)

        ttk.Button(
            form_frame,
            text="Mettre à jour statut",
            command=self.update_product_status,
        ).pack(anchor="w", pady=(0, 15))

        list_frame = ttk.Labelframe(container, text="Inventaire par variante", padding=15)
        list_frame.pack(side="left", fill="both", expand=True)

        columns = ("article", "statut", "couleur", "taille", "quantite")
        self.inventory_tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        for col in columns:
            self.inventory_tree.heading(col, text=col.capitalize())
            self.inventory_tree.column(col, width=130)
        self.inventory_tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.inventory_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.inventory_tree.configure(yscrollcommand=scrollbar.set)

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

        address_frame = ttk.Labelframe(detail_frame, text="Adresse client", padding=10)
        address_frame.pack(fill="x", pady=10)
        address_frame.configure(height=90)
        address_frame.pack_propagate(False)
        self.order_address_label = Label(
            address_frame,
            text="Adresse indisponible",
            justify="left",
            wraplength=320,
            height=4,
            anchor="w",
        )
        self.order_address_label.pack(fill="both", expand=True)

        buttons_frame = ttk.Frame(detail_frame)
        buttons_frame.pack(fill="x", pady=(10, 0))
        buttons_frame.columnconfigure(1, weight=1)
        indicator_frame = ttk.Frame(buttons_frame)
        indicator_frame.grid(row=0, column=0, rowspan=3, sticky="w")
        ttk.Label(indicator_frame, text="Couleur sélectionnée").grid(row=0, column=0, sticky="w")
        self.order_item_color_label = Label(
            indicator_frame,
            text="N/A",
            width=16,
            relief="solid",
            borderwidth=1,
            anchor="center",
        )
        self.order_item_color_label.grid(row=1, column=0, sticky="w", pady=(2, 8))
        ttk.Label(indicator_frame, text="Taille sélectionnée").grid(row=2, column=0, sticky="w")
        self.order_item_size_label = ttk.Label(indicator_frame, text="N/A")
        self.order_item_size_label.grid(row=3, column=0, sticky="w")
        ttk.Button(
            buttons_frame,
            text="Marquer en traitement",
            command=lambda: self.update_order_status("processing"),
        ).grid(row=0, column=1, sticky="e", pady=5)
        ttk.Button(
            buttons_frame,
            text="Marquer acceptée",
            command=lambda: self.update_order_status("accepted"),
        ).grid(row=1, column=1, sticky="e", pady=5)
        ttk.Button(
            buttons_frame,
            text="Marquer complétée",
            command=self.complete_order,
        ).grid(row=2, column=1, sticky="e", pady=5)

        items_frame = ttk.Labelframe(detail_frame, text="Articles commandés", padding=10)
        items_frame.pack(fill="both", expand=True, side="bottom", pady=(10, 0))
        item_columns = ("article", "quantite", "prix", "color", "size")
        self.order_items_tree = ttk.Treeview(
            items_frame,
            columns=item_columns,
            show="headings",
            displaycolumns=("article", "quantite", "prix"),
            height=6,
        )
        self.order_items_tree.heading("article", text="Article")
        self.order_items_tree.heading("quantite", text="Qté")
        self.order_items_tree.heading("prix", text="Prix")
        self.order_items_tree.column("article", width=180)
        self.order_items_tree.column("quantite", width=60)
        self.order_items_tree.column("prix", width=80)
        self.order_items_tree.pack(side="left", fill="both", expand=True)
        self.order_items_tree.bind("<<TreeviewSelect>>", self.update_order_item_indicator)
        items_scrollbar = ttk.Scrollbar(items_frame, orient="vertical", command=self.order_items_tree.yview)
        items_scrollbar.pack(side="right", fill="y")
        self.order_items_tree.configure(yscrollcommand=items_scrollbar.set)

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

    def reset_product_form(self) -> None:
        self.editing_product_id = None
        self.product_name.set("")
        self.product_description.delete("1.0", "end")
        self.product_price.set("")
        self.product_stock.set("")
        self.product_status.set("pending")
        self.product_color.set("")
        self.product_size.set("")
        self.product_category.set("")
        self.selected_images.clear()
        self.images_label.config(text="0 image(s) sélectionnée(s)")

    def load_product_for_edit(self, product_id: int) -> None:
        conn = get_connection()
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        conn.close()
        if not product:
            return
        self.editing_product_id = product_id
        self.product_name.set(product["name"])
        self.product_description.delete("1.0", "end")
        self.product_description.insert("1.0", product["description"])
        self.product_price.set(str(product["price"]))
        self.product_stock.set(str(product["stock"]))
        self.product_status.set(product["status"])
        self.product_color.set(product["color"] or "")
        self.product_size.set(product["size"] or "")
        self.product_category.set(product["category"] or "")
        self.selected_images.clear()
        self.images_label.config(text="0 image(s) sélectionnée(s)")

    def save_product(self) -> None:
        name = self.product_name.get().strip()
        description = self.product_description.get("1.0", "end").strip()
        price = self.product_price.get().strip()
        stock = self.product_stock.get().strip()
        status = self.product_status.get().strip()
        color = self.product_color.get().strip()
        size = self.product_size.get().strip()
        category = self.product_category.get().strip()

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
        if self.editing_product_id is None:
            cursor.execute(
                """
                INSERT INTO products (name, description, price, status, stock, color, size, category, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    description,
                    price_value,
                    status,
                    stock_value,
                    color or None,
                    size or None,
                    category or None,
                    datetime.utcnow().isoformat(),
                ),
            )
            product_id = cursor.lastrowid
        else:
            product_id = self.editing_product_id
            cursor.execute(
                """
                UPDATE products
                SET name = ?, description = ?, price = ?, status = ?, stock = ?, color = ?, size = ?, category = ?
                WHERE id = ?
                """,
                (
                    name,
                    description,
                    price_value,
                    status,
                    stock_value,
                    color or None,
                    size or None,
                    category or None,
                    product_id,
                ),
            )

        if self.selected_images:
            cursor.execute("DELETE FROM product_images WHERE product_id = ?", (product_id,))
            for idx, (data, mime_type) in enumerate(self.selected_images):
                cursor.execute(
                    "INSERT INTO product_images (product_id, image_blob, mime_type, position) VALUES (?, ?, ?, ?)",
                    (product_id, data, mime_type, idx),
                )

        conn.commit()
        conn.close()

        self.reset_product_form()

        self.refresh_all()
        messagebox.showinfo("Succès", "Article enregistré.")

    def refresh_all(self) -> None:
        self.refresh_dashboard()
        self.refresh_products()
        self.refresh_inventory()
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
        last_7_days = conn.execute(
            """
            SELECT DATE(completed_at) AS day,
                   COUNT(*) AS orders_count,
                   COALESCE(SUM(total), 0) AS revenue
            FROM transactions
            WHERE DATE(completed_at) >= DATE('now', '-6 day')
            GROUP BY DATE(completed_at)
            ORDER BY DATE(completed_at)
            """
        ).fetchall()
        conn.close()

        self.dashboard_cards["Total commandes"].config(text=str(total_orders))
        self.dashboard_cards["Commandes en traitement"].config(text=str(processing_orders))
        self.dashboard_cards["Chiffre d'affaires"].config(text=f"€ {revenue:.2f}")
        self.dashboard_cards["Articles actifs"].config(text=str(active_products))

        self.draw_sales_and_orders_chart(last_7_days)
        self.draw_revenue_pie_chart(last_7_days)

    def _normalized_7_days(self, rows):
        by_day = {row["day"]: row for row in rows}
        dates = []
        for offset in range(6, -1, -1):
            day = datetime.utcnow().date().fromordinal(datetime.utcnow().date().toordinal() - offset)
            day_key = day.isoformat()
            row = by_day.get(day_key)
            dates.append(
                {
                    "day": day_key,
                    "label": day.strftime("%d/%m"),
                    "orders_count": row["orders_count"] if row else 0,
                    "revenue": row["revenue"] if row else 0,
                }
            )
        return dates

    def draw_sales_and_orders_chart(self, rows) -> None:
        data = self._normalized_7_days(rows)
        canvas = self.sales_chart
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 420)
        height = max(canvas.winfo_height(), 220)
        canvas.delete("all")

        left, right, top, bottom = 38, width - 12, 16, height - 34
        chart_h = bottom - top
        max_value = max(max(item["orders_count"], item["revenue"]) for item in data) or 1
        canvas.create_line(left, top, left, bottom, fill="#777")
        canvas.create_line(left, bottom, right, bottom, fill="#777")

        slot = (right - left) / len(data)
        group_w = slot * 0.7
        bar_w = group_w / 2 - 3
        for idx, item in enumerate(data):
            x0 = left + idx * slot + (slot - group_w) / 2
            x_orders0 = x0
            x_orders1 = x_orders0 + bar_w
            x_sales0 = x_orders1 + 6
            x_sales1 = x_sales0 + bar_w
            h_orders = (item["orders_count"] / max_value) * chart_h
            h_sales = (item["revenue"] / max_value) * chart_h
            canvas.create_rectangle(x_orders0, bottom - h_orders, x_orders1, bottom, fill="#4a90e2", outline="")
            canvas.create_rectangle(x_sales0, bottom - h_sales, x_sales1, bottom, fill="#27ae60", outline="")
            canvas.create_text((x0 + x_sales1) / 2, bottom + 12, text=item["label"], font=("Segoe UI", 8))

        canvas.create_rectangle(right - 140, top + 2, right - 128, top + 14, fill="#4a90e2", outline="")
        canvas.create_text(right - 122, top + 8, text="Commandes", anchor="w", font=("Segoe UI", 8))
        canvas.create_rectangle(right - 70, top + 2, right - 58, top + 14, fill="#27ae60", outline="")
        canvas.create_text(right - 52, top + 8, text="Ventes (€)", anchor="w", font=("Segoe UI", 8))

    def draw_revenue_pie_chart(self, rows) -> None:
        data = [item for item in self._normalized_7_days(rows) if item["revenue"] > 0]
        canvas = self.revenue_pie
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 320)
        height = max(canvas.winfo_height(), 220)
        canvas.delete("all")

        if not data:
            canvas.create_text(width / 2, height / 2, text="Aucun revenu sur 7 jours", fill="#666")
            return

        total = sum(item["revenue"] for item in data)
        box = (20, 18, min(width - 140, 200), min(height - 20, 200))
        colors = ["#4a90e2", "#27ae60", "#f39c12", "#8e44ad", "#16a085", "#d35400", "#c0392b"]
        start_angle = 0
        legend_y = 22
        for idx, item in enumerate(data):
            extent = (item["revenue"] / total) * 360
            color = colors[idx % len(colors)]
            canvas.create_arc(*box, start=start_angle, extent=extent, fill=color, outline="#ffffff")
            pct = item["revenue"] / total * 100
            canvas.create_rectangle(width - 126, legend_y - 6, width - 114, legend_y + 6, fill=color, outline="")
            canvas.create_text(
                width - 108,
                legend_y,
                anchor="w",
                text=f"{item['label']} ({pct:.0f}%)",
                font=("Segoe UI", 8),
            )
            legend_y += 20
            start_angle += extent

    def export_transactions_excel(self) -> None:
        days = self.export_days.get()
        if days not in (1, 7, 15, 30):
            days = 7
        conn = get_connection()
        transactions = conn.execute(
            """
            SELECT t.id,
                   t.order_id,
                   t.completed_at,
                   t.total,
                   o.customer_name,
                   o.customer_email,
                   o.customer_address,
                   o.status,
                   o.payment_status,
                   o.shipping_fee,
                   o.created_at
            FROM transactions t
            JOIN orders o ON o.id = t.order_id
            WHERE DATE(t.completed_at) >= DATE('now', ?)
            ORDER BY t.completed_at DESC
            """,
            (f"-{days - 1} day",),
        ).fetchall()
        conn.close()

        if not transactions:
            messagebox.showinfo("Export", "Aucune transaction à exporter pour cette plage.")
            return

        default_name = f"transactions_{days}j_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xls"
        path = filedialog.asksaveasfilename(
            title="Exporter les transactions",
            defaultextension=".xls",
            initialfile=default_name,
            filetypes=[("Fichier Excel", "*.xls")],
        )
        if not path:
            return

        headers = [
            "ID Transaction",
            "ID Commande",
            "Date transaction",
            "Montant",
            "Client",
            "Email",
            "Adresse",
            "Statut commande",
            "Statut paiement",
            "Frais livraison",
            "Date commande",
        ]
        rows_html = []
        for tx in transactions:
            row = [
                tx["id"],
                tx["order_id"],
                tx["completed_at"],
                f"{tx['total']:.2f}",
                tx["customer_name"],
                tx["customer_email"],
                tx["customer_address"],
                tx["status"],
                tx["payment_status"],
                f"{tx['shipping_fee']:.2f}",
                tx["created_at"],
            ]
            rows_html.append("<tr>" + "".join(f"<td>{html.escape(str(v or ''))}</td>" for v in row) + "</tr>")

        table_header = "".join(f"<th>{h}</th>" for h in headers)
        html_content = (
            "<html><head><meta charset='utf-8'></head><body>"
            "<table border='1'>"
            f"<tr>{table_header}</tr>"
            + "".join(rows_html)
            + "</table></body></html>"
        )

        with open(path, "w", encoding="utf-8") as file:
            file.write(html_content)
        messagebox.showinfo("Export", f"Export Excel réalisé: {path}")

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
        self.load_product_for_edit(product_id)
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

    def refresh_inventory(self) -> None:
        for item in self.inventory_tree.get_children():
            self.inventory_tree.delete(item)

        conn = get_connection()
        products = conn.execute("SELECT id, name FROM products ORDER BY name").fetchall()
        inventory = conn.execute(
            """
            SELECT p.name AS product_name, p.status, i.color, i.size, i.quantity
            FROM product_inventory i
            JOIN products p ON p.id = i.product_id
            ORDER BY p.name, p.status, i.color, i.size
            """
        ).fetchall()
        conn.close()

        self.inventory_products = {product["name"]: product["id"] for product in products}
        self.inventory_product_combo["values"] = list(self.inventory_products.keys())

        for row in inventory:
            self.inventory_tree.insert(
                "",
                "end",
                values=(
                    row["product_name"],
                    row["status"],
                    row["color"],
                    row["size"],
                    row["quantity"],
                ),
            )

    def update_inventory(self) -> None:
        product_name = self.inventory_product.get().strip()
        color = self.inventory_color.get().strip()
        size = self.inventory_size.get().strip()
        quantity_str = self.inventory_quantity.get().strip()

        if not product_name or not color or not size or not quantity_str:
            messagebox.showerror(
                "Erreur",
                "Sélectionnez un article, une couleur, une taille et une quantité.",
            )
            return
        if not quantity_str.isdigit():
            messagebox.showerror("Erreur", "Quantité invalide.")
            return
        quantity = int(quantity_str)
        product_id = self.inventory_products.get(product_name)
        if not product_id:
            messagebox.showerror("Erreur", "Article introuvable.")
            return

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO product_inventory (product_id, color, size, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id, color, size)
            DO UPDATE SET quantity = excluded.quantity
            """,
            (product_id, color, size, quantity),
        )
        total_stock = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM product_inventory WHERE product_id = ?",
            (product_id,),
        ).fetchone()["total"]
        cursor.execute("UPDATE products SET stock = ? WHERE id = ?", (total_stock, product_id))
        conn.commit()
        conn.close()
        self.inventory_quantity.set("")
        self.refresh_products()
        self.refresh_inventory()
        messagebox.showinfo("Succès", "Inventaire mis à jour.")

    def update_product_status(self) -> None:
        product_name = self.inventory_product.get().strip()
        status = self.inventory_status.get().strip()
        if not product_name or not status:
            messagebox.showerror("Erreur", "Sélectionnez un article et un statut.")
            return
        product_id = self.inventory_products.get(product_name)
        if not product_id:
            messagebox.showerror("Erreur", "Article introuvable.")
            return
        conn = get_connection()
        conn.execute("UPDATE products SET status = ? WHERE id = ?", (status, product_id))
        conn.commit()
        conn.close()
        self.inventory_status.set("")
        self.refresh_products()
        self.refresh_inventory()
        messagebox.showinfo("Succès", "Statut mis à jour.")

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
            "SELECT product_name, quantity, price, color, size FROM order_items WHERE order_id = ?",
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
                    item["color"] or "",
                    item["size"] or "",
                ),
            )
        self.clear_order_item_indicator()
        detail = (
            f"Client: {order['customer_name']}\n"
            f"Email: {order['customer_email']}\n"
            f"Date achat: {order['created_at']}\n"
            f"Statut: {order['status']}\n"
            f"Paiement: {order['payment_status']}\n"
            f"Livraison: € {order['shipping_fee']:.2f}\n"
            f"Total TTC: € {order['total']:.2f}"
        )
        self.order_address_label.config(text=self.format_customer_address(order))
        self.order_detail_label.config(text=detail)

    def clear_order_item_indicator(self) -> None:
        self.order_item_color_label.config(text="N/A", background=self.root.cget("bg"))
        self.order_item_size_label.config(text="N/A")

    def update_order_item_indicator(self, _event=None) -> None:
        selected = self.order_items_tree.selection()
        if not selected:
            self.clear_order_item_indicator()
            return
        values = self.order_items_tree.item(selected[0]).get("values", [])
        if len(values) < 5:
            self.clear_order_item_indicator()
            return
        color_name = values[3] or "N/A"
        size_name = values[4] or "N/A"
        swatch_color = COLOR_SWATCHES.get(color_name, self.root.cget("bg"))
        self.order_item_color_label.config(text=color_name, background=swatch_color)
        self.order_item_size_label.config(text=size_name)

    def format_customer_address(self, order) -> str:
        name = str(order["customer_name"] or "").strip()
        raw_address = str(order["customer_address"] or "").strip()
        if not raw_address:
            return "Adresse indisponible"
        lines = [line.strip() for line in raw_address.replace("\r", "\n").split("\n") if line.strip()]
        if len(lines) == 1:
            parts = [part.strip() for part in lines[0].split(",") if part.strip()]
        else:
            parts = lines
        address_lines = []
        if name:
            address_lines.append(name)
        if parts:
            address_lines.append(parts[0])
        if len(parts) > 1:
            address_lines.append(parts[1])
        if len(parts) > 2:
            address_lines.append(parts[2])
        if len(parts) > 3:
            address_lines.append(", ".join(parts[3:]))
        return "\n".join(address_lines) if address_lines else "Adresse indisponible"

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
