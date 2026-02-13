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
- `PAYPAL_CLIENT_SECRET` : secret API PayPal
- `PAYPAL_SECRET_KEY_1` : alias accepté pour compatibilité (si `PAYPAL_CLIENT_SECRET` absent)
- `PAYPAL_ENV` : `sandbox` ou `live`
- `PAYPAL_DEBUG` : `1`/`true` pour activer les logs détaillés PayPal (backend + SDK frontend)
- `PAYPAL_ENV_AUTO_FALLBACK` : `1` par défaut, tente automatiquement l'autre environnement si `invalid_client` (utile si clés live/sandbox inversées)
- `SHIPPING_FEE` : frais de livraison fixes
- `ELIT21_SECRET` : secret de session Flask

Exemple de fichier `.env` :

```env
APP_NAME=AI_market
ELIT21_SECRET=change-me
PAYPAL_CLIENT_ID=your-paypal-client-id
PAYPAL_SECRET_KEY_1=your-paypal-client-secret
PAYPAL_ENV=sandbox
PAYPAL_DEBUG=1
SHIPPING_FEE=9.99
```


### Configuration PayPal (sans webhooks)

1. Crée une application **REST** dans PayPal Developer.
2. Copie `Client ID` + `Secret` du même environnement (**Sandbox** ou **Live**).
3. Mets `PAYPAL_ENV` sur cet environnement (`sandbox` ou `live`).
4. Redémarre `python run.py` après toute modification de `.env`.

Notes:
- Les webhooks ne sont pas requis pour ce flux: la confirmation passe par `create-paypal-order` puis `capture-paypal-order`.
- Le backend configure aussi `return_url` et `cancel_url` pour couvrir le fallback redirection (popup bloqué).
- Le backend vérifie à la capture: statut `COMPLETED`, `reference_id` de la commande, devise `EUR` et montant attendu.
- Si `PAYPAL_ENV` est mauvais mais les clés sont valides, le backend tente automatiquement l'autre environnement (désactivable via `PAYPAL_ENV_AUTO_FALLBACK=0`).

## Structure

```
elit21/
  admin/   # Interface Tkinter
  web/     # Application Flask
  assets/  # CSS
  templates/ # HTML
```

Aucun article n'est créé par défaut : la vitrine démarre vierge et se remplit via l'interface Tkinter.
