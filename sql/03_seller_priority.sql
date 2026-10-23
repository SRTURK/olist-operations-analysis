-- Only single-seller orders; avoid attributing the same order to multiple sellers.
WITH metrics AS (
 SELECT seller_id, COUNT(*) orders, SUM(is_late) late_orders, AVG(is_late) late_rate,
        COUNT(bad_review) reviewed_orders, AVG(bad_review) bad_review_rate,
        SUM(merchandise_value) merchandise_value
 FROM analysis_orders WHERE seller_count=1
 GROUP BY seller_id HAVING COUNT(*)>=100
), scored AS (
 SELECT *, (late_rate+3.8416/(2*orders)-1.96*SQRT(late_rate*(1-late_rate)/orders+3.8416/(4*orders*orders)))/(1+3.8416/orders) AS late_rate_wilson_lower
 FROM metrics
)
SELECT *, DENSE_RANK() OVER(ORDER BY late_orders DESC) AS late_count_rank
FROM scored ORDER BY late_orders DESC, late_rate_wilson_lower DESC, seller_id;
