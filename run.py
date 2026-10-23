"""SQL-first Olist operations analysis. Run from any working directory."""
from pathlib import Path
import sys
import json
import numpy as np
import pandas as pd
import duckdb
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import setup, save_table, table, report, metadata, plt, wilson_lower

BASE=Path(__file__).resolve().parent
OUT=BASE/'reports'
SQL=BASE/'sql'

def main():
    setup()
    OUT.mkdir(exist_ok=True)
    (BASE/'data/processed').mkdir(parents=True, exist_ok=True)
    db=duckdb.connect(str(BASE/'data/processed/olist.duckdb'))
    names={'orders':'olist_orders_dataset.csv','items':'olist_order_items_dataset.csv',
           'payments':'olist_order_payments_dataset.csv','reviews':'olist_order_reviews_dataset.csv',
           'customers':'olist_customers_dataset.csv','products':'olist_products_dataset.csv',
           'sellers':'olist_sellers_dataset.csv','translations':'product_category_name_translation.csv'}
    for name, file in names.items():
        p=(BASE/'data/raw'/file).as_posix().replace("'", "''")
        db.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT *, ROW_NUMBER() OVER() source_row FROM read_csv_auto('{p}', sample_size=-1)")
    db.execute((SQL/'01_order_mart.sql').read_text(encoding='utf-8'))
    q=lambda sql: db.execute(sql).df()
    scalar=lambda sql: db.execute(sql).fetchone()[0]
    checks=[]
    def check(name, actual, expected, tolerance=0):
        passed=abs(actual-expected)<=tolerance
        checks.append({'check':name,'actual':actual,'expected':expected,'passed':bool(passed)})
        if not passed:
            raise AssertionError(f'{name}: {actual} != {expected}')
    check('order grain count',scalar('SELECT COUNT(*) FROM order_mart'),scalar('SELECT COUNT(*) FROM orders'))
    check('order primary key',scalar('SELECT COUNT(*)-COUNT(DISTINCT order_id) FROM orders'),0)
    check('mart primary key',scalar('SELECT COUNT(*)-COUNT(DISTINCT order_id) FROM order_mart'),0)
    for t, key in [('customers','customer_id'),('products','product_id'),('sellers','seller_id'),('translations','product_category_name')]:
        check(t+' primary key',scalar(f'SELECT COUNT(*)-COUNT(DISTINCT {key}) FROM {t}'),0)
    for t in ['items','payments','reviews']:
        check(t+' orphan order',scalar(f'SELECT COUNT(*) FROM {t} a ANTI JOIN orders b USING(order_id)'),0)
    check('customer foreign key',scalar('SELECT COUNT(*) FROM orders ANTI JOIN customers USING(customer_id)'),0)
    check('item product foreign key',scalar('SELECT COUNT(*) FROM items ANTI JOIN products USING(product_id)'),0)
    check('item seller foreign key',scalar('SELECT COUNT(*) FROM items ANTI JOIN sellers USING(seller_id)'),0)
    check('item composite key',scalar('SELECT COUNT(*) FROM (SELECT order_id,order_item_id FROM items GROUP BY ALL HAVING COUNT(*)>1)'),0)
    check('payment composite key',scalar('SELECT COUNT(*) FROM (SELECT order_id,payment_sequential FROM payments GROUP BY ALL HAVING COUNT(*)>1)'),0)
    check('item value reconciliation',scalar('SELECT SUM(merchandise_value) FROM order_mart'),scalar('SELECT SUM(price) FROM items'),0.01)
    check('payment value reconciliation',scalar('SELECT SUM(paid_value) FROM order_mart'),scalar('SELECT SUM(payment_value) FROM payments'),0.01)
    check('negative item value',scalar('SELECT COUNT(*) FROM items WHERE price<0 OR freight_value<0'),0)
    audit=q('''SELECT COUNT(*) total_orders,
      COUNT(*) FILTER(WHERE order_status='delivered') delivered_status,
      COUNT(*) FILTER(WHERE delivery_eligible) eligible_all_dates,
      COUNT(*) FILTER(WHERE order_status='delivered' AND NOT delivery_eligible) invalid_delivered,
      COUNT(*) FILTER(WHERE review_score IS NULL) no_review,
      COUNT(*) FILTER(WHERE merchandise_value IS NULL) no_items,
      COUNT(*) FILTER(WHERE paid_value IS NULL) no_payment,
      COUNT(*) FILTER(WHERE ABS(paid_value-merchandise_value-freight_value)>0.05) amount_mismatch,
      COUNT(*) FILTER(WHERE seller_count>1) multi_seller_orders
      FROM order_mart''')
    save_table(audit,OUT,'data_quality_summary')
    anomalies=q('''SELECT order_id,order_status,merchandise_value,freight_value,paid_value,
      paid_value-merchandise_value-freight_value discrepancy
      FROM order_mart WHERE ABS(paid_value-merchandise_value-freight_value)>0.05 ORDER BY ABS(discrepancy) DESC''')
    save_table(anomalies,OUT,'payment_reconciliation_exceptions')
    review_dupes=scalar('SELECT COUNT(*)-COUNT(DISTINCT order_id) FROM reviews')
    naive=scalar('SELECT SUM(i.price) FROM items i JOIN payments p USING(order_id)')
    matched=scalar('SELECT SUM(price) FROM items SEMI JOIN payments USING(order_id)')
    inflation=naive/matched-1
    save_table(pd.DataFrame([{'correct_item_value_matched_orders':matched,'naive_join_item_value':naive,'inflation_rate':inflation}]),OUT,'join_fanout_demonstration')
    monthly=q((SQL/'02_monthly_metrics.sql').read_text(encoding='utf-8'))
    check('monthly counts',int(monthly.orders.sum()),scalar('SELECT COUNT(*) FROM analysis_orders'))
    save_table(monthly,OUT,'monthly_metrics')
    seller=q((SQL/'03_seller_priority.sql').read_text(encoding='utf-8'))
    save_table(seller,OUT,'seller_priority')
    a=q('SELECT * FROM analysis_orders ORDER BY order_id')
    total=len(a); late=a.is_late.mean(); reviewed=a.dropna(subset=['bad_review']).copy()
    # Rates by delay buckets; numerator and denominator both retained.
    a['delay_bucket']=pd.cut(a.delay_days,[-np.inf,0,3,7,14,np.inf],labels=['按期/提前','延迟1–3天','延迟4–7天','延迟8–14天','延迟15天以上'])
    buckets=a.groupby('delay_bucket',observed=True).agg(orders=('order_id','size'),reviewed=('bad_review','count'),bad_reviews=('bad_review','sum'),bad_review_rate=('bad_review','mean')).reset_index()
    buckets['review_coverage']=buckets.reviewed/buckets.orders
    save_table(buckets,OUT,'delay_review_association')
    assoc=reviewed.groupby('is_late').agg(n=('order_id','size'),bad_rate=('bad_review','mean'))
    gap=float(assoc.loc[1,'bad_rate']-assoc.loc[0,'bad_rate'])
    # Sensitivity: exclude reviews created before the calendar date of delivery.
    post=reviewed[pd.to_datetime(reviewed.review_creation_date).dt.normalize()>=pd.to_datetime(reviewed.order_delivered_customer_date).dt.normalize()]
    sens=post.groupby('is_late').agg(n=('order_id','size'),bad_rate=('bad_review','mean')).reset_index()
    save_table(sens,OUT,'post_delivery_review_sensitivity')
    # Identify largest month-on-month deterioration, requiring 1,000 orders in each month.
    candidates=monthly[(monthly.orders>=1000)&(monthly.orders.shift(1)>=1000)].dropna(subset=['late_rate_change'])
    hit=candidates.loc[candidates.late_rate_change.idxmax()]
    month=pd.Timestamp(hit.purchase_month); prev=month-pd.DateOffset(months=1)
    pair=a[a.purchase_month.isin([month,prev])]
    group=pair.groupby(['purchase_month','customer_state']).agg(n=('order_id','size'),rate=('is_late','mean'))
    g0=group.loc[prev]; g1=group.loc[month]
    common=g0.index.intersection(g1.index)
    d=pd.DataFrame({'state':common,'n0':g0.loc[common,'n'].values,'n1':g1.loc[common,'n'].values,
                    'r0':g0.loc[common,'rate'].values,'r1':g1.loc[common,'rate'].values})
    d['w0']=d.n0/d.n0.sum(); d['w1']=d.n1/d.n1.sum()
    d['within_effect']=(d.w0+d.w1)/2*(d.r1-d.r0)
    d['mix_effect']=(d.r0+d.r1)/2*(d.w1-d.w0)
    d['total_contribution']=d.within_effect+d.mix_effect
    delta=(d.w1*d.r1).sum()-(d.w0*d.r0).sum()
    check('symmetric decomposition identity',float(d.total_contribution.sum()),float(delta),1e-10)
    save_table(d.sort_values('total_contribution',ascending=False),OUT,'state_decomposition')
    # Similar decomposition at dominant category granularity is a diagnostic cross-check.
    cats=pair.groupby(['purchase_month','category']).agg(orders=('order_id','size'),late_rate=('is_late','mean')).reset_index()
    save_table(cats,OUT,'category_month_diagnostic')
    save_table(pd.DataFrame(checks),OUT,'validation_checks')
    fig,ax=plt.subplots(figsize=(10,4.6))
    ax.plot(monthly.purchase_month,monthly.late_rate*100,marker='o',label='月延迟率')
    ax.plot(monthly.purchase_month,monthly.rolling_3m_late_rate*100,linestyle='--',label='近3个月加权延迟率')
    ax.axvline(month,color='#E38B29',alpha=.5)
    ax.set(title='履约延迟率：按购买月份观察',ylabel='已送达有效订单中的占比（%）',xlabel='购买月份')
    ax.legend(); fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(OUT/'monthly_late_rate.png'); plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4.6))
    ax.bar(buckets.delay_bucket.astype(str),buckets.bad_review_rate*100,color='#176B87')
    for i,row in buckets.iterrows(): ax.text(i,row.bad_review_rate*100+1,f'{row.bad_review_rate:.1%}\nn={int(row.reviewed):,}',ha='center',fontsize=9)
    ax.set(title='延迟与差评的关联（仅有评价订单）',ylabel='1–2星评价占比（%）',ylim=(0,100))
    fig.tight_layout(); fig.savefig(OUT/'delay_reviews.png'); plt.close(fig)
    top=d.nlargest(8,'total_contribution').sort_values('total_contribution')
    fig,ax=plt.subplots(figsize=(10,4.6)); y=np.arange(len(top))
    ax.barh(y-.17,top.within_effect*100,height=.32,label='地区内延迟率变化')
    ax.barh(y+.17,top.mix_effect*100,height=.32,label='订单地区结构变化')
    ax.set_yticks(y,top.state); ax.set(title=f'{prev:%Y-%m} → {month:%Y-%m} 延迟率变化贡献',xlabel='百分点')
    ax.legend(); fig.tight_layout(); fig.savefig(OUT/'state_decomposition.png'); plt.close(fig)
    top_seller_share=seller.head(10).late_orders.sum()/a.is_late.sum()
    summary={'orders_raw':int(audit.total_orders.iloc[0]),'analysis_orders':total,'late_rate':float(late),
      'join_inflation':float(inflation),'bad_rate_on_time':float(assoc.loc[0,'bad_rate']),
      'bad_rate_late':float(assoc.loc[1,'bad_rate']),'bad_review_gap':gap,
      'anomaly_month':month.strftime('%Y-%m'),'previous_month':prev.strftime('%Y-%m'),
      'late_rate_change':float(hit.late_rate_change),'within_effect':float(d.within_effect.sum()),
      'mix_effect':float(d.mix_effect.sum()),'validation_checks':len(checks),
      'review_extra_rows':int(review_dupes),'top10_seller_late_share':float(top_seller_share)}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    status=q('SELECT order_status,COUNT(*) orders FROM orders GROUP BY order_status ORDER BY orders DESC')
    body=f'''完成日期：2026-10-23 · SQL + Python · 公开历史数据的回顾性诊断

## 业务结论

1. 原始订单 **{summary['orders_raw']:,}** 笔，主分析纳入 **{total:,}** 笔 2017-01 至 2018-08 的有效已送达订单，延迟率 **{late:.2%}**。
2. 未聚合就连接商品明细与支付明细，会使匹配订单的商品金额高估 **{inflation:.2%}**。已通过先聚合再关联修复，并与源表金额对账。
3. 延迟订单差评率 **{assoc.loc[1,'bad_rate']:.2%}**，按期订单 **{assoc.loc[0,'bad_rate']:.2%}**，相差 **{gap*100:.2f} 个百分点**。限制到送达当日或之后创建的评价，二者变为 **{sens.loc[sens.is_late==1,'bad_rate'].iloc[0]:.2%}** 与 **{sens.loc[sens.is_late==0,'bad_rate'].iloc[0]:.2%}**，说明评价时点影响很大。这些都是关联，不能推断改善配送一定带来同等幅度的评分提升。
4. 最大月度恶化出现在 **{prev:%Y-%m} → {month:%Y-%m}**：全样本延迟率上升 **{hit.late_rate_change*100:.2f} 个百分点**。共同地区样本分解中，地区内部变化贡献 **{d.within_effect.sum()*100:.2f} 个百分点**，地区订单结构贡献 **{d.mix_effect.sum()*100:.2f} 个百分点**。

## 数据口径与质量

来源：[Olist 发布页](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)。原始 CSV、下载来源和 SHA256 见根目录 data_manifest.json；没有生成模拟业务数据。数据为 2016–2018 年历史数据，结论不代表当前 Olist 经营状况。

{table(audit)}

- 数据库加载订单、商品明细、支付、评价、客户、商品、商家、品类翻译 8 张表；地理坐标文件保留但未用于分析。
- 日期按原数据的无时区本地时间解析。延迟定义为实际送达**日历日期**晚于预计送达日，避免把当天午夜之后的送达都算延迟。
- 差评定义为 1–2 星；无评价不计为好评。一个订单只保留最后答复的评价（ROW_NUMBER），共折叠 {review_dupes:,} 条额外评价记录。时间并列按 review_id、源文件行号确定性排序。
- 商品金额不含运费；支付金额含运费且可能存在业务差异。误差大于 0.05 巴西雷亚尔的订单单独输出，未强行覆盖。两类金额与各自源表分别对账。
- 商家排查只使用单商家订单，至少 100 单；混合品类订单按商品金额最大的品类归类，仅供订单诊断。
- 全部 **{len(checks)} 项断言通过**；详细数值见 validation_checks.csv。金额例外见 payment_reconciliation_exceptions.csv。

原始订单状态：

{table(status,0)}

主分析仅包含已送达订单，存在完成订单选择；取消/未送达订单不应据此视为正常履约。2018-09 后记录稀疏，排除整段尾部；月末订单仍可能受提取时点与送达状态筛选影响。缺少可信的数据快照日，不能宣称彻底消除了右删失。

## 指标异动：从总量到地区

![月度趋势](monthly_late_rate.png)

选择规则在代码中固定为“相邻两月均不少于 1,000 单的最大延迟率正向变化”，属于探索性定位，未把筛选后的峰值当作独立显著性检验。

对共同覆盖的 {len(common)} 个地区使用对称分解：地区内贡献 = 平均订单权重 × 延迟率变化；结构贡献 = 平均延迟率 × 权重变化。共同地区覆盖前月 {d.n0.sum()/len(pair[pair.purchase_month==prev]):.2%}、当月 {d.n1.sum()/len(pair[pair.purchase_month==month]):.2%}。两项之和等于共同地区总变化（已断言核验）。

![地区贡献](state_decomposition.png)

{table(d.sort_values('total_contribution',ascending=False)[['state','n0','n1','r0','r1','within_effect','mix_effect']].head(8))}

表中率和贡献均为小数比例；乘以 100 得到百分比或百分点。这是算术分解，不能解释为物流供应商、天气或罢工等原因；数据没有这些外部变量。

## 延迟与客户体验

![延迟与评价](delay_reviews.png)

{table(buckets)}

评价可能在实际送达前创建。补充限制“评价创建日期不早于送达日期”后得到：

{table(sens)}

该敏感性筛选也会改变人群，不能消除所有混杂。地区、品类、商家服务与订单难度都可能同时影响延迟和评价。

## 建议排查顺序

1. 优先调查峰值月份中贡献最大的地区，再交叉检查 category_month_diagnostic.csv 中的品类变化，核实是普遍运力问题还是具体线路/品类问题。
2. 对 seller_priority.csv 前 10 个高延迟数量商家做运营核查。这些商家（每家至少 100 个单商家有效订单）的延迟单合计占全部分析延迟订单 **{top_seller_share:.2%}**；这是可排查覆盖面，不是可承诺消除的损失。
3. 同时看绝对延迟单数、延迟率及 Wilson 95% 下界，避免小样本商家误入榜单。下界是单商家的描述性区间，不是多重比较校正后的处罚依据。
4. 若实施预计到货提示或物流分流，另行做随机试点，并同时观察延迟率、取消率、投诉/退货和成本；本数据没有线上干预效果。

前 10 个排查对象（匿名商家 ID）：

{table(seller[['seller_id','orders','late_orders','late_rate','late_rate_wilson_lower','bad_review_rate']].head(10))}

## 复现与交付

在本仓库目录运行 `python run.py`。原始数据 → 8 张原始表 → 聚合/去重中间表 → 订单宽表 → SQL 指标 → Python 分解与图表 → 本报告。数据关系、指标字典与面试说明见项目 README.md。
'''
    report(OUT,'电商履约与客户体验诊断',body)
    metadata(OUT,{'project':'olist','seed':None,'checks_passed':len(checks),'sql_dialect':'DuckDB'})
    db.close()
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
