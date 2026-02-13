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
- `SHIPPING_FEE` : frais de livraison fixes
- `ELIT21_SECRET` : secret de session Flask

Exemple de fichier `.env` :

```env
APP_NAME=AI_market
ELIT21_SECRET=change-me
PAYPAL_CLIENT_ID=AZtrIu_myFqZAEokeJLNZvFfqENW2N9VMFH4sb4YVmQw5h1ItKAa0rAjvc7cLTYGokhyPqbr0_LyAynM
PAYPAL_SECRET_KEY_1=ELmY8HCdmV_iigHzbNAlA-4oEw2Hk4ezX2MlWPBe1nlHmLCVP2shv7cJspCRaIUtW90nUrDfAo5YncOS
PAYPAL_ENV=sandbox
PAYPAL_DEBUG=1
SHIPPING_FEE=9.99
```

## Structure

```
elit21/
  admin/   # Interface Tkinter
  web/     # Application Flask
  assets/  # CSS
  templates/ # HTML
```

Aucun article n'est créé par défaut : la vitrine démarre vierge et se remplit via l'interface Tkinter.
