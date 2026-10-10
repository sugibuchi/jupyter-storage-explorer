SELECT date_trunc('month', order_date) AS month,
       sum(quantity * unit_price) AS revenue
FROM orders
GROUP BY 1
ORDER BY 1;
