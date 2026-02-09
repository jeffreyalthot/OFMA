# OFMA - ELIT21

Système complet ELIT21 combinant :
- **Site Web de vente (Flask)** avec login/register, template marketplace premium, pages produit, scrolling pour le catalogue.
- **Interface Tkinter de gestion** pour articles, commandes, dashboard finance et transactions.
- **Base de données SQLite** centralisée pour utilisateurs, articles, images (BLOB), commandes, paiements, transactions.

## Lancement rapide

```bash
python run.py
```

- Le site web est disponible sur `http://localhost:5000`.
- L'interface Tkinter s'ouvre pour gérer l'inventaire et les commandes.

## Variables d'environnement

- `PAYPAL_CLIENT_ID` : identifiant PayPal (sandbox/production)
- `PAYPAL_ENV` : `sandbox` ou `live`
- `ELIT21_SECRET` : secret de session Flask

## Structure

```
elit21/
  admin/   # Interface Tkinter
  web/     # Application Flask
  assets/  # CSS
  templates/ # HTML
```

Aucun article n'est créé par défaut : la vitrine démarre vierge et se remplit via l'interface Tkinter.
