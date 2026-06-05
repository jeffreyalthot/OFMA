-- OFMA 0.5.1 safety migration: integer-cent accounting, PayPal idempotency, payment audit metadata.
-- SQLite-compatible and replay-safe when coordinated by elit21.db.init_db helpers.
ALTER TABLE products ADD COLUMN price_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN shipping_fee_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN subtotal_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN tax_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN total_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE order_items ADD COLUMN price_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE order_items ADD COLUMN line_total_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN transaction_total_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN capture_id TEXT;
ALTER TABLE transactions ADD COLUMN paypal_order_id TEXT;
ALTER TABLE payment_logs ADD COLUMN attempt_key TEXT;
ALTER TABLE payment_logs ADD COLUMN final_status TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_paypal_order_id ON orders(paypal_order_id) WHERE paypal_order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_capture_id ON orders(capture_id) WHERE capture_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_status_archived ON products(status, archived);
CREATE INDEX IF NOT EXISTS idx_products_category_status_archived ON products(category, status, archived);
CREATE INDEX IF NOT EXISTS idx_payment_logs_created_at ON payment_logs(created_at);
