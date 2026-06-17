#!/usr/bin/env python3
"""
Tesla SEC Financial Reports Analyzer
使用SEC API直接提取财务数据，生成分析报告
"""

import requests
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta

CIK = "0001318605"
OUTPUT_DIR = "sec_filings"

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.126.com")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
RECIPIENT = os.getenv("RECIPIENT", "luochan1028@126.com")


def get_sec_xbrl_data():
    """从SEC获取Tesla的结构化财务数据(XBRL)"""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
    headers = {"User-Agent": "TeslaFetcher/1.0 (contact@example.com)"}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def find_recent_filing_info():
    """获取最近的财报提交信息"""
    url = f"https://data.sec.gov/submissions/CIK{CIK}.json"
    headers = {"User-Agent": "TeslaFetcher/1.0 (contact@example.com)"}
    response = requests.get(url, headers=headers, timeout=30)
    data = response.json()
    
    recent = data.get("filings", {}).get("recent", {})
    filings = []
    
    for idx, form in enumerate(recent.get("form", [])):
        if form in ["10-K", "10-Q"]:
            accession = recent["accessionNumber"][idx]
            filing_date = recent["filingDate"][idx]
            primary_doc = recent["primaryDocument"][idx]
            filings.append({
                "form": form, "date": filing_date,
                "accession": accession, "document": primary_doc,
                "url": f"https://www.sec.gov/Archives/edgar/data/{CIK}/{accession.replace('-', '')}/{primary_doc}"
            })
    
    seen = set(); unique = []
    for f in filings:
        key = (f["form"], f["date"])
        if key not in seen: seen.add(key); unique.append(f)
    return unique


def get_metric_value(xbrl_data, concept_names, period_end=None, is_qtr=True):
    """从XBRL数据提取指定指标的数值"""
    facts = xbrl_data.get("facts", {})
    
    for us_gaap_or_other in ["us-gaap", "ifrs-full", "srt"]:
        namespace = facts.get(us_gaap_or_other, {})
        
        for concept in concept_names:
            if concept in namespace:
                units = namespace[concept].get("units", {})
                
                # 优先用美元 (USD) 或纯数字
                unit_keys = ["USD", "shares", "pure"]
                for unit_key in unit_keys:
                    if unit_key in units:
                        entries = units[unit_key]
                        
                        # 找最近的年度/季度数据
                        if period_end:
                            for entry in entries:
                                if entry.get("end") == period_end and entry.get("form") in ["10-K", "10-Q"]:
                                    val = entry.get("val")
                                    if val is not None:
                                        return float(val)
                        
                        # 如果没有指定日期，返回最近的数据
                        filtered = []
                        for entry in entries:
                            if entry.get("form") in ["10-K", "10-Q"]:
                                filtered.append(entry)
                        
                        if filtered:
                            filtered.sort(key=lambda e: e.get("end", ""), reverse=True)
                            for entry in filtered[:20]:  # 检查最近20条
                                val = entry.get("val")
                                if val is not None and val != 0:
                                    return float(val)
    return None


def get_metric_for_period(xbrl_data, concept_names, end_date):
    """获取指定日期的指标值"""
    facts = xbrl_data.get("facts", {})
    
    for namespace_name in ["us-gaap", "ifrs-full"]:
        namespace = facts.get(namespace_name, {})
        for concept in concept_names:
            if concept in namespace:
                units = namespace[concept].get("units", {})
                unit_key = "USD" if namespace_name != "srt" else "pure"
                if unit_key not in units:
                    for k in units:
                        unit_key = k; break
                if unit_key in units:
                    for entry in units[unit_key]:
                        if entry.get("end") == end_date and entry.get("form") in ["10-K", "10-Q"]:
                            val = entry.get("val")
                            if val is not None and val != 0:
                                return float(val)
    return None


def get_all_metrics_for_date(xbrl_data, end_date):
    """获取指定日期的所有可用指标"""
    metrics = {}
    concepts_map = {
        "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", 
                    "SalesRevenueNet", "Revenue", "TotalRevenuesAndOtherIncome",
                    "RevenueFromContractWithCustomerIncludingAssessedTax",
                    "ContractWithCustomerRevenue"],
        "net_income": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholders", 
                       "ProfitLoss", "NetIncome"],
        "gross_profit": ["GrossProfit", "GrossMargin"],
        "gross_margin_percent": [],  # 手动计算
        "rd_expense": ["ResearchAndDevelopmentExpense", "ResearchDevelopmentAndRelatedExpense"],
        "operating_income": ["OperatingIncomeLoss"],
        "income_before_tax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndEquityMethodInvestments"],
        "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalentsPeriodIncreaseDecrease", 
                 "Cash", "CashAndCashEquivalents"],
        "total_assets": ["Assets"],
        "total_liabilities": ["Liabilities"],
        "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "eps_basic": ["EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted", 
                      "IncomeLossAvailableToCommonStockholdersBasic"],
        "eps_diluted": ["EarningsPerShareDiluted", "IncomeLossAvailableToCommonStockholdersDiluted"],
        "automotive_revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax"],  # 细分数据难找
        "energy_revenue": [],  # 细分数据难找
        "services_revenue": [],  # 细分数据难找
    }
    
    for metric, concept_names in concepts_map.items():
        if not concept_names: continue
        val = get_metric_for_period(xbrl_data, concept_names, end_date)
        if val is not None:
            metrics[metric] = val
    
    # 计算毛利率
    if "gross_profit" in metrics and "revenue" in metrics and metrics["revenue"] > 0:
        metrics["gross_margin"] = (metrics["gross_profit"] / metrics["revenue"]) * 100
    
    return metrics


def get_latest_10q_and_10k_dates(xbrl_data):
    """找出最近的10-Q和10-K报告期结束日期"""
    facts = xbrl_data.get("facts", {})
    
    # 从Revenue数据中找报告期
    dates_10q = []
    dates_10k = []
    
    for namespace_name in ["us-gaap", "ifrs-full"]:
        namespace = facts.get(namespace_name, {})
        for concept_name, concept_data in namespace.items():
            if any(keyword in concept_name.lower() for keyword in ["revenue", "netincome", "assets"]):
                for unit, entries in concept_data.get("units", {}).items():
                    for entry in entries:
                        form = entry.get("form", "")
                        end = entry.get("end", "")
                        if form == "10-Q" and end:
                            if end not in dates_10q: dates_10q.append(end)
                        elif form == "10-K" and end:
                            if end not in dates_10k: dates_10k.append(end)
    
    dates_10q.sort(reverse=True)
    dates_10k.sort(reverse=True)
    
    return dates_10q[:3], dates_10k[:3]


def format_number(num, is_currency=True):
    if num is None: return "N/A"
    if abs(num) >= 1_000_000_000:
        val = num / 1_000_000_000
        return f"${val:.2f}B" if is_currency else f"{val:.2f}B"
    if abs(num) >= 1_000_000:
        val = num / 1_000_000
        return f"${val:.2f}M" if is_currency else f"{val:.2f}M"
    return f"${num:.2f}" if is_currency else f"{num:.2f}"


def calculate_change(current, previous):
    if current is None or previous is None or previous == 0: return None
    return ((current - previous) / abs(previous)) * 100


def generate_report(current_filing, current_metrics, previous_filing, previous_metrics):
    form_name = "年报" if current_filing["form"] == "10-K" else "季报"
    report = []
    report.append("=" * 55)
    report.append("          Tesla 财务分析报告")
    report.append("=" * 55)
    report.append(f"报告期: {current_filing['date']} ({form_name})")
    if previous_filing:
        report.append(f"对比期: {previous_filing['date']} ({'年报' if previous_filing['form'] == '10-K' else '季报'})")
    report.append(f"原文链接: {current_filing['url']}")
    report.append("")
    report.append("-" * 55)
    report.append("【核心财务指标】")
    report.append("-" * 55)
    report.append("")
    
    display_items = [
        ("revenue", "营业收入", True),
        ("gross_profit", "毛利润", True),
        ("net_income", "净利润", True),
        ("gross_margin", "毛利率(%)", False),
        ("rd_expense", "研发费用", True),
        ("operating_income", "运营收入", True),
        ("cash", "现金及等价物", True),
        ("total_assets", "总资产", True),
        ("equity", "股东权益", True),
        ("eps_basic", "每股收益($)", False),
    ]
    
    for key, chinese_name, is_currency in display_items:
        curr = current_metrics.get(key)
        prev = previous_metrics.get(key) if previous_metrics else None
        
        if curr is not None:
            if key == "gross_margin":
                curr_str = f"{curr:.1f}%"
            elif key == "eps_basic":
                curr_str = f"${curr:.2f}"
            else:
                curr_str = format_number(curr, is_currency)
            
            if prev is not None:
                change = calculate_change(curr, prev)
                if change is not None:
                    arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                    report.append(f"  {chinese_name}: {curr_str}  {arrow}{abs(change):.1f}%")
                    continue
            report.append(f"  {chinese_name}: {curr_str}")
    
    report.append("")
    
    # 变化分析
    report.append("-" * 55)
    report.append("【关键变化分析】")
    report.append("-" * 55)
    report.append("")
    
    changes = []
    if previous_metrics:
        if 'revenue' in current_metrics and 'revenue' in previous_metrics:
            rev = calculate_change(current_metrics['revenue'], previous_metrics['revenue'])
            if rev is not None and abs(rev) > 0.5:
                direction = "增长" if rev > 0 else "下降"
                changes.append(f"  • 营业收入{direction} {abs(rev):.1f}%，至 {format_number(current_metrics['revenue'])}")
        
        if 'gross_profit' in current_metrics and 'gross_profit' in previous_metrics:
            gp = calculate_change(current_metrics['gross_profit'], previous_metrics['gross_profit'])
            if gp is not None and abs(gp) > 1:
                direction = "增长" if gp > 0 else "下降"
                changes.append(f"  • 毛利润{direction} {abs(gp):.1f}%，至 {format_number(current_metrics['gross_profit'])}")
        
        if 'net_income' in current_metrics and 'net_income' in previous_metrics:
            ni = calculate_change(current_metrics['net_income'], previous_metrics['net_income'])
            if ni is not None and abs(ni) > 1:
                direction = "增长" if ni > 0 else "下降"
                changes.append(f"  • 净利润{direction} {abs(ni):.1f}%，至 {format_number(current_metrics['net_income'])}")
        
        if 'gross_margin' in current_metrics and 'gross_margin' in previous_metrics:
            gm = current_metrics['gross_margin'] - previous_metrics['gross_margin']
            if abs(gm) > 0.3:
                direction = "上升" if gm > 0 else "下降"
                changes.append(f"  • 毛利率{direction} {abs(gm):.1f}个百分点，至 {current_metrics['gross_margin']:.1f}%")
        
        if 'cash' in current_metrics and 'cash' in previous_metrics:
            cash = calculate_change(current_metrics['cash'], previous_metrics['cash'])
            if cash is not None and abs(cash) > 5:
                direction = "增加" if cash > 0 else "减少"
                changes.append(f"  • 现金{direction} {abs(cash):.1f}%，当前 {format_number(current_metrics['cash'])}")
    
    if changes:
        for c in changes: report.append(c)
    else:
        report.append("  • 主要财务指标相对稳定")
    
    report.append("")
    
    # 盈利能力指标
    report.append("-" * 55)
    report.append("【总结】")
    report.append("-" * 55)
    report.append("")
    
    summary = []
    if 'revenue' in current_metrics:
        summary.append(f"营收 {format_number(current_metrics['revenue'])}")
    if 'gross_margin' in current_metrics:
        summary.append(f"毛利率 {current_metrics['gross_margin']:.0f}%")
    if 'net_income' in current_metrics:
        ni = current_metrics['net_income']
        summary.append(f"{'净利润' if ni > 0 else '净亏损'} {format_number(abs(ni))}")
    
    if summary:
        report.append("  " + " | ".join(summary))
    else:
        report.append("  数据有限，请查看原文链接")
    
    report.append("")
    report.append("=" * 55)
    report.append(f"报告生成: {datetime.now().strftime('%Y-%m-%d')} | 数据来源: SEC EDGAR")
    report.append("=" * 55)
    return "\n".join(report)


def send_email(subject, content, recipient):
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "未设置邮件账户 (SMTP_USER/SMTP_PASSWORD)"
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient
    
    configs = [(SMTP_SERVER, 25, "starttls"), (SMTP_SERVER, 587, "starttls"), (SMTP_SERVER, 465, "ssl")]
    for server_host, port, method in configs:
        try:
            if method == "ssl":
                server = smtplib.SMTP_SSL(server_host, port, timeout=30)
            else:
                server = smtplib.SMTP(server_host, port, timeout=30)
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipient, msg.as_string())
            server.quit()
            return True, None
        except Exception as e:
            last_error = str(e)
    return False, last_error


def analyze_filings():
    print(f"[{datetime.now().isoformat()}] Tesla 财务分析...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    try:
        # 获取XBRL结构化数据
        print("从SEC API获取财务数据...")
        xbrl_data = get_sec_xbrl_data()
        
        # 获取最近的财报信息
        filings = find_recent_filing_info()
        print(f"找到 {len(filings)} 个财报记录")
        
        if not filings:
            print("没有找到财报"); return
        
        current_filing = filings[0]
        previous_filing = None
        
        # 找同类型的上一期
        for f in filings[1:]:
            if f["form"] == current_filing["form"]:
                previous_filing = f
                break
        
        print(f"当前: {current_filing['form']} {current_filing['date']}")
        if previous_filing: print(f"对比: {previous_filing['form']} {previous_filing['date']}")
        
        # 从XBRL数据提取报告日期和对应的指标
        dates_10q, dates_10k = get_latest_10q_and_10k_dates(xbrl_data)
        print(f"可用10-Q日期: {dates_10q[:3]}")
        print(f"可用10-K日期: {dates_10k[:3]}")
        
        # 用当前filing的日期来查找对应的指标
        # XBRL中的日期是报告期结束日期，需要映射
        # 使用最近的可用日期
        if current_filing["form"] == "10-Q":
            current_dates = dates_10q
        else:
            current_dates = dates_10k
        
        if not current_dates:
            print("警告: 没有找到报告日期")
            return
        
        current_date = current_dates[0]
        current_metrics = get_all_metrics_for_date(xbrl_data, current_date)
        
        previous_date = current_dates[1] if len(current_dates) > 1 else None
        previous_metrics = {}
        if previous_date:
            previous_metrics = get_all_metrics_for_date(xbrl_data, previous_date)
            if not previous_filing:
                previous_filing = {"form": current_filing["form"], "date": previous_date}
        
        print(f"当前期({current_date}): {current_metrics}")
        print(f"上期({previous_date}): {previous_metrics}")
        
        # 生成报告
        report = generate_report(
            {"form": current_filing["form"], "date": current_date, "url": current_filing["url"]},
            current_metrics,
            {"form": current_filing["form"], "date": previous_date} if previous_date else None,
            previous_metrics
        )
        print("\n" + report + "\n")
        
        # 保存
        report_file = os.path.join(OUTPUT_DIR, f"{current_filing['form']}_{current_date}_report.txt")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        
        # 发送邮件
        form_name = "年报" if current_filing["form"] == "10-K" else "季报"
        email_subject = f"【Tesla分析报告】{form_name} {current_date}"
        print(f"发送邮件至 {RECIPIENT}...")
        success, error = send_email(email_subject, report, RECIPIENT)
        if success: print("✅ 报告已发送")
        else: print(f"❌ 邮件发送失败: {error}")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    analyze_filings()
