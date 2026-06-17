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
    ("Tesla 特斯拉", "0001318605"),
    ("NVIDIA 英伟达", "0001045810"),
    ("Microsoft 微软", "0000789019"),
    ("Apple 苹果", "0000320193"),
    ("Micron 美光", "0000723125"),
    ("Broadcom 博通", "0001730168"),
    ("AMD 超威半导体", "0000002488"),
    ("Intel 英特尔", "0000050863"),
    ("Meta Platforms", "0001326801"),
    ("Alphabet 谷歌", "0001652044"),
    ("Amazon 亚马逊", "0001018724"),
    ("TSMC 台积电", "0001158449"),
]

REVENUE_CONCEPTS = [
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet", "Revenue", "TotalRevenuesAndOtherIncome",
    "RevenueFromContractWithCustomerIncludingAssessedTax"
]
NET_INCOME_CONCEPTS = [
    "NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholders", "ProfitLoss", "NetIncome"
]
GROSS_PROFIT_CONCEPTS = ["GrossProfit", "GrossMargin"]
RD_CONCEPTS = ["ResearchAndDevelopmentExpense", "ResearchDevelopmentAndRelatedExpense"]
CASH_CONCEPTS = ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents", "Cash"]
ASSETS_CONCEPTS = ["Assets"]
EQUITY_CONCEPTS = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
EPS_CONCEPTS = ["EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"]


def get_xbrl_data(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    headers = {"User-Agent": "Fetcher/1.0 (contact@example.com)"}
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code != 200: return None
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


def find_report_dates_with_metrics(xbrl_data):
    """返回按日期分组的指标数据: {date: {form, revenue, net_income, gross_profit, ...}}"""
    facts = xbrl_data.get("facts", {})
    all_forms = ["10-K", "10-Q", "20-F"]
    
    # 按日期收集指标
    date_info = {}
    
    # 只扫描核心指标来确定报告期
    core_concepts = {
        "revenue": REVENUE_CONCEPTS,
        "net_income": NET_INCOME_CONCEPTS,
        "gross_profit": GROSS_PROFIT_CONCEPTS,
    }
    
    for metric_name, concept_list in core_concepts.items():
        for ns in ["us-gaap", "ifrs-full"]:
            namespace = facts.get(ns, {})
            if not namespace: continue
            for concept in concept_list:
                if concept not in namespace: continue
                units = namespace[concept].get("units", {})
                for unit_key, entries in units.items():
                    for entry in entries:
                        form = entry.get("form")
                        end = entry.get("end")
                        val = entry.get("val")
                        if form in all_forms and end and val and val != 0:
                            if end not in date_info:
                                date_info[end] = {"form": form, "metrics": {}}
                            date_info[end]["metrics"][metric_name] = float(val)
    
    # 只保留有营收的日期
    valid_dates = {d: info for d, info in date_info.items() if "revenue" in info["metrics"]}
    
    # 按日期排序
    sorted_dates = sorted(valid_dates.keys(), reverse=True)
    
    return sorted_dates, valid_dates


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


def find_matching_comparison_date(xbrl_data, current_date, valid_dates, date_info):
    """找同类型的上一期报告日。10-K/20-F对上一年，10-Q对上一季或上年同季"""
    current_form = date_info[current_date]["form"]
    
    # 计算季度时长
    from datetime import date
    try:
        curr = date.fromisoformat(current_date)
    except:
        return None
    
    # 找最合适的对比日期
    # 10-K/20-F → 找去年同期
    if current_form in ["10-K", "20-F"]:
        # 找一年前的
        for d in valid_dates:
            try:
                dd = date.fromisoformat(d)
                if (curr - dd).days in range(350, 390) and date_info[d]["form"] in ["10-K", "20-F"]:
                    return d
            except: continue
    
    # 10-Q → 找上季度或上年同季
    for target_days in [80, 100, 110, 350, 365, 380]:
        for d in valid_dates:
            try:
                dd = date.fromisoformat(d)
                delta = abs((curr - dd).days - target_days)
                if delta < 15 and d != current_date:
                    return d
            except: continue
    
    # 没有合适的，就用最近的第二个日期
    if len(valid_dates) > 1 and valid_dates[1] != current_date:
        return valid_dates[1]
    
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


def analyze_company(name, cik):
    print(f"\n{'='*45}")
    print(f"📊 {name} (CIK {cik})")
    print(f"{'='*45}")
    
    xbrl = get_xbrl_data(cik)
    if xbrl is None:
        print(f"  ❌ 无法获取数据"); return None
    
    valid_dates, date_info = find_report_dates_with_metrics(xbrl)
    if not valid_dates:
        print(f"  ⚠️ 没有找到报告日期"); return None
    
    current_date = valid_dates[0]
    current_form = date_info[current_date]["form"]
    forms_for_current = [current_form, "10-Q", "10-K", "20-F"]
    
    print(f"  当前期: {current_date} ({current_form})")
    
    previous_date = find_matching_comparison_date(xbrl, current_date, valid_dates, date_info)
    if previous_date:
        print(f"  对比期: {previous_date}")
    
    current = get_all_metrics(xbrl, current_date, forms_for_current)
    previous = get_all_metrics(xbrl, previous_date, forms_for_current) if previous_date else {}
    
    useful = sum(1 for v in current.values() if v is not None)
    print(f"  获取指标数: {useful}/9")
    
    return {
        "name": name, "form": "年报" if current_form in ["10-K", "20-F"] else "季报",
        "current_date": current_date, "previous_date": previous_date,
        "current": current, "previous": previous
    }


def build_report(results):
    lines = []
    lines.append("=" * 65)
    lines.append("           美股科技巨头财务报告")
    lines.append(f"           生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 65)
    lines.append("")
    
    # 总览表
    lines.append("-" * 65)
    lines.append("【核心指标总览】")
    lines.append("-" * 65)
    lines.append(f"{'公司':<18}{'营收':<14}{'净利润':<14}{'毛利率':<10}{'EPS':<8}")
    lines.append("-" * 65)
    
    for r in results:
        if r is None: continue
        short_name = r["name"].split(" ")[0][:16]
        rev = fmt_num(r["current"].get("revenue"))
        ni = fmt_num(r["current"].get("net_income"))
        gm = f"{r['current']['gross_margin']:.0f}%" if r["current"].get("gross_margin") else "N/A"
        eps = f"${r['current']['eps']:.2f}" if r["current"].get("eps") else "N/A"
        
        rev_change = pct_change(r["current"].get("revenue"), r["previous"].get("revenue"))
        arrow = ""
        if rev_change is not None:
            arrow = f"  ↑{abs(rev_change):.0f}%" if rev_change > 0 else (f"  ↓{abs(rev_change):.0f}%" if rev_change < 0 else "")
        
        lines.append(f"{short_name:<18}{rev:<14}{ni:<14}{gm:<10}{eps:<8}{arrow}")
    
    lines.append("")
    
    # 每家公司详细
    for r in results:
        if r is None: continue
        
        lines.append("-" * 65)
        lines.append(f"【{r['name']}】报告期: {r['current_date']} ({r['form']})")
        if r.get("previous_date"):
            lines.append(f"对比期: {r['previous_date']}")
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
            curr = c.get(key); prev = p.get(key) if p else None
            if curr is None: continue
            
            if key == "gross_margin": curr_str = f"{curr:.1f}%"
            elif key == "eps": curr_str = f"${curr:.2f}"
            else: curr_str = fmt_num(curr, is_currency)
            
            if prev is not None:
                change = pct_change(curr, prev)
                if change is not None:
                    arrow = "↑" if change > 0 else ("↓" if change < 0 else "→")
                    if key == "gross_margin":
                        lines.append(f"  {label}: {curr_str}  {arrow}{abs(curr - prev):.1f}pp")
                    else:
                        lines.append(f"  {label}: {curr_str}  {arrow}{abs(change):.1f}%")
                    continue
            lines.append(f"  {label}: {curr_str}")
        
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
    lines.append("数据来源: SEC EDGAR | 报告类型: 10-K/10-Q/20-F")
    lines.append("注: 部分对比期可能是不同的时间段，主要用于趋势参考")
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
    for name, cik in COMPANIES:
        try:
            results.append(analyze_company(name, cik))
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
