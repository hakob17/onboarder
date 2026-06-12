CREATE TABLE IF NOT EXISTS payments (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL,
  amount_cents INT NOT NULL,
  provider VARCHAR(32),
  status VARCHAR(24) NOT NULL DEFAULT 'new',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS refunds (
  id BIGSERIAL PRIMARY KEY,
  payment_id BIGINT NOT NULL,
  amount_cents INT NOT NULL,
  reason VARCHAR(120)
);
