#!/usr/bin/env python3
"""
Tesla SEC Financial Reports Analyzer
分析特斯拉财报，与上期对比，生成结构化报告
"""

import requests
import os
import re
import smtplib
import html
import time
import random
import urllib.parse
from email.mime.text import MIMEText
from datetime import datetime, timedelta

CIK = "0001318605"
OUTPUT_DIR = "sec_filings"

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.126.com")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
RECIPIENT = os.getenv("RECIPIENT", "luochan1028@126.com")


def get_recent_filings(forms=None, days_back=730):
    if forms is None:
        forms = ["10-K", "10-Q"]
    url = f"https://data.sec.gov/submissions/CIK{CIK}.json"
    headers = {"User-Agent": "TeslaFetcher/1.0 (contact@example.com)"}
    response = requests.get(url, headers=headers, timeout=30)
    data = response.json()
    filings = []
    recent_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    for idx, form_type in enumerate(data.get("filings", {}).get("recent", {}).get("form", [])):
        if form_type in forms:
            filing_date = data["filings"]["recent"]["filingDate"][idx]
            if filing_date >= recent_date:
                accession_number = data["filings"]["recent"]["accessionNumber"][idx]
                primary_document = data["filings"]["recent"]["primaryDocument"][idx]
                filings.append({
                    "form": form_type, "date": filing_date,
                    "accession": accession_number, "document": primary_document,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{CIK}/{accession_number.replace('-', '')}/{primary_document}"
                })
    seen = set(); unique = []
    for f in filings:
        key = (f["form"], f["date"])
        if key not in seen:
            seen.add(key); unique.append(f)
    return unique


def fetch_filing_content(url):
    headers = {"User-Agent": "TeslaFetcher/1.0 (contact@example.com)"}
    response = requests.get(url, headers=headers, timeout=60)
    return response.text


def extract_text_from_html(html_content):
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_financial_number(text, pattern):
    """从文本中提取数字和单位"""
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    matched = match.group(0)
    num_match = re.search(r'[\d,]+\.?\d*', matched)
    if not num_match:
        return None
    try:
        num = float(num_match.group().replace(',', ''))
    except (ValueError, AttributeError):
        return None
    if num <= 0:
        return num
    lower = matched.lower()
    if 'billion' in lower:
        num *= 1_000_000_000
    elif 'million' in lower:
        num *= 1_000_000
    elif 'thousand' in lower:
        num *= 1_000
    return num


def extract_financial_metrics(text):
    """提取关键财务指标"""
    metrics = {}
    text_lower = text.lower()
    
    # 营收
    for pattern in [
        r'(?:total\s+)?(?:revenue|net\s+sales?)\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?',
    ]:
        val = parse_financial_number(text, pattern)
        if val and abs(val) > 1_000_000:
            metrics['revenue'] = val
            break
    
    # 净利润
    for pattern in [
        r'net\s+(?:income|loss)\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?',
    ]:
        val = parse_financial_number(text, pattern)
        if val is not None and abs(val) > 100_000:
            metrics['net_income'] = val
            break
    
    # 毛利率
    match = re.search(r'gross\s+margin\s*[:\-]?\s*[\d,]+\.?\d*\s*%', text, re.IGNORECASE)
    if match:
        val_match = re.search(r'[\d,]+\.?\d*', match.group())
        if val_match:
            try:
                metrics['gross_margin'] = float(val_match.group().replace(',', ''))
            except ValueError:
                pass
    
    # 研发费用
    match = re.search(r'research\s+and\s+development\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?', text, re.IGNORECASE)
    if match:
        val = parse_financial_number(text, r'research\s+and\s+development\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
        if val and abs(val) > 100_000:
            metrics['rd_expense'] = val
    
    # 现金
    for pattern in [
        r'cash\s+(?:and\s+)?(?:cash\s+)?equivalents?\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?',
    ]:
        val = parse_financial_number(text, pattern)
        if val and abs(val) > 100_000_000:
            metrics['cash'] = val
            break
    
    # 总资产
    for pattern in [
        r'total\s+assets\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?',
    ]:
        val = parse_financial_number(text, pattern)
        if val and abs(val) > 1_000_000_000:
            metrics['total_assets'] = val
            break
    
    # 每股收益
    match = re.search(r'(?:earnings|net\s+income)\s+per\s+share\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*', text, re.IGNORECASE)
    if match:
        val_match = re.search(r'[\d,]+\.?\d*', match.group())
        if val_match:
            try:
                metrics['eps'] = float(val_match.group().replace(',', ''))
            except ValueError:
                pass
    
    # 汽车业务营收
    val = parse_financial_number(text, r'automotive\s+(?:sales|revenue)\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
    if val and abs(val) > 1_000_000:
        metrics['automotive_revenue'] = val
    
    # 能源业务营收
    val = parse_financial_number(text, r'energy\s+(?:generation|storage|segment)\s*(?:revenue)?\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
    if val and abs(val) > 100_000:
        metrics['energy_revenue'] = val
    
    # 服务业务营收
    val = parse_financial_number(text, r'services?\s+revenue\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
    if val and abs(val) > 100_000:
        metrics['services_revenue'] = val
    
    return metrics


def format_number(num):
    if num is None: return "N/A"
    if abs(num) >= 1_000_000_000: return f"${num/1_000_000_000:.2f}B"
    if abs(num) >= 1_000_000: return f"${num/1_000_000:.2f}M"
    if abs(num) >= 1_000: return f"${num/1_000:.2f}K"
    return f"${num:.2f}"


def calculate_change(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def generate_report(current_filing, current_metrics, previous_filing, previous_metrics):
    form_name = "年报" if current_filing["form"] == "10-K" else "季报"
    report = []
    report.append("=" * 55)
    report.append("          Tesla 财务分析报告")
    report.append("=" * 55)
    report.append(f"报告期: {current_filing['date']} ({form_name})")
    if previous_filing:
        report.append(f"对比期: {previous_filing['date']}")
    report.append(f"原文链接: {current_filing['url']}")
    report.append("")
    report.append("-" * 55)
    report.append("【核心指标】")
    report.append("-" * 55)
    report.append("")
    
    metrics_display = [
        ("revenue", "营业收入", True),
        ("net_income", "净利润", True),
        ("gross_margin", "毛利率(%)", False),
        ("rd_expense", "研发费用", True),
        ("cash", "现金及等价物", True),
        ("total_assets", "总资产", True),
        ("automotive_revenue", "汽车业务", True),
        ("energy_revenue", "能源业务", True),
        ("services_revenue", "服务业务", True),
        ("eps", "每股收益($)", True),
    ]
    
    for key, chinese_name, show_change in metrics_display:
        curr = current_metrics.get(key)
        prev = previous_metrics.get(key) if previous_metrics else None
        
        if curr is not None:
            if key == "gross_margin":
                curr_str = f"{curr:.1f}%"
            elif key == "eps":
                curr_str = f"${curr:.2f}"
            else:
                curr_str = format_number(curr)
            
            if show_change and prev is not None:
                change = calculate_change(curr, prev)
                if change is not None:
                    arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                    report.append(f"  {chinese_name}: {curr_str}  {arrow}{abs(change):.1f}%")
                    continue
            report.append(f"  {chinese_name}: {curr_str}")
    
    report.append("")
    report.append("-" * 55)
    report.append("【关键变化分析】")
    report.append("-" * 55)
    report.append("")
    
    changes = []
    if 'revenue' in current_metrics and 'revenue' in previous_metrics if previous_metrics else False:
        if previous_metrics:
            rev_change = calculate_change(current_metrics['revenue'], previous_metrics['revenue'])
            if rev_change is not None and abs(rev_change) > 3:
                direction = "增长" if rev_change > 0 else "下降"
                changes.append(f"  • 营业收入{direction} {abs(rev_change):.1f}%，{direction}至 {format_number(current_metrics['revenue'])}")
    
    if previous_metrics and 'net_income' in current_metrics and 'net_income' in previous_metrics:
        ni_change = calculate_change(current_metrics['net_income'], previous_metrics['net_income'])
        if ni_change is not None and abs(ni_change) > 5:
            direction = "增长" if ni_change > 0 else "下降"
            changes.append(f"  • 净利润{direction} {abs(ni_change):.1f}%，{direction}至 {format_number(current_metrics['net_income'])}")
    
    if previous_metrics and 'automotive_revenue' in current_metrics and 'automotive_revenue' in previous_metrics:
        auto_change = calculate_change(current_metrics['automotive_revenue'], previous_metrics['automotive_revenue'])
        if auto_change is not None and abs(auto_change) > 3:
            direction = "增长" if auto_change > 0 else "下降"
            changes.append(f"  • 汽车业务{direction} {abs(auto_change):.1f}%，{direction}至 {format_number(current_metrics['automotive_revenue'])}")
    
    if changes:
        for c in changes: report.append(c)
    else:
        report.append("  • 主要财务指标相对稳定")
    
    report.append("")
    
    # 业务构成
    report.append("-" * 55)
    report.append("【业务构成占比】")
    report.append("-" * 55)
    report.append("")
    
    if 'revenue' in current_metrics:
        total_rev = current_metrics['revenue']
        if 'automotive_revenue' in current_metrics and total_rev > 0:
            pct = (current_metrics['automotive_revenue'] / total_rev) * 100
            report.append(f"  • 汽车业务: {pct:.0f}% ({format_number(current_metrics['automotive_revenue'])})")
        if 'energy_revenue' in current_metrics and total_rev > 0:
            pct = (current_metrics['energy_revenue'] / total_rev) * 100
            report.append(f"  • 能源业务: {pct:.0f}% ({format_number(current_metrics['energy_revenue'])})")
        if 'services_revenue' in current_metrics and total_rev > 0:
            pct = (current_metrics['services_revenue'] / total_rev) * 100
            report.append(f"  • 服务业务: {pct:.0f}% ({format_number(current_metrics['services_revenue'])})")
    
    report.append("")
    
    # 总结
    report.append("-" * 55)
    report.append("【总结】")
    report.append("-" * 55)
    report.append("")
    
    summary = []
    if 'revenue' in current_metrics:
        summary.append(f"营收 {format_number(current_metrics['revenue'])}")
    if 'net_income' in current_metrics:
        ni = current_metrics['net_income']
        if ni > 0: summary.append(f"净利润 {format_number(ni)}")
        else: summary.append(f"净亏损 {format_number(abs(ni))}")
    if 'gross_margin' in current_metrics:
        summary.append(f"毛利率 {current_metrics['gross_margin']:.0f}%")
    
    if summary:
        report.append("  " + " | ".join(summary))
    
    report.append("")
    report.append("=" * 55)
    report.append(f"报告生成: {datetime.now().strftime('%Y-%m-%d')} | 数据来源: SEC")
    report.append("=" * 55)
    return "\n".join(report)


def send_email(subject, content, recipient):
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "未设置邮件账户"
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient
    
    for server_host, port, method in [(SMTP_SERVER, 25, "starttls"), (SMTP_SERVER, 587, "starttls"), (SMTP_SERVER, 465, "ssl")]:
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
        filings = get_recent_filings(forms=["10-K", "10-Q"], days_back=730)
        print(f"找到 {len(filings)} 个财报")
        
        current_filing = None; previous_filing = None
        for f in filings:
            if f["form"] in ["10-Q", "10-K"]:
                if current_filing is None:
                    current_filing = f
                elif current_filing["form"] == f["form"]:
                    previous_filing = f
                    break
        
        if not current_filing:
            print("未找到财报"); return
        print(f"当前: {current_filing['form']} {current_filing['date']}")
        if previous_filing: print(f"上期: {previous_filing['form']} {previous_filing['date']}")
        
        print("下载当前财报...")
        current_html = fetch_filing_content(current_filing["url"])
        current_text = extract_text_from_html(current_html)
        current_metrics = extract_financial_metrics(current_text)
        print(f"当前指标: {current_metrics}")
        
        previous_metrics = {}
        if previous_filing:
            print("下载上期财报...")
            previous_html = fetch_filing_content(previous_filing["url"])
            previous_text = extract_text_from_html(previous_html)
            previous_metrics = extract_financial_metrics(previous_text)
            print(f"上期指标: {previous_metrics}")
        
        print("生成分析报告...")
        report = generate_report(current_filing, current_metrics, previous_filing, previous_metrics)
        print(report)
        
        filename_key = f"{current_filing['form']}_{current_filing['date']}_report.txt"
        report_file = os.path.join(OUTPUT_DIR, filename_key)
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        
        form_name = "年报" if current_filing["form"] == "10-K" else "季报"
        email_subject = f"【Tesla分析报告】{form_name} {current_filing['date']}"
        print(f"\n发送邮件至 {RECIPIENT}...")
        success, error = send_email(email_subject, report, RECIPIENT)
        if success: print("✅ 报告已发送")
        else: print(f"❌ 邮件发送失败: {error}")
    except Exception as e:
        print(f"错误: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    analyze_filings()
