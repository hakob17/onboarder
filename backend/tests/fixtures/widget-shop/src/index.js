const express = require('express');
const axios = require('axios');
const { Pool } = require('pg');

const app = express();
const pool = new Pool();

app.get('/api/widgets', async (req, res) => {
  const rows = await pool.query('SELECT id, name, price FROM widgets WHERE active = true');
  res.json(rows.rows);
});

app.post('/api/widgets/:id/order', async (req, res) => {
  await pool.query('INSERT INTO widget_orders (widget_id, qty) VALUES ($1, $2)', [req.params.id, req.body.qty]);
  const charge = await axios.post(`${process.env.BILLING_URL}/api/charges`, { amount: req.body.amount });
  res.json({ ok: charge.status === 200 });
});

module.exports = app;
