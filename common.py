"""Presentation helpers for this standalone project."""
from pathlib import Path
import json
import platform
import importlib.metadata
import html
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import markdown

def setup():
    plt.rcParams.update({'font.family': ['Microsoft YaHei', 'DejaVu Sans'],
                         'axes.unicode_minus': False, 'figure.dpi': 150,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.titleweight': 'bold', 'axes.titlepad': 14,
                         'axes.prop_cycle': matplotlib.cycler(color=['#176B87','#E38B29','#608C62','#8556A6'])})

def table(df, decimals=4):
    return df.to_markdown(index=False, floatfmt=f'.{decimals}f')

def save_table(df, out, name):
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out/f'{name}.csv', index=False, encoding='utf-8-sig')
    return df

def report(out, title, body):
    out.mkdir(parents=True, exist_ok=True)
    text = f'# {title}\n\n{body.strip()}\n'
    (out/'REPORT.md').write_text(text, encoding='utf-8')
    css = '''body{font:16px/1.8 "Microsoft YaHei",system-ui,sans-serif;color:#213547;background:#f5f7fa;margin:0}main{max-width:1080px;margin:36px auto;padding:48px;background:white;border-top:7px solid #176b87}h1{font-size:32px;line-height:1.4}h2{margin-top:40px;color:#176b87}table{display:block;overflow:auto;border-collapse:collapse;font-size:13px;width:100%}th,td{padding:9px 12px;border-bottom:1px solid #dce4ea;text-align:left;white-space:nowrap}th{background:#edf5f8}img{max-width:100%;height:auto}a{color:#176b87}blockquote{margin:18px 0;padding:8px 22px;background:#edf5f8;border-left:4px solid #176b87}code{background:#eef2f5;padding:2px 5px}pre{overflow:auto;padding:16px;background:#eef2f5}@media print{main{margin:0;padding:10px}body{background:white}h2{break-after:avoid}img,table{break-inside:avoid}}'''
    doc = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+css+'</style><main>'+markdown.markdown(text, extensions=['tables','fenced_code'])+'</main></html>'
    (out/'REPORT.html').write_text(doc, encoding='utf-8')

def metadata(out, extra):
    packages = ['numpy','pandas','matplotlib','duckdb']
    payload={'python': platform.python_version(), 'packages': {p:importlib.metadata.version(p) for p in packages}, **extra}
    (out/'run_metadata.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

def wilson_lower(k, n, z=1.96):
    p = np.asarray(k)/np.asarray(n)
    return (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
