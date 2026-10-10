-- name: daily_revenue
SELECT date(created_at) AS day, COUNT(*) AS orders, ROUND(SUM(total),2) AS revenue
FROM orders
GROUP BY day
ORDER BY day DESC
LIMIT 7;

-- name: top_services
SELECT s.name, COUNT(*) AS pieces, ROUND(SUM(oi.price),2) AS revenue
FROM order_items oi
JOIN services s ON s.id = oi.service_id
GROUP BY s.id
ORDER BY pieces DESC;

-- name: orders_by_weekday
SELECT strftime('%w', created_at) AS weekday, COUNT(*) AS orders
FROM orders
GROUP BY weekday
ORDER BY weekday;

-- name: late_orders
SELECT o.id, c.name, o.due_at, o.status
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.status IN ('received','washing') AND o.due_at < datetime('now')
ORDER BY o.due_at;

-- name: top_customers
SELECT c.name, COUNT(o.id) AS orders, ROUND(SUM(o.total),2) AS spent
FROM customers c
JOIN orders o ON o.customer_id = c.id
GROUP BY c.id
ORDER BY spent DESC
LIMIT 5;

-- name: low_inventory
SELECT name, quantity, min_level
FROM inventory
WHERE quantity <= min_level;
