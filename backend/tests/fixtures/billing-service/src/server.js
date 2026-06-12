const express = require('express');
const { Pool } = require('pg');

const app = express();
const pool = new Pool();

app.post('/api/charges', async (req, res) => {
  const order = await pool.query('SELECT id, total_cents FROM orders WHERE id = $1', [req.body.orderId]);
  await pool.query('INSERT INTO payments (order_id, amount_cents, status) VALUES ($1, $2, $3)',
    [req.body.orderId, order.rows[0].total_cents, 'captured']);
  res.json({ success: true });
});

app.get('/api/charges/:id', async (req, res) => {
  const rows = await pool.query('SELECT id, order_id, amount_cents, status FROM payments WHERE id = $1', [req.params.id]);
  res.json(rows.rows[0]);
});

module.exports = app;
