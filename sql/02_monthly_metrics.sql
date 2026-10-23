WITH monthly AS (
 SELECT purchase_month, COUNT(*) orders, SUM(merchandise_value) merchandise_value,
        AVG(merchandise_value) average_order_value,
        SUM(is_late) late_orders, AVG(is_late) late_rate,
        AVG(delivery_days) mean_delivery_days,
        COUNT(bad_review) reviewed_orders, AVG(bad_review) bad_review_rate
 FROM analysis_orders GROUP BY purchase_month
)
SELECT *, late_rate-LAG(late_rate) OVER(ORDER BY purchase_month) late_rate_change,
       orders*1.0/NULLIF(LAG(orders) OVER(ORDER BY purchase_month),0)-1 AS orders_growth,
       SUM(late_orders) OVER(ORDER BY purchase_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)*1.0/
       SUM(orders) OVER(ORDER BY purchase_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS rolling_3m_late_rate
FROM monthly ORDER BY purchase_month;
