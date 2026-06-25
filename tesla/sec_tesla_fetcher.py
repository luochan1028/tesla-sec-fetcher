#!/usr/bin/env python3
"""
Multi-Company SEC Financial Reports Analyzer
多公司财报分析 + 股票投资角度利好/利空判断 + 新财报检测
"""

import requests
import os
import smtplib
import time as _time
import json
from email.mime.text import MIMEText
from datetime import datetime, timedelta, date

OUTPUT_DIR = "sec_filings"
STATE_FILE = os.path.join(OUTPUT_DIR, "last_state.json")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.126.com")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
RECIPIENT = os.getenv("RECIPIENT", "luochan1028@126.com")

# 环境变量：强制发送邮件（即使没有新财报）
FORCE_SEND = os.getenv("FORCE_SEND", "false").lower() == "true"

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
    "SalesRevenueNet", "Revenue", "TotalRevenuesAndOtherIncome"
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


def get_latest_filing_date(cik):
    """获取公司最近一次财报提交日期"""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {"User-Agent": "Fetcher/1.0 (contact@example.com)"}
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code != 200: return None, None
    
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    
    latest_10k = None
    latest_10q = None
    
    for idx, form in enumerate(recent.get("form", [])):
        if form == "10-K" and latest_10k is None:
            latest_10k = recent["filingDate"][idx]
        elif form == "10-Q" and latest_10q is None:
            latest_10q = recent["filingDate"][idx]
        elif form == "20-F" and latest_10k is None:
            latest_10k = recent["filingDate"][idx]
        
        if latest_10k and latest_10q:
            break
    
    latest = max(filter(None, [latest_10k, latest_10q])) if (latest_10k or latest_10q) else None
    return latest, {"10-K": latest_10k, "10-Q": latest_10q}


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
    facts = xbrl_data.get("facts", {})
    all_forms = ["10-K", "10-Q", "20-F"]
    date_info = {}
    
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
    
    valid_dates = {d: info for d, info in date_info.items() if "revenue" in info["metrics"]}
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
    current_form = date_info[current_date]["form"]
    try:
        curr = date.fromisoformat(current_date)
    except:
        return None
    
    same_form_dates = [d for d in valid_dates if date_info[d]["form"] == current_form]
    
    if current_form in ["10-K", "20-F"]:
        for d in same_form_dates:
            try:
                dd = date.fromisoformat(d)
                delta_days = (curr - dd).days
                if 350 <= delta_days <= 390:
                    return d
            except: continue
    
    if current_form == "10-Q":
        for d in same_form_dates:
            try:
                dd = date.fromisoformat(d)
                delta_days = (curr - dd).days
                if 350 <= delta_days <= 390:
                    return d
            except: continue
        
        for d in same_form_dates:
            try:
                dd = date.fromisoformat(d)
                delta_days = (curr - dd).days
                if 80 <= delta_days <= 120:
                    return d
            except: continue
    
    if len(same_form_dates) > 1:
        for d in same_form_dates:
            if d != current_date:
                return d
    
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


def analyze_investment_signal(c, p):
    bullish = []
    bearish = []
    
    if c.get("revenue") and p.get("revenue"):
        rc = pct_change(c["revenue"], p["revenue"])
        if rc is not None:
            if rc > 10:
                bullish.append(f"营收大幅增长 {rc:.1f}%")
            elif rc > 0:
                bullish.append(f"营收稳健增长 {rc:.1f}%")
            elif rc < -10:
                bearish.append(f"营收大幅下滑 {abs(rc):.1f}%")
            elif rc < 0:
                bearish.append(f"营收小幅下降 {abs(rc):.1f}%")
    
    if c.get("net_income") and p.get("net_income"):
        ni = pct_change(c["net_income"], p["net_income"])
        if ni is not None:
            if ni > 20:
                bullish.append(f"净利润大幅增长 {ni:.1f}%")
            elif ni > 0:
                bullish.append(f"净利润增长 {ni:.1f}%")
            elif ni < -20:
                bearish.append(f"净利润大幅下降 {abs(ni):.1f}%")
            elif ni < 0:
                bearish.append(f"净利润下降 {abs(ni):.1f}%")
    
    if p.get("net_income") and c.get("net_income"):
        if p["net_income"] < 0 and c["net_income"] >= 0:
            bullish.append("净利润扭亏为盈")
        elif p["net_income"] >= 0 and c["net_income"] < 0:
            bearish.append("净利润由盈转亏")
    
    if c.get("gross_margin") and p.get("gross_margin"):
        gm_change = c["gross_margin"] - p["gross_margin"]
        if gm_change > 2:
            bullish.append(f"毛利率显著提升 {gm_change:.1f}pp")
        elif gm_change > 0:
            bullish.append(f"毛利率改善 {gm_change:.1f}pp")
        elif gm_change < -2:
            bearish.append(f"毛利率大幅下降 {abs(gm_change):.1f}pp")
        elif gm_change < 0:
            bearish.append(f"毛利率下降 {abs(gm_change):.1f}pp")
    
    if c.get("gross_margin"):
        if c["gross_margin"] > 60:
            bullish.append(f"高毛利率 {c['gross_margin']:.0f}%")
        elif c["gross_margin"] < 20:
            bearish.append(f"低毛利率 {c['gross_margin']:.0f}%")
    
    if c.get("cash"):
        if c["cash"] > 10_000_000_000:
            bullish.append("现金充裕")
        elif c["cash"] < 1_000_000_000:
            bearish.append("现金紧张")
    
    if c.get("eps") and p.get("eps"):
        eps_change = pct_change(c["eps"], p["eps"])
        if eps_change is not None and eps_change > 10:
            bullish.append(f"EPS增长 {eps_change:.1f}%")
        elif eps_change is not None and eps_change < -10:
            bearish.append(f"EPS下降 {abs(eps_change):.1f}%")
    
    if c.get("rd_expense") and p.get("rd_expense"):
        rd_change = pct_change(c["rd_expense"], p["rd_expense"])
        if rd_change is not None:
            if rd_change > 15:
                bullish.append(f"研发投入大幅增加 {rd_change:.1f}%")
            elif rd_change < -15:
                bearish.append(f"研发投入大幅削减 {abs(rd_change):.1f}%")
    
    return bullish, bearish


def get_investment_summary(bullish, bearish):
    if len(bullish) >= 3 and len(bearish) <= 1:
        return "🟢 强烈利好", "多项关键指标向好，营收、利润、毛利率同步改善"
    elif len(bullish) >= 2 and len(bearish) == 0:
        return "🟢 利好", "核心指标表现优异，建议关注"
    elif len(bullish) > len(bearish):
        return "🟡 偏利好", "整体向好，但存在部分风险因素"
    elif len(bearish) >= 3 and len(bullish) <= 1:
        return "🔴 强烈利空", "多项关键指标恶化，营收、利润、毛利率同步下降"
    elif len(bearish) >= 2 and len(bullish) == 0:
        return "🔴 利空", "核心指标表现疲软，需谨慎"
    elif len(bearish) > len(bullish):
        return "🟡 偏利空", "整体承压，但部分指标仍有亮点"
    else:
        return "⚪ 中性", "指标分化，无明确趋势信号"


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
        "current": current, "previous": previous,
        "report_form": current_form
    }


def load_state():
    """加载上次运行状态"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_state(state):
    """保存运行状态"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_new_filings():
    """检查是否有新的财报提交"""
    last_state = load_state()
    current_state = {}
    new_filings = []
    
    print("\n" + "="*50)
    print("🔍 检查新财报...")
    print("="*50)
    
    for name, cik in COMPANIES:
        latest_date, details = get_latest_filing_date(cik)
        current_state[cik] = {
            "name": name,
            "latest_date": latest_date,
            "details": details
        }
        
        last_date = last_state.get(cik, {}).get("latest_date")
        if latest_date and (last_date is None or latest_date > last_date):
            print(f"  🆕 {name}: 新财报 {latest_date} (上次: {last_date})")
            new_filings.append({
                "name": name, "cik": cik,
                "new_date": latest_date,
                "old_date": last_date
            })
        else:
            print(f"  ✓ {name}: 无更新 ({latest_date})")
        
        _time.sleep(0.2)
    
    # 保存当前状态
    save_state(current_state)
    
    return new_filings, current_state


def build_report(results, new_filings=None):
    if new_filings is None:
        new_filings = []
    
    new_company_names = {nf["name"] for nf in new_filings}
    
    lines = []
    lines.append("=" * 70)
    
    if new_filings:
        lines.append("  🎉 发现新财报！美股科技巨头财务报告")
        lines.append(f"  🆕 新财报公司: {', '.join(nf['name'] for nf in new_filings)}")
    else:
        lines.append("        美股科技巨头财务报告 + 股票投资分析")
    
    lines.append(f"        生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)
    lines.append("")
    
    # 新财报摘要
    if new_filings:
        lines.append("-" * 70)
        lines.append("🆕 【新财报发布】")
        lines.append("-" * 70)
        for nf in new_filings:
            lines.append(f"  • {nf['name']}: {nf['new_date']}")
        lines.append("")
    
    # 投资信号速览
    lines.append("-" * 70)
    lines.append("【投资信号速览】")
    lines.append("-" * 70)
    lines.append(f"{'公司':<18}{'信号':<12}{'营收变化':<12}{'净利润变化':<12}{'毛利率':<10}")
    lines.append("-" * 70)
    
    for r in results:
        if r is None: continue
        short_name = r["name"].split(" ")[0][:16]
        is_new = r["name"] in new_company_names
        prefix = "🆕 " if is_new else ""
        
        bullish, bearish = analyze_investment_signal(r["current"], r["previous"])
        signal, _ = get_investment_summary(bullish, bearish)
        
        rev_change = pct_change(r["current"].get("revenue"), r["previous"].get("revenue"))
        rev_str = f"↑{rev_change:.0f}%" if rev_change and rev_change > 0 else (f"↓{abs(rev_change):.0f}%" if rev_change and rev_change < 0 else "N/A")
        
        ni_change = pct_change(r["current"].get("net_income"), r["previous"].get("net_income"))
        ni_str = f"↑{ni_change:.0f}%" if ni_change and ni_change > 0 else (f"↓{abs(ni_change):.0f}%" if ni_change and ni_change < 0 else "N/A")
        
        gm = f"{r['current']['gross_margin']:.0f}%" if r["current"].get("gross_margin") else "N/A"
        
        lines.append(f"{prefix}{short_name:<16}{signal:<12}{rev_str:<12}{ni_str:<12}{gm:<10}")
    
    lines.append("")
    
    # 先展示新财报公司
    new_results = [r for r in results if r and r["name"] in new_company_names]
    other_results = [r for r in results if r and r["name"] not in new_company_names]
    
    if new_results:
        lines.append("=" * 70)
        lines.append("🆕 新财报详细分析")
        lines.append("=" * 70)
        lines.append("")
        
        for r in new_results:
            lines += build_company_section(r, True)
    
    # 其他公司
    if other_results:
        lines.append("=" * 70)
        lines.append("其他公司概览")
        lines.append("=" * 70)
        lines.append("")
        
        for r in other_results:
            lines += build_company_section(r, False)
    
    # 整体市场分析
    lines.append("=" * 70)
    lines.append("📊 【整体市场分析】")
    lines.append("=" * 70)
    
    bull_count = 0; bear_count = 0; neutral_count = 0
    
    for r in results:
        if r is None: continue
        bullish, bearish = analyze_investment_signal(r["current"], r["previous"])
        signal, _ = get_investment_summary(bullish, bearish)
        
        if "强烈利好" in signal or "利好" in signal:
            bull_count += 1
        elif "强烈利空" in signal or "利空" in signal:
            bear_count += 1
        else:
            neutral_count += 1
    
    lines.append(f"")
    lines.append(f"  📈 利好信号: {bull_count} 家")
    lines.append(f"  📉 利空信号: {bear_count} 家")
    lines.append(f"  ⚖️ 中性信号: {neutral_count} 家")
    lines.append(f"  🆕 新财报: {len(new_filings)} 家")
    lines.append(f"")
    
    if bull_count > bear_count * 2:
        lines.append("  👉 整体市场情绪偏乐观，多数科技股财报表现良好")
    elif bear_count > bull_count * 2:
        lines.append("  👉 整体市场情绪偏悲观，科技股面临压力")
    else:
        lines.append("  👉 市场分化明显，建议关注个股基本面")
    
    lines.append(f"")
    lines.append("⚠️ 【风险提示】")
    lines.append("  • 本报告基于SEC公开财报数据，仅供参考")
    lines.append("  • 投资有风险，入市需谨慎")
    lines.append("  • 建议结合其他因素综合分析后再做决策")
    lines.append(f"")
    lines.append("=" * 70)
    lines.append("数据来源: SEC EDGAR | 报告类型: 10-K/10-Q/20-F")
    lines.append("=" * 70)
    return "\n".join(lines)


def build_company_section(r, is_new):
    lines = []
    lines.append("-" * 70)
    
    prefix = "🆕 " if is_new else ""
    lines.append(f"{prefix}【{r['name']}】报告期: {r['current_date']} ({r['form']})")
    if r.get("previous_date"):
        lines.append(f"对比期: {r['previous_date']}")
    lines.append("-" * 70)
    lines.append("")
    
    c = r["current"]; p = r["previous"]
    
    lines.append("📈 【核心财务指标】")
    lines.append("-" * 40)
    
    items = [
        ("营业收入", "revenue", True),
        ("毛利润", "gross_profit", True),
        ("净利润", "net_income", True),
        ("毛利率(%)", "gross_margin", False),
        ("研发费用", "rd_expense", True),
        ("现金及等价物", "cash", True),
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
    lines.append("💡 【股票投资分析】")
    lines.append("-" * 40)
    
    bullish, bearish = analyze_investment_signal(c, p)
    signal, signal_desc = get_investment_summary(bullish, bearish)
    
    lines.append(f"  📊 综合信号: {signal}")
    lines.append(f"  💭 解读: {signal_desc}")
    lines.append("")
    
    if bullish:
        lines.append("  🟢 利好因素:")
        for item in bullish[:5]:
            lines.append(f"    • {item}")
    
    if bearish:
        lines.append("")
        lines.append("  🔴 利空因素:")
        for item in bearish[:5]:
            lines.append(f"    • {item}")
    
    summary = []
    if c.get("revenue"): summary.append(f"营收{fmt_num(c['revenue'])}")
    if c.get("gross_margin"): summary.append(f"毛利率{c['gross_margin']:.0f}%")
    if c.get("net_income"):
        summary.append(f"{'净利润' if c['net_income'] > 0 else '净亏损'}{fmt_num(abs(c['net_income']))}")
    
    if summary:
        lines.append(f"\n  👉 {' | '.join(summary)}")
    lines.append("")
    
    return lines


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
    print(f"[{datetime.now().isoformat()}] 开始检查 {len(COMPANIES)} 家公司财报...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 检查新财报
    new_filings, _ = check_new_filings()
    
    if not new_filings and not FORCE_SEND:
        print(f"\nℹ️ 没有新财报，跳过发送邮件")
        print(f"   如需强制发送，请设置 FORCE_SEND=true")
        return
    
    if new_filings:
        print(f"\n✅ 发现 {len(new_filings)} 家公司新财报！")
    else:
        print(f"\nℹ️ 强制发送模式 (FORCE_SEND=true)")
    
    # 获取所有公司的详细分析
    results = []
    for name, cik in COMPANIES:
        try:
            results.append(analyze_company(name, cik))
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            results.append(None)
        _time.sleep(0.2)
    
    report = build_report([r for r in results if r is not None], new_filings)
    print("\n" + report + "\n")
    
    report_file = os.path.join(OUTPUT_DIR, f"report_{datetime.now().strftime('%Y%m%d')}.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    if new_filings:
        new_names = ",".join(nf["name"].split(" ")[0] for nf in new_filings[:3])
        subject = f"🆕【新财报】{new_names}等{len(new_filings)}家公司发布新财报 - {datetime.now().strftime('%Y-%m-%d')}"
    else:
        subject = f"【美股财报报告】{datetime.now().strftime('%Y-%m-%d')} 科技巨头财务+投资分析"
    
    print(f"发送邮件至 {RECIPIENT}...")
    success, error = send_email(subject, report, RECIPIENT)
    if success: print("✅ 报告已发送")
    else: print(f"❌ 邮件发送失败: {error}")


if __name__ == "__main__":
    main()
