from __future__ import annotations

import io
import html
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
    Toplevel,
    colorchooser,
)

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover - optional dependency
    Image = None
    ImageTk = None

from elit21.db import (
    CURRENCY_OPTIONS,
    decimal_to_cents,
    DEFAULT_SITE_SETTINGS,
    PAGE_CUSTOMIZATION_KEYS,
    get_connection,
    get_site_settings,
    init_db,
)
from elit21.i18n import SUPPORTED_LANGUAGES, admin_tr, normalize_language
from elit21.services.media_service import InvalidImageUpload, resolve_image_path, save_product_image


MAX_IMAGES = 8
ORDERS_AUTO_REFRESH_MS = 60_000
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

SITE_NAME_FONTS = [
    "Segoe UI",
    "Inter",
    "Arial",
    "Helvetica",
    "Times New Roman",
    "Georgia",
    "Verdana",
    "Courier New",
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

PAGE_DESIGN_HINTS = {
    "cart": "Panier avec liste d'articles + résumé de facture.",
    "checkout": "Formulaire livraison + modules paiement + facture.",
    "checkout_success": "Confirmation paiement avec récapitulatif.",
    "experience": "Tableau d'analyse avec cartes de métriques.",
    "index": "Hero marketing + annonces + grille produits.",
    "login": "Bloc d'authentification compact.",
    "policy": "Page info avec image de marque + sections liste.",
    "product": "Fiche produit + options + galerie image.",
    "register": "Bloc d'inscription compact.",
    "seo": "Page information SEO structurée.",
}


class AdminApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("ELIT21 - Gestionnaire")
        self.root.geometry("1200x750")

        init_db()

        self.selected_images: list[tuple[bytes, str, str | None]] = []
        self.image_previews: list[ImageTk.PhotoImage] = []
        self.orders_refresh_job: str | None = None
        self.site_settings_window: Toplevel | None = None
        self.site_preview_window: Toplevel | None = None
        self.currency_window: Toplevel | None = None
        self.site_settings_vars: dict[str, StringVar] = {}
        self.page_tabs: dict[str, ttk.Frame] = {}
        self.selected_preview_page = "index"
        self._site_settings_autosave_job: str | None = None
        self.currency_var = StringVar(value="CAD")
        self.currency_code = "CAD"
        self.language_code = "fr"
        self.language_window: Toplevel | None = None
        self.shipping_window: Toplevel | None = None

        top_bar = ttk.Frame(root, padding=(10, 6))
        top_bar.pack(fill="x")
        self.web_button = ttk.Button(top_bar, command=self.open_site_settings_window)
        self.web_button.pack(side="left")
        self.currency_button = ttk.Button(top_bar, command=self.open_currency_window)
        self.currency_button.pack(side="left", padx=(8, 0))
        self.shipping_button = ttk.Button(top_bar, command=self.open_shipping_window)
        self.shipping_button.pack(side="left", padx=(8, 0))
        self.language_button = ttk.Button(top_bar, command=self.open_language_window)
        self.language_button.pack(side="left", padx=(8, 0))
        ttk.Button(top_bar, text="Actualiser tout", command=self.refresh_all).pack(side="right")
        ttk.Button(top_bar, text="Exporter produits CSV", command=self.export_products_csv).pack(
            side="right", padx=(0, 8)
        )
        self.root.bind("<Control-r>", lambda _event: self.refresh_all())
        self.root.bind("<Control-f>", lambda _event: self.focus_product_search())

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        self.dashboard_tab = ttk.Frame(notebook)
        self.products_tab = ttk.Frame(notebook)
        self.inventory_tab = ttk.Frame(notebook)
        self.orders_tab = ttk.Frame(notebook)
        self.transactions_tab = ttk.Frame(notebook)

        self.notebook = notebook
        notebook.add(self.dashboard_tab, text="")
        notebook.add(self.products_tab, text="")
        notebook.add(self.inventory_tab, text="")
        notebook.add(self.orders_tab, text="")
        notebook.add(self.transactions_tab, text="")

        self._build_dashboard()
        self._build_products_tab()
        self._build_inventory_tab()
        self._build_orders_tab()
        self._build_transactions_tab()

        self.apply_language()
        self.refresh_all()
        self.schedule_orders_refresh()
        self.open_site_settings_window()

    def t(self, key: str) -> str:
        return admin_tr(self.language_code, key)

    def apply_language(self) -> None:
        settings = get_site_settings()
        self.language_code = normalize_language(settings.get("language_code"))
        self.root.title(self.t("title"))
        self.web_button.config(text=self.t("btn_web"))
        self.currency_button.config(text=self.t("btn_currency"))
        self.language_button.config(text=self.t("btn_language"))
        self.shipping_button.config(text=self.t("btn_shipping"))
        self.notebook.tab(self.dashboard_tab, text=self.t("tab_dashboard"))
        self.notebook.tab(self.products_tab, text=self.t("tab_products"))
        self.notebook.tab(self.inventory_tab, text=self.t("tab_inventory"))
        self.notebook.tab(self.orders_tab, text=self.t("tab_orders"))
        self.notebook.tab(self.transactions_tab, text=self.t("tab_transactions"))

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
        self.product_filter_query = StringVar()
        self.product_filter_status = StringVar(value="Tous")
        self.product_filter_stock = StringVar(value="Tous")
        self.products_total_count = 0
        self.product_sort_by = StringVar(value="created_desc")

        ttk.Label(form_frame, text="Nom").pack(anchor="w")
        ttk.Entry(form_frame, textvariable=self.product_name, width=35).pack(anchor="w")

        ttk.Label(form_frame, text="Description").pack(anchor="w", pady=(10, 0))
        self.product_description = Text(form_frame, width=40, height=6)
        self.product_description.pack(anchor="w")

        self.product_price_label = ttk.Label(form_frame, text="Prix")
        self.product_price_label.pack(anchor="w", pady=(10, 0))
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
        ttk.Entry(form_frame, textvariable=self.product_size, width=20).pack(anchor="w")

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
            values=["pending", "active", "inactive", "archived"],
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
        filters_frame = ttk.Frame(list_frame)
        filters_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(filters_frame, text="Recherche").pack(side="left")
        self.product_filter_entry = ttk.Entry(filters_frame, textvariable=self.product_filter_query, width=24)
        self.product_filter_entry.pack(side="left", padx=(6, 8))
        ttk.Label(filters_frame, text="Statut").pack(side="left")
        status_filter = ttk.Combobox(
            filters_frame,
            textvariable=self.product_filter_status,
            values=["Tous", "active", "pending", "inactive", "archived"],
            state="readonly",
            width=12,
        )
        status_filter.pack(side="left", padx=(6, 8))
        ttk.Label(filters_frame, text="Stock").pack(side="left")
        stock_filter = ttk.Combobox(
            filters_frame,
            textvariable=self.product_filter_stock,
            values=["Tous", "En stock", "Stock faible (<=3)", "Rupture"],
            state="readonly",
            width=16,
        )
        stock_filter.pack(side="left", padx=(6, 8))
        ttk.Label(filters_frame, text="Tri").pack(side="left")
        sort_filter = ttk.Combobox(
            filters_frame,
            textvariable=self.product_sort_by,
            values=["created_desc", "name_asc", "price_desc", "stock_desc"],
            state="readonly",
            width=14,
        )
        sort_filter.pack(side="left", padx=(6, 8))
        ttk.Button(filters_frame, text="Filtrer", command=self.refresh_products).pack(side="left")
        ttk.Button(
            filters_frame,
            text="Réinitialiser",
            command=lambda: self._reset_product_filters(),
        ).pack(side="left", padx=(6, 0))
        self.products_count_label = ttk.Label(filters_frame, text="0 article(s)")
        self.products_count_label.pack(side="right")
        self.product_filter_query.trace_add("write", lambda *_args: self.refresh_products())
        self.product_filter_status.trace_add("write", lambda *_args: self.refresh_products())
        self.product_filter_stock.trace_add("write", lambda *_args: self.refresh_products())
        self.product_sort_by.trace_add("write", lambda *_args: self.refresh_products())

        columns = ("id", "name", "status", "price", "stock")
        self.products_tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        for col in columns:
            self.products_tree.heading(col, text=col.capitalize())
            self.products_tree.column(col, width=120)
        self.products_tree.pack(side="left", fill="both", expand=True)
        self.products_tree.bind("<<TreeviewSelect>>", self.show_product_preview)
        self.products_tree.bind("<Double-1>", self.show_product_preview)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.products_tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.products_tree.configure(yscrollcommand=scrollbar.set)

        self.products_tree.tag_configure("active", background="#e8fff2")
        self.products_tree.tag_configure("pending", background="#fff8e5")
        self.products_tree.tag_configure("inactive", background="#ffecec")
        self.products_tree.tag_configure("archived", background="#eef0f4")
        self.products_tree.tag_configure("low_stock", foreground="#b45309")
        self.products_status_summary = ttk.Label(
            list_frame,
            text="Actifs: 0 | En attente: 0 | Inactifs: 0",
            foreground="#475569",
        )
        self.products_status_summary.pack(anchor="w", pady=(8, 0))

        preview_frame = ttk.Labelframe(container, text="Aperçu image", padding=15)
        preview_frame.pack(side="left", fill="y", padx=10)
        self.preview_label = Label(preview_frame, text="Aucune image")
        self.preview_label.pack()
        ttk.Separator(preview_frame, orient="horizontal").pack(fill="x", pady=10)
        ttk.Button(
            preview_frame,
            text="Activer sélection",
            command=lambda: self.bulk_update_selected_products("active"),
        ).pack(fill="x", pady=(0, 6))
        ttk.Button(
            preview_frame,
            text="Désactiver sélection",
            command=lambda: self.bulk_update_selected_products("inactive"),
        ).pack(fill="x", pady=(0, 6))
        ttk.Button(
            preview_frame,
            text="Mettre en attente",
            command=lambda: self.bulk_update_selected_products("pending"),
        ).pack(fill="x")
        ttk.Button(
            preview_frame,
            text="Dupliquer sélection",
            command=self.duplicate_selected_products,
        ).pack(fill="x", pady=(8, 6))
        ttk.Button(
            preview_frame,
            text="Supprimer sélection",
            command=self.delete_selected_products,
        ).pack(fill="x")
        ttk.Separator(preview_frame, orient="horizontal").pack(fill="x", pady=10)
        self.stock_adjust_delta = StringVar(value="1")
        controls = ttk.Frame(preview_frame)
        controls.pack(fill="x")
        ttk.Label(controls, text="Ajustement stock").pack(side="left")
        ttk.Entry(controls, textvariable=self.stock_adjust_delta, width=6).pack(side="left", padx=(6, 6))
        ttk.Button(controls, text="+", width=3, command=lambda: self.adjust_selected_stock(True)).pack(side="left")
        ttk.Button(controls, text="-", width=3, command=lambda: self.adjust_selected_stock(False)).pack(side="left", padx=(6, 0))
        ttk.Label(
            preview_frame,
            text="Astuce: Ctrl/Cmd+clic pour multi-sélection.",
            foreground="#6b7280",
            wraplength=220,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

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
        ttk.Entry(form_frame, textvariable=self.inventory_size, width=20).pack(anchor="w")

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
        detail_frame.configure(width=520)
        detail_frame.pack_propagate(False)

        self.order_detail_label = ttk.Label(detail_frame, text="Sélectionnez une commande")
        self.order_detail_label.pack(anchor="w")

        address_frame = ttk.Labelframe(detail_frame, text="Adresse client", padding=10)
        address_frame.pack(fill="x", pady=10)
        address_frame.configure(height=120)
        address_frame.pack_propagate(False)
        self.order_address_label = Label(
            address_frame,
            text="Adresse indisponible",
            justify="left",
            wraplength=430,
            height=5,
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
        items_frame.configure(height=210)
        items_frame.pack_propagate(False)
        item_columns = ("article", "quantite", "prix", "color", "size")
        self.order_items_tree = ttk.Treeview(
            items_frame,
            columns=item_columns,
            show="headings",
            displaycolumns=("article", "quantite", "prix"),
            height=5,
        )
        self.order_items_tree.heading("article", text="Article")
        self.order_items_tree.heading("quantite", text="Qté")
        self.order_items_tree.heading("prix", text="Prix")
        self.order_items_tree.column("article", width=240)
        self.order_items_tree.column("quantite", width=60)
        self.order_items_tree.column("prix", width=80)
        self.order_items_tree.pack(side="left", fill="both", expand=True)
        self.order_items_tree.bind("<<TreeviewSelect>>", self.update_order_item_indicator)
        items_scrollbar_y = ttk.Scrollbar(items_frame, orient="vertical", command=self.order_items_tree.yview)
        items_scrollbar_y.pack(side="right", fill="y")
        items_scrollbar_x = ttk.Scrollbar(items_frame, orient="horizontal", command=self.order_items_tree.xview)
        items_scrollbar_x.pack(side="bottom", fill="x")
        self.order_items_tree.configure(
            yscrollcommand=items_scrollbar_y.set,
            xscrollcommand=items_scrollbar_x.set,
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
            self.selected_images.append((data, mime_type, path))

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
                INSERT INTO products (name, description, price, price_cents, status, stock, color, size, category, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    description,
                    price_value,
                    decimal_to_cents(price_value),
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
                SET name = ?, description = ?, price = ?, price_cents = ?, status = ?, stock = ?, color = ?, size = ?, category = ?
                WHERE id = ?
                """,
                (
                    name,
                    description,
                    price_value,
                    decimal_to_cents(price_value),
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
            for idx, (data, mime_type, original_path) in enumerate(self.selected_images):
                try:
                    image_path = save_product_image(
                        product_id=product_id,
                        index=idx,
                        content=data,
                        mime_type=mime_type,
                        original_path=original_path,
                    )
                except InvalidImageUpload as exc:
                    conn.rollback()
                    conn.close()
                    messagebox.showerror("Image refusée", str(exc))
                    return
                cursor.execute(
                    """
                    INSERT INTO product_images (product_id, image_blob, image_path, mime_type, position)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (product_id, None, image_path, mime_type, idx),
                )

        conn.commit()
        conn.close()

        self.reset_product_form()

        self.refresh_all()
        messagebox.showinfo("Succès", "Article enregistré.")

    def refresh_all(self) -> None:
        self.refresh_currency_settings()
        self.update_currency_labels()
        self.refresh_dashboard()
        self.refresh_products()
        self.refresh_inventory()
        self.refresh_orders()
        self.refresh_transactions()

    def refresh_currency_settings(self) -> None:
        settings = get_site_settings()
        currency_code = str(settings.get("currency_code") or "CAD").upper()
        if currency_code not in CURRENCY_OPTIONS:
            currency_code = "CAD"
        self.currency_code = currency_code
        self.currency_var.set(currency_code)

    def get_currency_label(self) -> str:
        currency = CURRENCY_OPTIONS.get(self.currency_code, CURRENCY_OPTIONS["CAD"])
        return f"{currency['symbol']} ({self.currency_code})"

    def format_money(self, amount: float) -> str:
        return f"{self.get_currency_label()} {amount:.2f}"

    def update_currency_labels(self) -> None:
        if hasattr(self, "product_price_label"):
            self.product_price_label.config(text=f"Prix ({self.get_currency_label()})")

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
        self.dashboard_cards["Chiffre d'affaires"].config(text=self.format_money(revenue))
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
        canvas.create_text(
            right - 52,
            top + 8,
            text=f"Ventes ({self.get_currency_label()})",
            anchor="w",
            font=("Segoe UI", 8),
        )

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

        filter_query = self.product_filter_query.get().strip().lower()
        filter_status = self.product_filter_status.get().strip().lower()

        where_clauses = []
        params: list[str] = []
        if filter_query:
            where_clauses.append("(LOWER(name) LIKE ? OR LOWER(category) LIKE ?)")
            params.extend([f"%{filter_query}%", f"%{filter_query}%"])
        if filter_status and filter_status != "tous":
            where_clauses.append("status = ?")
            params.append(filter_status)

        filter_stock = self.product_filter_stock.get().strip().lower()
        if filter_stock == "en stock":
            where_clauses.append("stock > 0")
        elif filter_stock == "stock faible (<=3)":
            where_clauses.append("stock BETWEEN 1 AND 3")
        elif filter_stock == "rupture":
            where_clauses.append("stock <= 0")

        query = "SELECT id, name, status, price, stock FROM products"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        sort_map = {
            "created_desc": "created_at DESC",
            "name_asc": "name ASC",
            "price_desc": "price DESC",
            "stock_desc": "stock DESC",
        }
        query += f" ORDER BY {sort_map.get(self.product_sort_by.get(), 'created_at DESC')}"

        conn = get_connection()
        products = conn.execute(query, params).fetchall()
        self.products_total_count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        status_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS c
            FROM products
            GROUP BY status
            """
        ).fetchall()
        conn.close()
        status_counts = {row["status"]: row["c"] for row in status_rows}

        for product in products:
            self.products_tree.insert(
                "",
                "end",
                values=(
                    product["id"],
                    product["name"],
                    product["status"],
                    self.format_money(product["price"]),
                    product["stock"],
                ),
                tags=(
                    product["status"],
                    "low_stock" if int(product["stock"] or 0) <= 3 else "",
                ),
            )
        self.products_count_label.config(text=f"{len(products)} / {self.products_total_count} article(s)")
        self.products_status_summary.config(
            text=(
                f"Actifs: {status_counts.get('active', 0)} | "
                f"En attente: {status_counts.get('pending', 0)} | "
                f"Inactifs: {status_counts.get('inactive', 0)}"
            )
        )
        self.preview_label.config(text="Aucune image", image="")
        self.preview_label.image = None

    def export_products_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Exporter produits (CSV)",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT id, name, category, status, price, stock, created_at
            FROM products
            ORDER BY created_at DESC
            """
        ).fetchall()
        conn.close()
        headers = ["id", "name", "category", "status", "price", "stock", "created_at"]
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(headers) + "\n")
            for row in rows:
                values = []
                for key in headers:
                    value = str(row[key] if row[key] is not None else "")
                    escaped = value.replace('"', '""')
                    values.append(f'"{escaped}"')
                f.write(",".join(values) + "\n")
        messagebox.showinfo("Export", f"Export CSV réalisé: {path}")

    def _reset_product_filters(self) -> None:
        self.product_filter_query.set("")
        self.product_filter_status.set("Tous")
        self.product_filter_stock.set("Tous")
        self.product_sort_by.set("created_desc")
        self.refresh_products()

    def bulk_update_selected_products(self, status: str) -> None:
        selected = self.products_tree.selection()
        if not selected:
            messagebox.showwarning("Sélection requise", "Sélectionnez au moins un article.")
            return
        ids = [int(self.products_tree.item(item)["values"][0]) for item in selected]
        placeholders = ",".join("?" for _ in ids)
        conn = get_connection()
        conn.execute(
            f"UPDATE products SET status = ? WHERE id IN ({placeholders})",
            [status, *ids],
        )
        conn.commit()
        conn.close()
        self.refresh_products()
        self.refresh_inventory()
        messagebox.showinfo("Succès", f"{len(ids)} article(s) mis à jour.")

    def duplicate_selected_products(self) -> None:
        selected = self.products_tree.selection()
        if not selected:
            messagebox.showwarning("Sélection requise", "Sélectionnez au moins un article.")
            return
        conn = get_connection()
        cursor = conn.cursor()
        created = 0
        for item in selected:
            product_id = int(self.products_tree.item(item)["values"][0])
            product = cursor.execute(
                "SELECT name, description, price, stock, color, size, category FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
            if not product:
                continue
            cursor.execute(
                """
                INSERT INTO products (name, description, price, price_cents, status, stock, color, size, category, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{product['name']} (Copie)",
                    product["description"],
                    product["price"],
                    "pending",
                    product["stock"],
                    product["color"],
                    product["size"],
                    product["category"],
                    datetime.utcnow().isoformat(),
                ),
            )
            created += 1
        conn.commit()
        conn.close()
        self.refresh_all()
        messagebox.showinfo("Succès", f"{created} article(s) dupliqué(s).")

    def delete_selected_products(self) -> None:
        selected = self.products_tree.selection()
        if not selected:
            messagebox.showwarning("Sélection requise", "Sélectionnez au moins un article.")
            return
        if not messagebox.askyesno(
            "Confirmation",
            (
                f"Supprimer {len(selected)} article(s) ? Les produits déjà liés "
                "à une commande seront archivés pour préserver l'historique."
            ),
        ):
            return
        conn = get_connection()
        cursor = conn.cursor()
        deleted_count = 0
        archived_count = 0
        for item in selected:
            product_id = int(self.products_tree.item(item)["values"][0])
            order_usage = cursor.execute(
                "SELECT COUNT(*) AS count FROM order_items WHERE product_id = ?",
                (product_id,),
            ).fetchone()["count"]
            if order_usage:
                cursor.execute(
                    """
                    UPDATE products
                    SET status = ?, archived = 1, deleted_at = ?, stock = 0
                    WHERE id = ?
                    """,
                    ("archived", datetime.utcnow().isoformat(), product_id),
                )
                cursor.execute(
                    "UPDATE product_inventory SET quantity = 0 WHERE product_id = ?",
                    (product_id,),
                )
                archived_count += 1
            else:
                cursor.execute("DELETE FROM product_images WHERE product_id = ?", (product_id,))
                cursor.execute("DELETE FROM product_inventory WHERE product_id = ?", (product_id,))
                cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
                deleted_count += 1
        conn.commit()
        conn.close()
        self.reset_product_form()
        self.refresh_all()
        messagebox.showinfo(
            "Succès",
            f"{deleted_count} article(s) supprimé(s), {archived_count} article(s) archivé(s).",
        )

    def adjust_selected_stock(self, increase: bool) -> None:
        selected = self.products_tree.selection()
        if not selected:
            messagebox.showwarning("Sélection requise", "Sélectionnez au moins un article.")
            return
        try:
            delta = int(self.stock_adjust_delta.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Erreur", "Valeur d'ajustement invalide.")
            return
        if delta <= 0:
            messagebox.showerror("Erreur", "La valeur d'ajustement doit être > 0.")
            return
        delta = delta if increase else -delta
        ids = [int(self.products_tree.item(item)["values"][0]) for item in selected]
        placeholders = ",".join("?" for _ in ids)
        conn = get_connection()
        conn.execute(
            f"UPDATE products SET stock = CASE WHEN stock + ? < 0 THEN 0 ELSE stock + ? END WHERE id IN ({placeholders})",
            [delta, delta, *ids],
        )
        conn.commit()
        conn.close()
        self.refresh_products()
        self.refresh_inventory()

    def focus_product_search(self) -> None:
        self.notebook.select(self.products_tab)
        if hasattr(self, "product_filter_entry"):
            self.product_filter_entry.focus_set()

    def show_product_preview(self, _event=None) -> None:
        selected = self.products_tree.selection()
        if not selected:
            return
        product_id = int(self.products_tree.item(selected[0])["values"][0])
        self.load_product_for_edit(product_id)
        conn = get_connection()
        image = conn.execute(
            """
            SELECT image_blob, image_path, mime_type
            FROM product_images
            WHERE product_id = ?
            ORDER BY position
            LIMIT 1
            """,
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
        if data is None and image["image_path"]:
            path = resolve_image_path(image["image_path"])
            if path.exists():
                data = path.read_bytes()
        if data is None:
            self.preview_label.config(text="Image introuvable", image="")
            self.preview_label.image = None
            return
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
        selected = self.orders_tree.selection()
        selected_order = selected[0] if selected else None
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
                    self.format_money(order["total"]),
                    order["created_at"],
                ),
            )

        if selected_order and self.orders_tree.exists(selected_order):
            self.orders_tree.selection_set(selected_order)
            self.orders_tree.focus(selected_order)
            self.orders_tree.see(selected_order)
            self.show_order_detail()

    def schedule_orders_refresh(self) -> None:
        if self.orders_refresh_job is not None:
            self.root.after_cancel(self.orders_refresh_job)
        self.orders_refresh_job = self.root.after(ORDERS_AUTO_REFRESH_MS, self.auto_refresh_orders)

    def auto_refresh_orders(self) -> None:
        self.refresh_orders()
        self.schedule_orders_refresh()

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
                values=(tx["id"], tx["order_id"], self.format_money(tx["total"]), tx["completed_at"]),
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
                    self.format_money(item["price"]),
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
            f"Livraison: {self.format_money(order['shipping_fee'])}\n"
            f"Total TTC: {self.format_money(order['total'])}"
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

    def open_language_window(self) -> None:
        if self.language_window and self.language_window.winfo_exists():
            self.language_window.lift()
            self.language_window.focus_force()
            return

        self.apply_language()
        self.language_window = Toplevel(self.root)
        self.language_window.title(self.t("language_window_title"))
        self.language_window.geometry("420x180")
        self.language_window.resizable(False, False)

        frame = ttk.Frame(self.language_window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.t("language_label"), wraplength=360).pack(anchor="w", pady=(0, 8))

        self.language_var = StringVar(value=self.language_code)
        values = [f"{code} - {name}" for code, name in SUPPORTED_LANGUAGES.items()]
        self.language_combo = ttk.Combobox(frame, values=values, state="readonly", width=32)
        self.language_combo.pack(anchor="w", fill="x")
        selected = next((v for v in values if v.startswith(f"{self.language_code} - ")), values[0])
        self.language_combo.set(selected)

        ttk.Button(frame, text=self.t("language_confirm"), command=self.save_language_selection).pack(anchor="e", pady=(14, 0))

    def save_language_selection(self) -> None:
        if not hasattr(self, "language_combo"):
            return
        selected = self.language_combo.get().strip()
        language_code = normalize_language(selected.split(" - ", 1)[0] if selected else "fr")

        conn = get_connection()
        conn.execute("UPDATE site_settings SET language_code = ? WHERE id = 1", (language_code,))
        conn.commit()
        conn.close()

        self.apply_language()

        if self.language_window and self.language_window.winfo_exists():
            self.language_window.destroy()

        messagebox.showinfo("OK", self.t("language_updated"))

    def open_shipping_window(self) -> None:
        if self.shipping_window and self.shipping_window.winfo_exists():
            self.shipping_window.lift()
            self.shipping_window.focus_force()
            return

        self.refresh_currency_settings()
        settings = get_site_settings()
        current_value = str(settings.get("shipping_fee") or "9.99").strip()

        self.shipping_window = Toplevel(self.root)
        self.shipping_window.title("Prix livraison")
        self.shipping_window.geometry("420x220")
        self.shipping_window.resizable(False, False)

        frame = ttk.Frame(self.shipping_window, padding=16)
        frame.pack(fill="both", expand=True)

        currency_label = self.get_currency_label()
        ttk.Label(
            frame,
            text=f"Définissez le prix de livraison pour {currency_label} (site + PayPal):",
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        self.shipping_fee_var = StringVar(value=current_value)
        ttk.Entry(frame, textvariable=self.shipping_fee_var, width=24).pack(anchor="w")

        ttk.Button(
            frame,
            text="Confirmer",
            command=self.save_shipping_fee,
        ).pack(anchor="e", pady=(16, 0))

    def save_shipping_fee(self) -> None:
        if not hasattr(self, "shipping_fee_var"):
            return

        raw_value = self.shipping_fee_var.get().strip().replace(",", ".")
        try:
            shipping_fee = Decimal(raw_value)
        except InvalidOperation:
            messagebox.showerror("Erreur", "Prix de livraison invalide.")
            return

        if shipping_fee < Decimal("0"):
            messagebox.showerror("Erreur", "Le prix de livraison doit être positif.")
            return

        shipping_fee = shipping_fee.quantize(Decimal("0.01"))

        conn = get_connection()
        conn.execute("UPDATE site_settings SET shipping_fee = ? WHERE id = 1", (f"{shipping_fee:.2f}",))
        conn.commit()
        conn.close()

        self.refresh_all()
        if self.shipping_window and self.shipping_window.winfo_exists():
            self.shipping_window.destroy()

        messagebox.showinfo("Succès", f"Prix de livraison mis à jour: {self.format_money(float(shipping_fee))}.")

    def open_currency_window(self) -> None:
        if self.currency_window and self.currency_window.winfo_exists():
            self.currency_window.lift()
            self.currency_window.focus_force()
            return

        self.refresh_currency_settings()
        self.currency_window = Toplevel(self.root)
        self.currency_window.title("Devise monétaire")
        self.currency_window.geometry("420x220")
        self.currency_window.resizable(False, False)

        frame = ttk.Frame(self.currency_window, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Choisir la devise utilisée sur le site et pour PayPal:",
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        values = [
            f"{code} - {meta['name']} ({meta['symbol']})"
            for code, meta in CURRENCY_OPTIONS.items()
        ]
        self.currency_combo = ttk.Combobox(frame, values=values, state="readonly", width=42)
        self.currency_combo.pack(anchor="w")
        selected_value = next(
            (v for v in values if v.startswith(f"{self.currency_code} - ")),
            values[0],
        )
        self.currency_combo.set(selected_value)

        ttk.Button(
            frame,
            text="Confirmer",
            command=self.save_currency_selection,
        ).pack(anchor="e", pady=(16, 0))

    def save_currency_selection(self) -> None:
        if not hasattr(self, "currency_combo"):
            return
        selected = self.currency_combo.get().strip()
        currency_code = selected.split(" - ", 1)[0].upper() if selected else "CAD"
        if currency_code not in CURRENCY_OPTIONS:
            messagebox.showerror("Erreur", "Devise invalide.")
            return

        conn = get_connection()
        conn.execute("UPDATE site_settings SET currency_code = ? WHERE id = 1", (currency_code,))
        conn.commit()
        conn.close()

        self.refresh_all()
        if self.currency_window and self.currency_window.winfo_exists():
            self.currency_window.destroy()
        messagebox.showinfo(
            "Succès",
            f"Devise mise à jour: {CURRENCY_OPTIONS[currency_code]['name']} ({CURRENCY_OPTIONS[currency_code]['symbol']}).",
        )


    def choose_color(self, key: str, preview: Label) -> None:
        initial = self.site_settings_vars[key].get().strip() or DEFAULT_SITE_SETTINGS[key]
        selected = colorchooser.askcolor(color=initial, title="Choisir une couleur")
        color = selected[1]
        if not color:
            return
        self.site_settings_vars[key].set(color)
        preview.config(background=color, text=color)
        self.on_site_settings_changed()

    def on_site_settings_changed(self) -> None:
        self.update_site_preview()
        if self._site_settings_autosave_job:
            self.root.after_cancel(self._site_settings_autosave_job)
        self._site_settings_autosave_job = self.root.after(350, self.autosave_site_settings)

    def autosave_site_settings(self) -> None:
        self._site_settings_autosave_job = None
        self._persist_site_settings()

    def _persist_site_settings(self) -> None:
        values = {key: var.get().strip() for key, var in self.site_settings_vars.items()}
        for key, default_value in DEFAULT_SITE_SETTINGS.items():
            if not values.get(key):
                values[key] = default_value
        assignments = ", ".join([f"{key} = ?" for key in DEFAULT_SITE_SETTINGS])
        conn = get_connection()
        conn.execute(
            f"UPDATE site_settings SET {assignments} WHERE id = 1",
            tuple(values[key] for key in DEFAULT_SITE_SETTINGS),
        )
        conn.commit()
        conn.close()

    def open_site_settings_window(self) -> None:
        if self.site_settings_window and self.site_settings_window.winfo_exists():
            self.site_settings_window.lift()
            self.site_settings_window.focus_force()
            return

        settings = get_site_settings()
        self.site_settings_window = Toplevel(self.root)
        self.site_settings_window.title("Web Page - Personnalisation")
        self.site_settings_window.geometry("1120x760")

        container = ttk.Frame(self.site_settings_window, padding=14)
        container.pack(fill="both", expand=True)

        page_tabs = ttk.Notebook(container)
        page_tabs.pack(fill="both", expand=True)

        fields = [
            ("site_name", "Nom du site"),
            ("header_bg_color", "Couleur en-tête (principal)"),
            ("header_secondary_color", "Couleur en-tête (secondaire)"),
            ("page_bg_color", "Couleur de fond du site"),
            ("ad_bg_color", "Couleur fond petites annonces"),
            ("ad_text_color", "Couleur texte petites annonces"),
            ("ad_button_color", "Couleur bouton Voir article"),
            ("promo_badge_text", "Texte badge promo"),
            ("promo_title_text", "Titre promo"),
            ("promo_description_text", "Description promo"),
            ("promo_card_1_title", "Annonce 1 - titre"),
            ("promo_card_1_value", "Annonce 1 - valeur"),
            ("promo_card_2_title", "Annonce 2 - titre"),
            ("promo_card_2_value", "Annonce 2 - valeur"),
            ("promo_card_3_title", "Annonce 3 - titre"),
            ("promo_card_3_value", "Annonce 3 - valeur"),
        ]

        self.site_settings_vars = {
            key: StringVar(value=settings.get(key, DEFAULT_SITE_SETTINGS[key]))
            for key in DEFAULT_SITE_SETTINGS
        }
        for variable in self.site_settings_vars.values():
            variable.trace_add("write", lambda *_args: self.on_site_settings_changed())

        global_tab = ttk.Frame(page_tabs, padding=12)
        page_tabs.add(global_tab, text="global")

        row = 0
        field_rows: dict[str, int] = {}
        for key, label in fields:
            field_rows[key] = row
            ttk.Label(global_tab, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(global_tab, textvariable=self.site_settings_vars[key], width=45).grid(
                row=row,
                column=1,
                sticky="ew",
                padx=(8, 6),
                pady=3,
            )
            row += 1

        ttk.Label(global_tab, text="Police du nom du site").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Combobox(
            global_tab,
            textvariable=self.site_settings_vars["site_name_font"],
            values=SITE_NAME_FONTS,
            state="readonly",
            width=42,
        ).grid(row=row, column=1, sticky="ew", padx=(8, 6), pady=3)
        row += 1

        for color_key in (
            "header_bg_color",
            "header_secondary_color",
            "page_bg_color",
            "ad_bg_color",
            "ad_text_color",
            "ad_button_color",
        ):
            color_row = field_rows[color_key]
            preview = Label(
                global_tab,
                text=self.site_settings_vars[color_key].get(),
                width=16,
                relief="solid",
                borderwidth=1,
                background=self.site_settings_vars[color_key].get(),
            )
            preview.grid(row=color_row, column=2, padx=(4, 0), pady=3)
            ttk.Button(
                global_tab,
                text="Choisir",
                command=lambda k=color_key, p=preview: self.choose_color(k, p),
            ).grid(row=color_row, column=3, padx=(4, 0), pady=3)

        for page_key in PAGE_CUSTOMIZATION_KEYS:
            page_frame = ttk.Frame(page_tabs, padding=12)
            page_tabs.add(page_frame, text=page_key)
            self._build_page_customization_tab(page_frame, page_key)

        global_tab.columnconfigure(1, weight=1)

        actions = ttk.Frame(global_tab)
        actions.grid(row=row + 1, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Appliquer et sauvegarder", command=self.save_site_settings).pack(side="left")
        ttk.Button(actions, text="Réinitialiser", command=self.reset_site_settings_form).pack(side="left", padx=8)
        ttk.Button(actions, text="Ouvrir Aperçu rapide", command=self.open_site_preview_window).pack(side="left", padx=8)

        self.open_site_preview_window("index")
        self.update_site_preview()

    def _build_page_customization_tab(self, parent: ttk.Frame, page_key: str) -> None:
        if page_key == "experience":
            self._build_experience_customization_tab(parent, page_key)
            return
        ttk.Label(parent, text=f"Paramètres — {page_key}.html", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )
        ttk.Label(parent, text=PAGE_DESIGN_HINTS.get(page_key, ""), foreground="#475569").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )
        ttk.Label(parent, text="Titre de page").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_title_text"], width=52).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Sous-titre").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_subtitle_text"], width=52).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Texte contenu").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_body_text"], width=52).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Alignement du texte").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(
            parent,
            textvariable=self.site_settings_vars[f"{page_key}_text_align"],
            values=("left", "center", "right"),
            state="readonly",
            width=18,
        ).grid(row=5, column=1, sticky="w", padx=(8, 6), pady=4)
        color_preview = Label(
            parent,
            text=self.site_settings_vars[f"{page_key}_accent_color"].get(),
            width=16,
            relief="solid",
            borderwidth=1,
            background=self.site_settings_vars[f"{page_key}_accent_color"].get(),
        )
        ttk.Label(parent, text="Couleur accent").grid(row=6, column=0, sticky="w", pady=4)
        color_preview.grid(row=6, column=1, sticky="w", padx=(8, 6), pady=4)
        ttk.Button(
            parent,
            text="Choisir",
            command=lambda k=f"{page_key}_accent_color", p=color_preview: self.choose_color(k, p),
        ).grid(row=6, column=2, sticky="w", padx=(4, 0), pady=4)

        ttk.Separator(parent, orient="horizontal").grid(row=7, column=0, columnspan=4, sticky="ew", pady=(10, 10))

        ttk.Label(parent, text="Titre section principale").grid(row=8, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_section_title_text"], width=52).grid(
            row=8, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Sous-titre section").grid(row=9, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_section_subtitle_text"], width=52).grid(
            row=9, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Zone texte section").grid(row=10, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_section_body_text"], width=52).grid(
            row=10, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Texte bouton section").grid(row=11, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_section_button_text"], width=28).grid(
            row=11, column=1, sticky="w", padx=(8, 6), pady=4
        )

        color_rows = (
            ("section_bg_color", "Couleur fond section", 12),
            ("section_text_color", "Couleur texte section", 13),
            ("section_button_bg_color", "Couleur bouton section", 14),
            ("section_button_text_color", "Couleur texte bouton", 15),
        )
        for suffix, label, color_row in color_rows:
            key = f"{page_key}_{suffix}"
            preview = Label(
                parent,
                text=self.site_settings_vars[key].get(),
                width=16,
                relief="solid",
                borderwidth=1,
                background=self.site_settings_vars[key].get(),
            )
            ttk.Label(parent, text=label).grid(row=color_row, column=0, sticky="w", pady=4)
            preview.grid(row=color_row, column=1, sticky="w", padx=(8, 6), pady=4)
            ttk.Button(
                parent,
                text="Choisir",
                command=lambda k=key, p=preview: self.choose_color(k, p),
            ).grid(row=color_row, column=2, sticky="w", padx=(4, 0), pady=4)

        ttk.Button(
            parent,
            text=f"Afficher {page_key} dans Aperçu rapide",
            command=lambda p=page_key: self.open_site_preview_window(p),
        ).grid(row=16, column=0, columnspan=3, sticky="w", pady=(12, 0))
        parent.columnconfigure(1, weight=1)

    def _build_experience_customization_tab(self, parent: ttk.Frame, page_key: str) -> None:
        ttk.Label(parent, text="Paramètres — experience.html", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )
        ttk.Label(
            parent,
            text="Structure: en-tête + grille de cartes (2 colonnes) + section produits récents pleine largeur.",
            foreground="#475569",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))

        ttk.Label(parent, text="Titre principal").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_title_text"], width=52).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Sous-titre introduction").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_subtitle_text"], width=52).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Texte descriptif").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_body_text"], width=52).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Alignement du texte de l'en-tête").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(
            parent,
            textvariable=self.site_settings_vars[f"{page_key}_text_align"],
            values=("left", "center", "right"),
            state="readonly",
            width=18,
        ).grid(row=5, column=1, sticky="w", padx=(8, 6), pady=4)
        accent_preview = Label(
            parent,
            text=self.site_settings_vars[f"{page_key}_accent_color"].get(),
            width=16,
            relief="solid",
            borderwidth=1,
            background=self.site_settings_vars[f"{page_key}_accent_color"].get(),
        )
        ttk.Label(parent, text="Couleur accent (liens / surbrillance)").grid(row=6, column=0, sticky="w", pady=4)
        accent_preview.grid(row=6, column=1, sticky="w", padx=(8, 6), pady=4)
        ttk.Button(
            parent,
            text="Choisir",
            command=lambda k=f"{page_key}_accent_color", p=accent_preview: self.choose_color(k, p),
        ).grid(row=6, column=2, sticky="w", padx=(4, 0), pady=4)

        ttk.Separator(parent, orient="horizontal").grid(row=7, column=0, columnspan=4, sticky="ew", pady=(10, 10))

        ttk.Label(parent, text="Carte 1 — titre (indicateurs)").grid(row=8, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_section_title_text"], width=52).grid(
            row=8, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Carte 2 — titre (catégories)").grid(row=9, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_section_subtitle_text"], width=52).grid(
            row=9, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Carte 3 — titre (architecture de prix)").grid(row=10, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_section_body_text"], width=52).grid(
            row=10, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(parent, text="Carte 4 — titre (produits récents)").grid(row=11, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=self.site_settings_vars[f"{page_key}_section_button_text"], width=28).grid(
            row=11, column=1, sticky="w", padx=(8, 6), pady=4
        )

        color_rows = (
            ("section_bg_color", "Couleur fond carte", 12),
            ("section_text_color", "Couleur texte carte", 13),
            ("section_button_bg_color", "Couleur pastille métrique", 14),
            ("section_button_text_color", "Couleur texte pastille", 15),
        )
        for suffix, label, color_row in color_rows:
            key = f"{page_key}_{suffix}"
            preview = Label(
                parent,
                text=self.site_settings_vars[key].get(),
                width=16,
                relief="solid",
                borderwidth=1,
                background=self.site_settings_vars[key].get(),
            )
            ttk.Label(parent, text=label).grid(row=color_row, column=0, sticky="w", pady=4)
            preview.grid(row=color_row, column=1, sticky="w", padx=(8, 6), pady=4)
            ttk.Button(
                parent,
                text="Choisir",
                command=lambda k=key, p=preview: self.choose_color(k, p),
            ).grid(row=color_row, column=2, sticky="w", padx=(4, 0), pady=4)

        ttk.Button(
            parent,
            text="Afficher experience dans Aperçu rapide",
            command=lambda p=page_key: self.open_site_preview_window(p),
        ).grid(row=16, column=0, columnspan=3, sticky="w", pady=(12, 0))
        parent.columnconfigure(1, weight=1)

    def reset_site_settings_form(self) -> None:
        for key, default_value in DEFAULT_SITE_SETTINGS.items():
            self.site_settings_vars[key].set(default_value)
        self.on_site_settings_changed()

    def open_site_preview_window(self, page_key: str = "index") -> None:
        self.selected_preview_page = page_key
        if self.site_preview_window and self.site_preview_window.winfo_exists():
            self.site_preview_window.lift()
            self.site_preview_window.focus_force()
            self.update_site_preview()
            return

        self.site_preview_window = Toplevel(self.root)
        self.site_preview_window.title("Aperçu rapide - Page web")
        self.site_preview_window.geometry("900x600")
        self.site_preview_window.minsize(560, 420)
        frame = ttk.Frame(self.site_preview_window, padding=10)
        frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.preview_canvas = Canvas(frame, bg="#f5f7fb", highlightthickness=1, highlightbackground="#d1d5db")
        self.preview_canvas.pack(side="left", fill="both", expand=True)
        self.preview_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.configure(command=self.preview_canvas.yview)
        self.preview_canvas.bind_all("<MouseWheel>", self._on_preview_mousewheel)
        self.preview_canvas.bind("<Configure>", lambda _event: self.update_site_preview())
        self.update_site_preview()

    def _on_preview_mousewheel(self, event) -> None:
        if not hasattr(self, "preview_canvas") or not self.preview_canvas.winfo_exists():
            return
        self.preview_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def update_site_preview(self) -> None:
        if not hasattr(self, "preview_canvas") or not self.preview_canvas.winfo_exists():
            return
        c = self.preview_canvas
        c.delete("all")
        width = max(c.winfo_width(), 480)
        visible_height = max(c.winfo_height(), 320)
        scale_x = width / 900
        page_key = self.selected_preview_page
        header1 = self.site_settings_vars["header_bg_color"].get().strip() or DEFAULT_SITE_SETTINGS["header_bg_color"]
        bg = self.site_settings_vars["page_bg_color"].get().strip() or DEFAULT_SITE_SETTINGS["page_bg_color"]
        ad_button = self.site_settings_vars[f"{page_key}_accent_color"].get().strip() or DEFAULT_SITE_SETTINGS[f"{page_key}_accent_color"]
        section_bg = self.site_settings_vars[f"{page_key}_section_bg_color"].get().strip() or DEFAULT_SITE_SETTINGS[f"{page_key}_section_bg_color"]
        section_text = self.site_settings_vars[f"{page_key}_section_text_color"].get().strip() or DEFAULT_SITE_SETTINGS[f"{page_key}_section_text_color"]
        section_button_bg = self.site_settings_vars[f"{page_key}_section_button_bg_color"].get().strip() or DEFAULT_SITE_SETTINGS[f"{page_key}_section_button_bg_color"]
        section_button_text = self.site_settings_vars[f"{page_key}_section_button_text_color"].get().strip() or DEFAULT_SITE_SETTINGS[f"{page_key}_section_button_text_color"]
        site_name = self.site_settings_vars["site_name"].get().strip() or DEFAULT_SITE_SETTINGS["site_name"]
        title = self.site_settings_vars[f"{page_key}_title_text"].get().strip() or page_key.replace("_", " ").title()
        subtitle = self.site_settings_vars[f"{page_key}_subtitle_text"].get().strip() or "Sous-titre de page"
        body_text = self.site_settings_vars[f"{page_key}_body_text"].get().strip() or "Aperçu du contenu personnalisé."
        section_title = self.site_settings_vars[f"{page_key}_section_title_text"].get().strip() or "Section principale"
        section_subtitle = self.site_settings_vars[f"{page_key}_section_subtitle_text"].get().strip() or "Sous-section visuelle"
        section_body = self.site_settings_vars[f"{page_key}_section_body_text"].get().strip() or "Texte représentatif du contenu de la page."
        section_button_text_label = self.site_settings_vars[f"{page_key}_section_button_text"].get().strip() or "Action"
        align = self.site_settings_vars[f"{page_key}_text_align"].get().strip() or "left"
        anchor = {"left": "w", "center": "center", "right": "e"}.get(align, "w")
        txt_x = {"left": 40 * scale_x, "center": width / 2, "right": width - (40 * scale_x)}.get(align, 40 * scale_x)

        c.configure(bg=bg)
        c.create_rectangle(0, 0, width, 100, fill=header1, width=0)
        c.create_text(
            22 * scale_x,
            30,
            text=site_name,
            anchor="w",
            fill="#ffffff",
            font=(self.site_settings_vars["site_name_font"].get() or "Segoe UI", max(12, int(16 * scale_x)), "bold"),
        )
        c.create_text(width - (24 * scale_x), 30, text=f"Page: {page_key}", anchor="e", fill="#dbeafe", font=("Segoe UI", 10))
        c.create_text(txt_x, 140, text=title[:84], anchor=anchor, fill=section_text, font=("Segoe UI", 22, "bold"))
        c.create_text(txt_x, 180, text=subtitle[:140], anchor=anchor, fill=section_text, font=("Segoe UI", 12))
        c.create_text(txt_x, 210, text=body_text[:190], anchor=anchor, fill=section_text, font=("Segoe UI", 11))

        self._draw_page_preview_layout(
            c,
            page_key=page_key,
            width=width,
            section_bg=section_bg,
            section_text=section_text,
            section_button_bg=section_button_bg,
            section_button_text=section_button_text,
            section_title=section_title,
            section_subtitle=section_subtitle,
            section_body=section_body,
            section_button_text_label=section_button_text_label,
            accent=ad_button,
        )
        content_height = 1420
        c.configure(scrollregion=(0, 0, width, max(content_height, visible_height + 10)))

    def _draw_page_preview_layout(
        self,
        canvas: Canvas,
        *,
        page_key: str,
        width: int,
        section_bg: str,
        section_text: str,
        section_button_bg: str,
        section_button_text: str,
        section_title: str,
        section_subtitle: str,
        section_body: str,
        section_button_text_label: str,
        accent: str,
    ) -> None:
        top = 250
        left = 30
        right = width - 30
        if page_key == "experience":
            self._draw_experience_preview_layout(
                canvas,
                width=width,
                left=left,
                right=right,
                top=top,
                section_bg=section_bg,
                section_text=section_text,
                section_button_bg=section_button_bg,
                section_button_text=section_button_text,
                section_title=section_title,
                section_subtitle=section_subtitle,
                section_body=section_body,
                section_button_text_label=section_button_text_label,
                accent=accent,
            )
            return

        canvas.create_rectangle(left, top, right, top + 240, fill=section_bg, outline="#cbd5e1")
        canvas.create_text(left + 18, top + 24, text=section_title[:80], anchor="w", fill=section_text, font=("Segoe UI", 16, "bold"))
        canvas.create_text(left + 18, top + 58, text=section_subtitle[:120], anchor="w", fill=section_text, font=("Segoe UI", 11))
        canvas.create_text(left + 18, top + 96, text=section_body[:220], anchor="w", fill=section_text, font=("Segoe UI", 10))
        canvas.create_rectangle(left + 18, top + 170, left + 200, top + 206, fill=section_button_bg, outline="")
        canvas.create_text(left + 109, top + 188, text=section_button_text_label[:34], fill=section_button_text, font=("Segoe UI", 10, "bold"))

        if page_key in {"index", "experience"}:
            y = top + 270
            for i in range(3):
                x1 = left + (i * ((right - left - 24) / 3))
                x2 = x1 + ((right - left - 48) / 3)
                canvas.create_rectangle(x1, y, x2, y + 130, fill="#ffffff", outline="#dbe3ef")
                canvas.create_text(x1 + 14, y + 20, text=f"Carte {i + 1}", anchor="w", fill=accent, font=("Segoe UI", 10, "bold"))
                canvas.create_text(x1 + 14, y + 52, text="Contenu métrique / promo", anchor="w", fill="#334155", font=("Segoe UI", 9))
        elif page_key == "cart":
            y = top + 270
            canvas.create_rectangle(left, y, width * 0.68, y + 420, fill="#ffffff", outline="#dbe3ef")
            canvas.create_text(left + 14, y + 18, text="Liste/Formulaire", anchor="w", fill=accent, font=("Segoe UI", 10, "bold"))
            canvas.create_rectangle(width * 0.7, y, right, y + 420, fill="#ffffff", outline="#dbe3ef")
            canvas.create_text(width * 0.7 + 14, y + 18, text="Résumé facture", anchor="w", fill=accent, font=("Segoe UI", 10, "bold"))
        elif page_key == "checkout":
            y = top + 270
            form_right = width * 0.68
            summary_left = width * 0.7
            canvas.create_rectangle(left, y, form_right, y + 420, fill=section_bg, outline="#dbe3ef")
            canvas.create_text(
                left + 14,
                y + 20,
                text=(section_title or "Checkout sécurisé")[:62],
                anchor="w",
                fill=section_text,
                font=("Segoe UI", 11, "bold"),
            )
            canvas.create_text(
                left + 14,
                y + 44,
                text=(section_subtitle or "Complétez vos coordonnées")[:78],
                anchor="w",
                fill=section_text,
                font=("Segoe UI", 9),
            )
            canvas.create_text(
                left + 14,
                y + 64,
                text=(section_body or "Adresse livraison + validation paiement")[:88],
                anchor="w",
                fill=accent,
                font=("Segoe UI", 8),
            )
            field_width = form_right - left - 28
            for i in range(6):
                input_top = y + 90 + (i * 38)
                canvas.create_rectangle(
                    left + 14,
                    input_top,
                    left + 14 + field_width,
                    input_top + 24,
                    fill="#f8fafc",
                    outline="#dbe3ef",
                )
            paypal_top = y + 334
            canvas.create_rectangle(left + 14, paypal_top, left + 14 + field_width, paypal_top + 34, fill="#eef2ff", outline="#c7d2fe")
            canvas.create_text(left + 24, paypal_top + 18, text="PayPal", anchor="w", fill=accent, font=("Segoe UI", 10, "bold"))
            canvas.create_rectangle(
                left + 14,
                paypal_top + 44,
                left + 190,
                paypal_top + 74,
                fill=section_button_bg,
                outline="",
            )
            canvas.create_text(
                left + 102,
                paypal_top + 59,
                text=section_button_text_label[:30],
                fill=section_button_text,
                font=("Segoe UI", 9, "bold"),
            )
            canvas.create_rectangle(summary_left, y, right, y + 420, fill=section_bg, outline="#dbe3ef")
            canvas.create_text(summary_left + 14, y + 20, text="Facture", anchor="w", fill=section_text, font=("Segoe UI", 10, "bold"))
            for i in range(5):
                line_y = y + 56 + (i * 32)
                canvas.create_text(summary_left + 14, line_y, text=f"Article {i + 1}", anchor="w", fill="#475569", font=("Segoe UI", 8))
                canvas.create_text(right - 14, line_y, text="$00.00", anchor="e", fill=accent, font=("Segoe UI", 8, "bold"))
            canvas.create_line(summary_left + 14, y + 250, right - 14, y + 250, fill="#cbd5e1")
            canvas.create_text(summary_left + 14, y + 278, text="Total", anchor="w", fill=section_text, font=("Segoe UI", 9, "bold"))
            canvas.create_text(right - 14, y + 278, text="$000.00", anchor="e", fill=accent, font=("Segoe UI", 10, "bold"))
        elif page_key in {"login", "register", "checkout_success"}:
            y = top + 280
            box_w = min(500, right - left)
            cx = width / 2
            canvas.create_rectangle(cx - box_w / 2, y, cx + box_w / 2, y + 320, fill="#ffffff", outline="#dbe3ef")
            canvas.create_text(cx, y + 26, text="Bloc central", anchor="center", fill=accent, font=("Segoe UI", 11, "bold"))
            for i in range(3):
                canvas.create_rectangle(cx - (box_w / 2) + 22, y + 60 + (i * 54), cx + (box_w / 2) - 22, y + 95 + (i * 54), fill="#f8fafc", outline="#e2e8f0")
        elif page_key in {"product"}:
            y = top + 270
            canvas.create_rectangle(left, y, width * 0.54, y + 420, fill="#ffffff", outline="#dbe3ef")
            canvas.create_text(left + 14, y + 18, text="Infos produit", anchor="w", fill=accent, font=("Segoe UI", 10, "bold"))
            canvas.create_rectangle(width * 0.56, y, right, y + 420, fill="#ffffff", outline="#dbe3ef")
            canvas.create_text(width * 0.56 + 14, y + 18, text="Galerie image", anchor="w", fill=accent, font=("Segoe UI", 10, "bold"))
        else:
            y = top + 270
            canvas.create_rectangle(left, y, right, y + 420, fill="#ffffff", outline="#dbe3ef")
            canvas.create_text(left + 14, y + 18, text="Section information", anchor="w", fill=accent, font=("Segoe UI", 10, "bold"))

    def _draw_experience_preview_layout(
        self,
        canvas: Canvas,
        *,
        width: int,
        left: int,
        right: int,
        top: int,
        section_bg: str,
        section_text: str,
        section_button_bg: str,
        section_button_text: str,
        section_title: str,
        section_subtitle: str,
        section_body: str,
        section_button_text_label: str,
        accent: str,
    ) -> None:
        gap = 16
        column_width = (right - left - gap) / 2
        card_h = 190
        metrics_top = top + 20

        cards = [
            (section_title or "Indicateurs marché en direct", "Produits: 128 | Catégories: 14 | Prix moyen: 79"),
            (section_subtitle or "Catégories dominantes", "Outdoor 42  •  Running 31  •  Techwear 19"),
            (section_body or "Architecture de prix", "Entry 21  •  Core 77  •  Premium 30"),
        ]

        for idx, (title, hint) in enumerate(cards):
            row = idx // 2
            col = idx % 2
            x1 = left + (col * (column_width + gap))
            y1 = metrics_top + (row * (card_h + gap))
            x2 = x1 + column_width
            y2 = y1 + card_h
            canvas.create_rectangle(x1, y1, x2, y2, fill=section_bg, outline="#dbe3ef")
            canvas.create_text(x1 + 16, y1 + 24, text=title[:80], anchor="w", fill=section_text, font=("Segoe UI", 11, "bold"))
            canvas.create_rectangle(x1 + 16, y1 + 46, x1 + 130, y1 + 70, fill=section_button_bg, outline="")
            canvas.create_text(
                x1 + 73,
                y1 + 58,
                text="Vue synthèse",
                fill=section_button_text,
                font=("Segoe UI", 8, "bold"),
            )
            canvas.create_text(x1 + 16, y1 + 98, text=hint, anchor="w", fill=accent, font=("Segoe UI", 9))
            canvas.create_text(
                x1 + 16,
                y2 - 22,
                text="Bloc inspiré de experience.html / .experience-card",
                anchor="w",
                fill="#64748b",
                font=("Segoe UI", 8),
            )

        recent_y = metrics_top + (2 * (card_h + gap))
        recent_h = 260
        canvas.create_rectangle(left, recent_y, right, recent_y + recent_h, fill=section_bg, outline="#dbe3ef")
        canvas.create_text(
            left + 16,
            recent_y + 24,
            text=(section_button_text_label or "Dernières nouveautés")[:80],
            anchor="w",
            fill=section_text,
            font=("Segoe UI", 11, "bold"),
        )

        item_gap = 12
        item_w = (right - left - 16 * 2 - item_gap * 2) / 3
        for i in range(3):
            x1 = left + 16 + i * (item_w + item_gap)
            x2 = x1 + item_w
            y1 = recent_y + 42
            y2 = recent_y + recent_h - 16
            canvas.create_rectangle(x1, y1, x2, y2, fill="#ffffff", outline="#e2e8f0")
            canvas.create_rectangle(x1 + 8, y1 + 8, x2 - 8, y1 + 72, fill="#edf2f7", outline="")
            canvas.create_text(x1 + 10, y1 + 88, text=f"Produit {i + 1}", anchor="w", fill=section_text, font=("Segoe UI", 9, "bold"))
            canvas.create_text(x1 + 10, y1 + 106, text="Description courte...", anchor="w", fill="#64748b", font=("Segoe UI", 8))
            canvas.create_text(x1 + 10, y2 - 14, text="$00.00", anchor="w", fill=accent, font=("Segoe UI", 9, "bold"))

    def save_site_settings(self) -> None:
        self._persist_site_settings()
        self.refresh_all()
        self.update_site_preview()
        messagebox.showinfo("Succès", "Les paramètres de la page web ont été sauvegardés.")


def main():
    root = Tk()
    AdminApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
