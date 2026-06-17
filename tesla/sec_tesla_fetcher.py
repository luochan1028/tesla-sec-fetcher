#!/usr/bin/env python3
"""
Multi-Company SEC Financial Reports Analyzer
多公司财报分析：Tesla, NVIDIA, TSMC, Microsoft, Micron, Broadcom, Apple, AMD, Intel, Meta, Google, Amazon
"""

import requests
import os
import smtplib
import time as _time
from email.mime.text import MIMEText
from datetime import datetime, timedelta

OUTPUT_DIR = "sec_filings"

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.126.com")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
RECIPIENT = os.getenv("RECIPIENT", "luochan1028@126.com")

COMPANIES = [
    ("Tesla 特斯拉", "0001318605", ["10-K", "10-Q"]),
    ("NVIDIA 英伟达", "0001045810", ["10-K", "10-Q"]),
    ("Microsoft 微软", "0000789019", ["10-K", "10-Q"]),
    ("Apple 苹果", "0000320193", ["10-K", "10-Q"]),
    ("Micron 美光", "0000723125", ["10-K", "10-Q"]),
    ("Broadcom 博通", "0001730168", ["10-K", "10-Q"]),
    ("AMD 超威半导体", "0000002488", ["10-K", "10-Q"]),
    ("Intel 英特尔", "0000050863", ["10-K", "10-Q"]),
    ("Meta Platforms", "0001326801", ["10-K", "10-Q"]),
    ("Alphabet 谷歌", "0001652044", ["10-K", "10-Q"]),
    ("Amazon 亚马逊", "0001018724", ["10-K", "10-Q"]),
    ("TSMC 台积电", "0001158449", ["20-F"]),
]

REVENUE_CONCEPTS = [
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet", "Revenue", "TotalRevenuesAndOtherIncome",
    "RevenueFromContractWithCustomerIncludingAssessedTax", "ContractWithCustomerRevenue"
]
NET_INCOME_CONCEPTS = [
    "NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholders", "ProfitLoss", "NetIncome"
]
GROSS_PROFIT_CONCEPTS = ["GrossProfit", "GrossMargin"]
RD_CONCEPTS = ["ResearchAndDevelopmentExpense", "ResearchDevelopmentAndRelatedExpense"]
CASH_CONCEPTS = ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents", "Cash"]
ASSETS_CONCEPTS = ["Assets"]
EQUITY_CONCEPTS = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
EPS_CONCEPTS = ["EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted", "IncomeLossAvailableToCommonStockholdersBasic"]


def get_xbrl_data(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    headers = {"User-Agent": "Fetcher/1.0 (contact@example.com)"}
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code != 200:
        return None
    return r.json()


def get_metric_for_date(xbrl_data, concept_list, target_end_date, target_forms):
    facts = xbrl_data.get("facts", {})
    for ns in ["us-gaap", "ifrs-full", "srt"]:
        namespace = facts.get(ns, {})
        for concept in concept_list:
            if concept not in namespace: continue
            units = namespace[concept].get("units", {})
            for unit_key, entries in units.items():
                for entry in entries:
                    if entry.get("end") == target_end_date and entry.get("form") in target_forms:
                        val = entry.get("val")
                        if val is not None and val != 0:
                            return float(val)
    return None


def find_best_report_dates(xbrl_data, forms, top_n=5):
    """通过查找有营收数据的报告期来确定最佳日期"""
    facts = xbrl_data.get("facts", {})
    
    # 先尝试从revenue概念里找报告期
    candidate_dates = []
    for ns in ["us-gaap", "ifrs-full"]:
        namespace = facts.get(ns, {})
        if not namespace: continue
        for concept_name, concept_data in namespace.items():
            if "revenue" in concept_name.lower() or "income" in concept_name.lower() or "assets" in concept_name.lower():
                for unit_key, entries in concept_data.get("units", {}).items():
                    for entry in entries:
                        if entry.get("form") in forms and entry.get("end") and entry.get("val"):
                            candidate_dates.append((entry["end"], entry["form"], entry["val"]))
    
    # 按日期聚合，找有最高频率出现的日期
    date_counts = {}
    for d, form, val in candidate_dates:
        if d not in date_counts:
            date_counts[d] = 0
        date_counts[d] += 1
    
    # 按出现频率排序，取top
    sorted_dates = sorted(date_counts.keys(), key=lambda d: (-date_counts[d], d))
    return sorted_dates[:top_n]


def get_all_metrics(xbrl_data, target_end_date, forms):
    m = {}
    m["revenue"] = get_metric_for_date(xbrl_data, REVENUE_CONCEPTS, target_end_date, forms)
    m["net_income"] = get_metric_for_date(xbrl_data, NET_INCOME_CONCEPTS, target_end_date, forms)
    m["gross_profit"] = get_metric_for_date(xbrl_data, GROSS_PROFIT_CONCEPTS, target_end_date, forms)
    m["rd_expense"] = get_metric_for_date(xbrl_data, RD_CONCEPTS, target_end_date, forms)
    m["cash"] = get_metric_for_date(xbrl_data, CASH_CONCEPTS, target_end_date, forms)
    m["total_assets"] = get_metric_for_date(xbrl_data, ASSETS_CONCEPTS, target_end_date, forms)
    m["equity"] = get_metric_for_date(xbrl_data, EQUITY_CONCEPTS, target_end_date, forms)
    m["eps"] = get_metric_for_date(xbrl_data, EPS_CONCEPTS, target_end_date, forms)
    if m.get("gross_profit") and m.get("revenue") and m["revenue"] > 0:
        m["gross_margin"] = (m["gross_profit"] / m["revenue"]) * 100
    return m


def get_filing_url(cik, filing_date, forms):
    """获取最近财报的URL"""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {"User-Agent": "Fetcher/1.0 (contact@example.com)"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200: return None
        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        for idx, form in enumerate(recent.get("form", [])):
            if form in forms and recent["filingDate"][idx] >= filing_date[:7]:
                acc = recent["accessionNumber"][idx]
                doc = recent["primaryDocument"][idx]
                return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
    except:
        pass
    return None


def fmt_num(n, is_currency=True):
    if n is None: return "N/A"
    if abs(n) >= 1_000_000_000_000:
        return f"${n/1_000_000_000_000:.2f}T" if is_currency else f"{n/1_000_000_000_000:.2f}T"
    if abs(n) >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B" if is_currency else f"{n/1_000_000_000:.2f}B"
    if abs(n) >= 1_000_000:
        return f"${n/1_000_000:.2f}M" if is_currency else f"{n/1_000_000:.2f}M"
    return f"${n:.2f}" if is_currency else f"{n:.2f}"


def pct_change(curr, prev):
    if curr is None or prev is None or prev == 0: return None
    return ((curr - prev) / abs(prev)) * 100


def analyze_company(name, cik, forms):
    print(f"\n{'='*45}")
    print(f"📊 {name} (CIK {cik})")
    print(f"{'='*45}")
    
    xbrl = get_xbrl_data(cik)
    if xbrl is None:
        print(f"  ❌ 无法获取数据")
        return None
    
    dates = find_best_report_dates(xbrl, forms)
    if not dates:
        print(f"  ⚠️ 没有找到报告日期")
        return None
    
    current_date = dates[0]
    previous_date = dates[1] if len(dates) > 1 else None
    
    print(f"  当前期: {current_date}")
    if previous_date: print(f"  对比期: {previous_date}")
    
    current = get_all_metrics(xbrl, current_date, forms)
    
    # 获取当前期的filing URL
    filing_url = get_filing_url(cik, current_date, forms)
    
    previous = {}
    if previous_date:
        previous = get_all_metrics(xbrl, previous_date, forms)
    
    # 过滤掉只有很少数据的条目
    useful_count = sum(1 for v in current.values() if v is not None)
    print(f"  获取指标数: {useful_count}/9")
    
    if useful_count < 3:
        print(f"  ⚠️ 数据太少，尝试更多日期")
        for d in dates[2:]:
            m = get_all_metrics(xbrl, d, forms)
            c = sum(1 for v in m.values() if v is not None)
            if c >= useful_count and c >= 3:
                current = m
                current_date = d
                print(f"  → 使用 {d} (有{c}个指标)")
                break
    
    return {
        "name": name, "form": "年报" if "10-K" in forms else "季报/年报",
        "current_date": current_date, "previous_date": previous_date,
        "current": current, "previous": previous, "url": filing_url
    }


def build_report(results):
    lines = []
    lines.append("=" * 65)
    lines.append("          美股科技巨头财务报告")
    lines.append(f"          生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 65)
    lines.append("")
    
    # 表格总览
    lines.append("-" * 65)
    lines.append("【核心指标总览】")
    lines.append("-" * 65)
    lines.append(f"{'公司':<18}{'营收':<14}{'净利润':<14}{'毛利率':<10}{'EPS':<8}")
    lines.append("-" * 65)
    
    for r in results:
        if r is None: continue
        short_name = r["name"].split(" ")[0][:16]
        rev = fmt_num(r["current"].get("revenue"), True)
        ni = fmt_num(r["current"].get("net_income"), True)
        gm = f"{r['current']['gross_margin']:.0f}%" if r["current"].get("gross_margin") else "N/A"
        eps = f"${r['current']['eps']:.2f}" if r["current"].get("eps") else "N/A"
        
        rev_change = pct_change(r["current"].get("revenue"), r["previous"].get("revenue"))
        arrow = f"  ↑{abs(rev_change):.0f}%" if rev_change and rev_change > 0 else (f"  ↓{abs(rev_change):.0f}%" if rev_change and rev_change < 0 else "")
        
        lines.append(f"{short_name:<18}{rev:<14}{ni:<14}{gm:<10}{eps:<8}{arrow}")
    
    lines.append("")
    
    # 每家公司详细分析
    for idx, r in enumerate(results):
        if r is None: continue
        
        lines.append("-" * 65)
        lines.append(f"【{r['name']}】报告期: {r['current_date']} ({r['form']})")
        if r["url"]: lines.append(f"原文: {r['url']}")
        lines.append("-" * 65)
        lines.append("")
        
        c = r["current"]; p = r["previous"]
        
        items = [
            ("营业收入", "revenue", True),
            ("毛利润", "gross_profit", True),
            ("净利润", "net_income", True),
            ("毛利率(%)", "gross_margin", False),
            ("研发费用", "rd_expense", True),
            ("现金及等价物", "cash", True),
            ("总资产", "total_assets", True),
            ("股东权益", "equity", True),
            ("每股收益($)", "eps", False),
        ]
        
        for label, key, is_currency in items:
            curr = c.get(key)
            prev = p.get(key) if p else None
            
            if curr is None: continue
            
            if key == "gross_margin": curr_str = f"{curr:.1f}%"
            elif key == "eps": curr_str = f"${curr:.2f}"
            else: curr_str = fmt_num(curr, is_currency)
            
            if prev is not None:
                change = pct_change(curr, prev)
                if change is not None:
                    arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                    if key == "gross_margin":
                        lines.append(f"  {label}: {curr_str}  {arrow}{abs(curr - prev):.1f}pp")
                    else:
                        lines.append(f"  {label}: {curr_str}  {arrow}{abs(change):.1f}%")
                    continue
            lines.append(f"  {label}: {curr_str}")
        
        # 关键变化
        lines.append("")
        highlights = []
        if p and c.get("revenue") and p.get("revenue"):
            rc = pct_change(c["revenue"], p["revenue"])
            if rc is not None and abs(rc) > 0.5:
                direction = "增长" if rc > 0 else "下降"
                highlights.append(f"  • 营收{direction} {abs(rc):.1f}%，至 {fmt_num(c['revenue'])}")
        
        if p and c.get("net_income") and p.get("net_income"):
            nc = pct_change(c["net_income"], p["net_income"])
            if nc is not None and abs(nc) > 0.5:
                direction = "增长" if nc > 0 else "下降"
                highlights.append(f"  • 净利润{direction} {abs(nc):.1f}%，至 {fmt_num(c['net_income'])}")
        
        if p and c.get("gross_margin") and p.get("gross_margin"):
            gm = c["gross_margin"] - p["gross_margin"]
            if abs(gm) > 0.3:
                direction = "上升" if gm > 0 else "下降"
                highlights.append(f"  • 毛利率{direction} {abs(gm):.1f}个百分点，至 {c['gross_margin']:.1f}%")
        
        if highlights:
            for h in highlights: lines.append(h)
        else:
            lines.append("  • 主要指标相对稳定")
        
        summary = []
        if c.get("revenue"): summary.append(f"营收{fmt_num(c['revenue'])}")
        if c.get("gross_margin"): summary.append(f"毛利率{c['gross_margin']:.0f}%")
        if c.get("net_income"):
            summary.append(f"{'净利润' if c['net_income'] > 0 else '净亏损'}{fmt_num(abs(c['net_income']))}")
        
        if summary:
            lines.append(f"\n  👉 {' | '.join(summary)}")
        lines.append("")
    
    lines.append("=" * 65)
    lines.append("数据来源: SEC EDGAR (sec.gov) | 报告类型: 10-K/10-Q/20-F")
    lines.append("=" * 65)
    return "\n".join(lines)


def send_email(subject, content, recipient):
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "未设置邮件账户"
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient
    
    for host, port, method in [(SMTP_SERVER, 25, "starttls"), (SMTP_SERVER, 587, "starttls"), (SMTP_SERVER, 465, "ssl")]:
        try:
            if method == "ssl": server = smtplib.SMTP_SSL(host, port, timeout=30)
            else: server = smtplib.SMTP(host, port, timeout=30); server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipient, msg.as_string())
            server.quit()
            return True, None
        except Exception as e: last = str(e)
    return False, last


def main():
    print(f"[{datetime.now().isoformat()}] 开始抓取 {len(COMPANIES)} 家公司财报...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    results = []
    for name, cik, forms in COMPANIES:
        try:
            results.append(analyze_company(name, cik, forms))
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            results.append(None)
        _time.sleep(0.2)
    
    report = build_report([r for r in results if r is not None])
    print("\n" + report + "\n")
    
    report_file = os.path.join(OUTPUT_DIR, f"multi_company_{datetime.now().strftime('%Y%m%d')}.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    subject = f"【美股财报报告】{datetime.now().strftime('%Y-%m-%d')} 科技巨头财务"
    print(f"发送邮件至 {RECIPIENT}...")
    success, error = send_email(subject, report, RECIPIENT)
    if success: print("✅ 报告已发送")
    else: print(f"❌ 邮件发送失败: {error}")


if __name__ == "__main__":
    main()
