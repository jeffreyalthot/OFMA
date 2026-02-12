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
- `PAYPAL_CLIENT_SECRET` : secret API associé au Client ID (jamais exposé côté front)
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


## Configuration PayPal (Checkout)

1. Créez une application REST dans le dashboard développeur PayPal (`My Apps & Credentials`).
2. Récupérez le **Client ID** et le **Client Secret** de l’environnement visé (`sandbox` pour tests, `live` pour production).
3. Exportez les variables avant de lancer l’application :

```bash
export PAYPAL_CLIENT_ID="<votre_client_id>"
export PAYPAL_CLIENT_SECRET="<votre_client_secret>"
export PAYPAL_ENV="sandbox"
```

Sur la page Checkout, l’acheteur peut se connecter à PayPal ; les informations payeur/adresse renvoyées par PayPal sont ensuite réutilisées pour finaliser la commande.
