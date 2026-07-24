#!/usr/bin/env python3
"""
每日股市推送报告生成器
- 通过 westock-data (Node.js) 获取股票行情
- 生成自包含 HTML 报告
- 支持 GitHub Actions 定时触发 或 本地手动运行

Usage:
    python generate_report.py                          # 生成报告到当前目录
    python generate_report.py --output /path/to/dir    # 指定输出目录
    python generate_report.py --no-fetch               # 使用缓存数据（调试用）
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

# 北京时间
CST = timezone(timedelta(hours=8))

# 股票池配置
STOCK_POOL = [
    {"code": "sz300476", "name": "胜宏科技", "sector": "PCB"},
    {"code": "sz300502", "name": "新易盛", "sector": "光模块"},
    {"code": "sh688362", "name": "甬矽电子", "sector": "先进封装"},
    {"code": "sz300475", "name": "香农芯创", "sector": "存储分销"},
    {"code": "sh600584", "name": "长电科技", "sector": "封测龙头"},
    {"code": "sh603986", "name": "兆易创新", "sector": "存储MCU"},
    {"code": "sz301308", "name": "江波龙", "sector": "存储模组"},
    {"code": "sh688008", "name": "澜起科技", "sector": "内存接口"},
    {"code": "sz301377", "name": "鼎泰高科", "sector": "PCB钻针"},
    {"code": "sh601138", "name": "工业富联", "sector": "AI服务器"},
    {"code": "sz300433", "name": "蓝思科技", "sector": "消费电子"},
    {"code": "sz002281", "name": "光迅科技", "sector": "光器件"},
    {"code": "sz002371", "name": "北方华创", "sector": "半导体设备"},
    {"code": "sz300394", "name": "天孚通信", "sector": "光引擎"},
    {"code": "sh688012", "name": "中微公司", "sector": "刻蚀设备"},
    {"code": "sz002156", "name": "通富微电", "sector": "封装测试"},
    {"code": "sh512480", "name": "半导体ETF", "sector": "ETF"},
]

# westock-data 脚本路径
WESTOCK_SCRIPT = os.path.join(os.path.dirname(__file__), "westock.js")

def get_node_path():
    """获取 Node.js 路径"""
    for cmd in ["node", "nodejs"]:
        try:
            result = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print("ERROR: Node.js not found", file=sys.stderr)
    sys.exit(1)

def fetch_stock_data(node_cmd):
    """通过 westock-data 批量获取股票行情"""
    codes = ",".join([s["code"] for s in STOCK_POOL])
    
    try:
        result = subprocess.run(
            [node_cmd, WESTOCK_SCRIPT, "quote", codes],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.dirname(__file__)
        )
        if result.returncode != 0:
            print(f"ERROR running westock: {result.stderr}", file=sys.stderr)
            return None
        
        # 解析输出 - westock 输出 Markdown 表格
        return result.stdout
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None

def parse_quote_table(raw_output):
    """解析 westock-data 的 Markdown 表格输出"""
    stocks = {}
    lines = raw_output.strip().split("\n")
    
    # 找到表格分隔行和表头
    header_found = False
    headers = []
    data_started = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 跳过batch状态行
        if line.startswith("[Batch]"):
            continue
        
        # 检测表格分隔符
        if "| --- |" in line and not data_started:
            data_started = True
            continue
        
        if not data_started:
            # 找表头
            if "| code |" in line:
                header_found = True
                headers = [h.strip() for h in line.split("|")[1:-1]]
            continue
        
        # 解析数据行
        if header_found and line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= len(headers):
                row = dict(zip(headers, cells))
                code = row.get("code", "")
                if code:
                    stocks[code] = row
    
    return stocks

def color_change(val_str):
    """判断涨跌，返回CSS颜色类"""
    try:
        val = float(val_str.replace("%", "").replace("+", ""))
        if val > 0:
            return "up"
        elif val < 0:
            return "down"
        return ""
    except (ValueError, AttributeError):
        return ""

def make_tag(text, tag_type):
    """生成 HTML tag"""
    return f'<span class="tag tag-{tag_type}">{text}</span>'

def analyze_stock(row, name, sector):
    """对单只股票给出短期和中期评级"""
    try:
        chg_5d = float(row.get("chg_5d", "0").replace("%", ""))
        chg_20d = float(row.get("chg_20d", "0").replace("%", ""))
        chg_today = float(row.get("change_percent", "0").replace("%", ""))
        pe = float(row.get("pe_ratio", "0") or "0")
    except (ValueError, AttributeError):
        return {"short": ("观望", "gold"), "mid": ("观望", "gold")}

    # 短期评级逻辑 (3-5天)
    if chg_5d > 3:
        short = ("强势持有", "red")
    elif chg_5d > 0:
        short = ("逢低关注", "gold")
    elif chg_5d > -5:
        short = ("观望", "gold")
    elif chg_5d > -10:
        short = ("减仓观察", "green")
    else:
        short = ("建议减仓", "green")

    # 中期评级逻辑 (6-14天)
    if chg_20d > 5:
        mid = ("看多", "red")
    elif chg_20d > -10:
        mid = ("逢低布局", "gold")
    elif chg_20d > -25:
        mid = ("观望", "gold")
    else:
        mid = ("等待右侧", "green")

    return {"short": short, "mid": mid}


def generate_html(stocks_data, output_dir):
    """生成完整的 HTML 报告"""
    today = datetime.now(CST)
    date_str = today.strftime("%Y年%m月%d日")
    weekday = ["周一","周二","周三","周四","周五","周六","周日"][today.weekday()]
    datetime_str = today.strftime("%Y-%m-%d %H:%M")
    filename = f"report_{today.strftime('%Y%m%d')}.html"
    
    # 构建股票表格行
    stock_rows = []
    for stock in STOCK_POOL:
        code = stock["code"]
        row = stocks_data.get(code, {})
        if not row:
            continue
        
        analysis = analyze_stock(row, stock["name"], stock["sector"])
        short_rating, short_color = analysis["short"]
        mid_rating, mid_color = analysis["mid"]
        
        stock_rows.append(f"""
        <tr>
            <td><strong>{stock['name']}</strong><br><span style="font-size:0.75rem;color:#a0a0b8">{code} {stock['sector']}</span></td>
            <td>{row.get('price', '-')}</td>
            <td class="{color_change(row.get('change_percent', '0'))}">{row.get('change_percent', '-')}%</td>
            <td class="{color_change(row.get('chg_5d', '0'))}">{row.get('chg_5d', '-')}%</td>
            <td class="{color_change(row.get('chg_20d', '0'))}">{row.get('chg_20d', '-')}%</td>
            <td class="{color_change(row.get('chg_60d', '0'))}">{row.get('chg_60d', '-')}%</td>
            <td class="{color_change(row.get('chg_ytd', '0'))}">{row.get('chg_ytd', '-')}%</td>
            <td>{row.get('pe_ratio', '-')}</td>
            <td>{make_tag(short_rating, short_color)}</td>
            <td>{make_tag(mid_rating, mid_color)}</td>
        </tr>""")

    # 统计
    up_count = sum(1 for r in stocks_data.values() if float(r.get('change_percent', '0').replace('%','') or '0') > 0)
    down_count = sum(1 for r in stocks_data.values() if float(r.get('change_percent', '0').replace('%','') or '0') < 0)
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日股市推送 — {date_str}（{weekday}）</title>
<style>
  :root {{ --bg: #1a1a2e; --card: #16213e; --accent: #e94560; --red: #ff4757; --green: #2ed573; --text: #e0e0e0; --sub: #a0a0b8; --border: #2a2a4a; --gold: #ffa502; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); line-height: 1.7; padding: 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  .header {{ text-align: center; padding: 30px 0; border-bottom: 2px solid var(--border); margin-bottom: 24px; }}
  .header h1 {{ font-size: 1.6rem; margin-bottom: 6px; }}
  .header .date {{ color: var(--sub); font-size: 0.9rem; }}
  .section {{ margin-bottom: 28px; }}
  .section-title {{ font-size: 1.15rem; font-weight: 700; padding: 6px 14px; border-left: 4px solid var(--accent); margin-bottom: 14px; }}
  .card {{ background: var(--card); border-radius: 10px; padding: 18px; margin-bottom: 14px; border: 1px solid var(--border); }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 14px; }}
  .stat {{ background: var(--card); padding: 12px; border-radius: 8px; text-align: center; }}
  .stat .label {{ font-size: 0.75rem; color: var(--sub); }}
  .stat .value {{ font-size: 1.2rem; font-weight: 700; }}
  .up {{ color: var(--red) !important; }}
  .down {{ color: var(--green) !important; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  th {{ background: var(--border); padding: 8px 6px; text-align: left; font-weight: 600; color: var(--gold); white-space: nowrap; }}
  td {{ padding: 7px 6px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  tr:hover {{ background: rgba(233,69,96,0.05); }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }}
  .tag-red {{ background: rgba(255,71,87,0.2); color: var(--red); }}
  .tag-green {{ background: rgba(46,213,115,0.2); color: var(--green); }}
  .tag-gold {{ background: rgba(255,165,2,0.2); color: var(--gold); }}
  .disclaimer {{ background: rgba(233,69,96,0.06); border: 1px solid rgba(233,69,96,0.25); border-radius: 8px; padding: 14px; text-align: center; font-size: 0.78rem; color: var(--sub); margin-top: 20px; }}
  .summary-box {{ background: linear-gradient(135deg, rgba(233,69,96,0.08), rgba(55,66,250,0.08)); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }}
  .summary-box h3 {{ color: var(--gold); margin-bottom: 10px; }}
  .auto-badge {{ display: inline-block; background: rgba(46,213,115,0.15); color: var(--green); padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; margin-left: 8px; }}
  @media (max-width: 768px) {{ body {{ padding: 10px; }} table {{ font-size: 0.72rem; }} }}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>每日股市新闻与股票推送 <span class="auto-badge">自动生成</span></h1>
  <div class="date">{date_str}（{weekday}）| 生成时间 {datetime_str} | 芯片·AI链·CPO·PDC</div>
</div>

<div class="section">
  <div class="section-title">股票池行情总览</div>
  <div class="stats">
    <div class="stat"><div class="label">股票池数量</div><div class="value" style="color:var(--gold)">{len(STOCK_POOL)}只</div></div>
    <div class="stat"><div class="label">今日上涨</div><div class="value up">{up_count}只</div></div>
    <div class="stat"><div class="label">今日下跌</div><div class="value down">{down_count}只</div></div>
    <div class="stat"><div class="label">数据时间</div><div class="value" style="color:var(--sub);font-size:0.9rem">{datetime_str}</div></div>
  </div>

  <div style="overflow-x:auto;">
  <table>
    <thead>
      <tr><th>股票</th><th>现价</th><th>今日</th><th>5日</th><th>20日</th><th>60日</th><th>YTD</th><th>PE</th><th>短期</th><th>中期</th></tr>
    </thead>
    <tbody>
      {''.join(stock_rows)}
    </tbody>
  </table>
  </div>
</div>

<div class="section">
  <div class="section-title">核心关注</div>
  <div class="summary-box">
    <h3>长鑫科技 (688825) — 7月27日科创板上市</h3>
    <p>发行价 8.66 元，募资 295 亿元。利好设备链（北方华创、中微公司），短期利空存储设计（兆易创新、江波龙）。</p>
    <h3 style="margin-top:12px;">操作思路</h3>
    <p><strong>短期（3-5天）：</strong>关注工业富联（低估值+抗跌）、澜起科技（回购+强势）、北方华创/中微公司（长鑫催化）。</p>
    <p><strong>中期（6-14天）：</strong>设备链核心持仓，存储设计等待长鑫上市后重新评估。</p>
    <p><strong>需警惕：</strong>香农芯创、江波龙 20日跌幅超40%，趋势已破坏，逢反弹减仓。</p>
  </div>
</div>

<div class="disclaimer">
  <strong>免责声明</strong><br>
  本报告由自动化脚本生成，数据来源：腾讯自选股公开行情接口。仅供参考，不构成投资建议。股市有风险，投资需谨慎。<br>
  定时执行：每日 16:00（北京时间）| GitHub Actions 自动运行
</div>

</div>
</body>
</html>"""

    # 写入报告
    report_path = os.path.join(output_dir, filename)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    # 同时更新 index.html（指向最新报告）
    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0;url={filename}">
<title>每日股市推送</title>
</head>
<body>
<p>正在跳转到最新报告... <a href="{filename}">点击这里</a></p>
</body>
</html>""")
    
    return filename, report_path


def main():
    parser = argparse.ArgumentParser(description="每日股市推送报告生成器")
    parser.add_argument("--output", "-o", default=None, help="输出目录")
    parser.add_argument("--no-fetch", action="store_true", help="跳过数据获取（调试用）")
    args = parser.parse_args()
    
    output_dir = args.output or os.path.dirname(__file__)
    os.makedirs(output_dir, exist_ok=True)
    
    # 获取行情数据
    if not args.no_fetch:
        node_cmd = get_node_path()
        print(f"使用 Node.js: {node_cmd}")
        print("正在获取股票数据...")
        
        raw = fetch_stock_data(node_cmd)
        if not raw:
            print("获取数据失败!", file=sys.stderr)
            sys.exit(1)
        
        stocks_data = parse_quote_table(raw)
        print(f"成功获取 {len(stocks_data)} 只股票数据")
        
        # 缓存数据供调试
        cache_path = os.path.join(output_dir, ".cache.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(stocks_data, f, ensure_ascii=False)
    else:
        cache_path = os.path.join(output_dir, ".cache.json")
        with open(cache_path, "r", encoding="utf-8") as f:
            stocks_data = json.load(f)
        print(f"使用缓存数据: {len(stocks_data)} 只股票")
    
    # 生成报告
    filename, report_path = generate_html(stocks_data, output_dir)
    print(f"报告已生成: {report_path}")
    print(f"文件名: {filename}")


if __name__ == "__main__":
    main()
