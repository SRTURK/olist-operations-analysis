-- DuckDB SQL. Grain: exactly one row per order, including canceled orders.
-- Never join raw items to raw payments before aggregation (fan-out).
CREATE OR REPLACE TABLE item_totals AS
SELECT order_id, COUNT(*) AS item_count, COUNT(DISTINCT seller_id) AS seller_count,
       MIN(seller_id) AS sole_seller_id, SUM(price) AS merchandise_value,
       SUM(freight_value) AS freight_value
FROM items GROUP BY order_id;

CREATE OR REPLACE TABLE payment_totals AS
SELECT order_id, COUNT(*) AS payment_rows, SUM(payment_value) AS paid_value
FROM payments GROUP BY order_id;

-- Latest answered review wins; source_row breaks otherwise identical timestamp ties.
CREATE OR REPLACE TABLE latest_reviews AS
SELECT * EXCLUDE(rn) FROM (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY order_id ORDER BY review_answer_timestamp DESC NULLS LAST,
    review_creation_date DESC NULLS LAST, review_id DESC, source_row DESC) rn
  FROM reviews
) WHERE rn=1;

-- Allocate a mixed-category order to the category with greatest merchandise value.
-- This is only an order-level diagnostic label, not a category sales fact table.
CREATE OR REPLACE TABLE dominant_categories AS
SELECT order_id, category FROM (
 SELECT i.order_id, COALESCE(t.product_category_name_english,p.product_category_name,'unknown') category,
        SUM(i.price) category_value,
        ROW_NUMBER() OVER(PARTITION BY i.order_id ORDER BY SUM(i.price) DESC, category) rn
 FROM items i LEFT JOIN products p USING(product_id)
 LEFT JOIN translations t USING(product_category_name)
 GROUP BY i.order_id, category
) WHERE rn=1;

CREATE OR REPLACE TABLE order_mart AS
SELECT o.*, c.customer_unique_id, c.customer_state,
       it.item_count, it.seller_count,
       CASE WHEN it.seller_count=1 THEN it.sole_seller_id END seller_id,
       it.merchandise_value, it.freight_value, pt.paid_value, pt.payment_rows,
       r.review_score, r.review_creation_date, r.review_answer_timestamp,
       dc.category,
       DATE_TRUNC('month', o.order_purchase_timestamp)::DATE purchase_month,
       DATE_DIFF('day', CAST(o.order_purchase_timestamp AS DATE), CAST(o.order_delivered_customer_date AS DATE)) delivery_days,
       DATE_DIFF('day', CAST(o.order_estimated_delivery_date AS DATE), CAST(o.order_delivered_customer_date AS DATE)) delay_days,
       (o.order_status='delivered' AND o.order_delivered_customer_date IS NOT NULL
         AND o.order_estimated_delivery_date IS NOT NULL
         AND o.order_delivered_customer_date >= o.order_purchase_timestamp) AS delivery_eligible,
       CASE WHEN r.review_score IS NOT NULL THEN (r.review_score<=2)::INTEGER END AS bad_review
FROM orders o
LEFT JOIN customers c USING(customer_id)
LEFT JOIN item_totals it USING(order_id)
LEFT JOIN payment_totals pt USING(order_id)
LEFT JOIN latest_reviews r USING(order_id)
LEFT JOIN dominant_categories dc USING(order_id);

-- Complete purchase months with established volume; late-2018 sparse tail excluded.
CREATE OR REPLACE VIEW analysis_orders AS
SELECT *, (delay_days>0)::INTEGER is_late
FROM order_mart
WHERE delivery_eligible AND purchase_month BETWEEN DATE '2017-01-01' AND DATE '2018-08-01';
