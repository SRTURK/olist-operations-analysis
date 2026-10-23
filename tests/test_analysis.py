from pathlib import Path
import unittest
import numpy as np
import pandas as pd
import duckdb

ROOT=Path(__file__).resolve().parents[1]

class AnalysisTests(unittest.TestCase):
    def test_real_mart_sql_on_fanout_and_date_boundaries(self):
        # Two items, two payments and two reviews on one order: raw join would yield 8 rows.
        db=duckdb.connect()
        db.execute('''CREATE TABLE orders AS SELECT 'o1' order_id,'c1' customer_id,'delivered' order_status,
          TIMESTAMP '2017-01-01 12:00:00' order_purchase_timestamp,
          TIMESTAMP '2017-01-05 18:00:00' order_delivered_customer_date,
          TIMESTAMP '2017-01-05 00:00:00' order_estimated_delivery_date;
        CREATE TABLE items(order_id VARCHAR,order_item_id INTEGER,product_id VARCHAR,seller_id VARCHAR,price DOUBLE,freight_value DOUBLE);
        INSERT INTO items VALUES ('o1',1,'p1','s1',10,1),('o1',2,'p1','s1',20,2);
        CREATE TABLE payments(order_id VARCHAR,payment_value DOUBLE);
        INSERT INTO payments VALUES ('o1',11),('o1',22);
        CREATE TABLE reviews(order_id VARCHAR,review_id VARCHAR,review_score INTEGER,review_creation_date TIMESTAMP,review_answer_timestamp TIMESTAMP,source_row INTEGER);
        INSERT INTO reviews VALUES ('o1','r1',1,'2017-01-05','2017-01-05',1),('o1','r2',5,'2017-01-06','2017-01-06',2);
        CREATE TABLE customers AS SELECT 'c1' customer_id,'u1' customer_unique_id,'SP' customer_state;
        CREATE TABLE products AS SELECT 'p1' product_id,'categoria' product_category_name;
        CREATE TABLE translations AS SELECT 'categoria' product_category_name,'category' product_category_name_english;''')
        db.execute((ROOT/'sql/01_order_mart.sql').read_text(encoding='utf-8'))
        row=db.execute('SELECT merchandise_value,paid_value,review_score,delay_days,is_late FROM analysis_orders').fetchone()
        self.assertEqual(row,(30.,33.,5,0,0))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM order_mart').fetchone()[0],1)
        # A next-day arrival must be late, even when only one hour after midnight.
        db.execute("UPDATE orders SET order_delivered_customer_date='2017-01-06 01:00:00'")
        db.execute((ROOT/'sql/01_order_mart.sql').read_text(encoding='utf-8'))
        self.assertEqual(db.execute('SELECT is_late FROM analysis_orders').fetchone()[0],1)
        db.close()

    def test_manifest_hashes(self):
        import json,hashlib
        manifest=json.loads((ROOT/'data_manifest.json').read_text(encoding='utf-8'))
        for entry in manifest['files']:
            # Normalize Windows paths when moving this repository to Linux/macOS.
            path=ROOT/entry['file'].replace('\\','/')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),entry['sha256'])

if __name__=='__main__': unittest.main()
