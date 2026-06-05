# Migrations OFMA

Les migrations versionnées documentent chaque évolution de schéma. `elit21.db.init_db()` applique aujourd'hui les mêmes changements avec des helpers `ADD COLUMN IF MISSING` afin de rester rejouable avec SQLite, puis enregistre les versions dans `schema_migrations`.

Chaque nouveau changement doit :

1. ajouter un fichier `NNNN_description.sql` dans ce dossier ;
2. être idempotent ou protégé par le runner Python ;
3. backfiller les données existantes sans perte ;
4. enregistrer une entrée dans `schema_migrations`.
