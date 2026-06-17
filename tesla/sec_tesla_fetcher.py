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
                    "form": form_type,
                    "date": filing_date,
                    "accession": accession_number,
                    "document": primary_document,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{CIK}/{accession_number.replace('-', '')}/{primary_document}"
                })

    seen = set()
    unique = []
    for f in filings:
        key = (f["form"], f["date"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
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
    
    num_str = match.group(0)
    # 提取数字
    num_match = re.search(r'[\d,]+\.?\d*', num_str)
    if not num_match:
        return None
    
    num = float(num_match.group().replace(',', ''))
    
    # 判断单位
    if 'billion' in num_str.lower() or 'B' in num_str:
        num *= 1_000_000_000
    elif 'million' in num_str.lower() or 'M' in num_str:
        num *= 1_000_000
    elif 'thousand' in num_str.lower() or 'K' in num_str:
        num *= 1_000
    
    return num


def extract_financial_metrics(text):
    """提取关键财务指标"""
    metrics = {}
    
    # 营收
    patterns = [
        (r'(?:total\s+)?(?:revenues?|net\s+sales?)\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?',
         'revenue'),
        (r'(?:revenues?|net\s+sales?)\s*\(?\s*\$\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?\s*\)?',
         'revenue'),
    ]
    for pattern, key in patterns:
        val = parse_financial_number(text, pattern)
        if val and val > 1_000_000:  # 至少100万
            metrics[key] = val
            break
    
    # 净利润
    patterns = [
        (r'net\s+(?:income|loss)\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?',
         'net_income'),
        (r'(?:income|loss)\s*\(?\s*\$\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?\s*\)?',
         'net_income'),
    ]
    for pattern, key in patterns:
        val = parse_financial_number(text, pattern)
        if val:
            metrics[key] = val
            break
    
    # 毛利率
    match = re.search(r'gross\s+margin\s*[:\-]?\s*[\d,]+\.?\d*\s*%', text, re.IGNORECASE)
    if match:
        val = re.search(r'[\d,]+\.?\d*', match.group()).group()
        metrics['gross_margin'] = float(val.replace(',', ''))
    
    # 研发费用
    match = re.search(r'research\s+and\s+development\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?', text, re.IGNORECASE)
    if match:
        val = parse_financial_number(text, r'research\s+and\s+development\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
        if val:
            metrics['rd_expense'] = val
    
    # 现金
    patterns = [
        r'cash\s+(?:and\s+)?(?:cash\s+)?equivalents?\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = parse_financial_number(text, pattern)
            if val and val > 100_000_000:
                metrics['cash'] = val
                break
    
    # 总资产
    match = re.search(r'total\s+assets\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?', text, re.IGNORECASE)
    if match:
        val = parse_financial_number(text, r'total\s+assets\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
        if val:
            metrics['total_assets'] = val
    
    # 每股收益
    match = re.search(r'(?:earnings?|net\s+income)\s+per\s+share\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*', text, re.IGNORECASE)
    if match:
        val = re.search(r'[\d,]+\.?\d*', match.group())
        if val:
            metrics['eps'] = float(val.group().replace(',', ''))
    
    # 汽车业务营收
    match = re.search(r'automotive\s+(?:sales?|revenue)\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?', text, re.IGNORECASE)
    if match:
        val = parse_financial_number(text, r'automotive\s+(?:sales?|revenue)\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
        if val:
            metrics['automotive_revenue'] = val
    
    # 能源业务营收
    match = re.search(r'energy\s+(?:generation|storage|segment)\s*(?:revenue)?\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?', text, re.IGNORECASE)
    if match:
        val = parse_financial_number(text, r'energy\s+(?:generation|storage|segment)\s*(?:revenue)?\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
        if val:
            metrics['energy_revenue'] = val
    
    # 服务业务营收
    match = re.search(r'services?\s+revenue\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?', text, re.IGNORECASE)
    if match:
        val = parse_financial_number(text, r'services?\s+revenue\s*[:\-]?\s*\$?\s*[\d,]+\.?\d*\s*(?:million|billion|thousand)?')
        if val:
            metrics['services_revenue'] = val
    
    return metrics


def translate_to_chinese(text, retries=3):
    url = "https://api.mymemory.translated.net/get"
    encoded_text = urllib.parse.quote(text[:200])
    full_url = f"{url}?q={encoded_text}&langpair=en|zh-CN"

    for attempt in range(retries):
        try:
            resp = requests.get(full_url, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("responseStatus") == 200:
                    t = result.get("responseData", {}).get("translatedText", "")
                    if t and t != "NO QUERY SPECIFIED":
                        return t
        except:
            pass
        time.sleep(random.uniform(2, 5))
    return None


def format_number(num):
    """格式化数字显示"""
    if num is None:
        return "N/A"
    
    if abs(num) >= 1_000_000_000:
        return f"${num/1_000_000_000:.2f}B"
    elif abs(num) >= 1_000_000:
        return f"${num/1_000_000:.2f}M"
    elif abs(num) >= 1_000:
        return f"${num/1_000:.2f}K"
    else:
        return f"${num:.2f}"


def calculate_change(current, previous):
    """计算变化百分比"""
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def generate_report(current_filing, current_metrics, previous_filing, previous_metrics):
    """生成分析报告"""
    form_name = "年报" if current_filing["form"] == "10-K" else "季报"
    
    report = []
    report.append("=" * 60)
    report.append("       Tesla 财务分析报告")
    report.append("=" * 60)
    report.append("")
    report.append(f"报告期: {current_filing['date']} ({form_name})")
    report.append(f"对比期: {previous_filing['date']} ({'年报' if previous_filing['form'] == '10-K' else '季报'})")
    report.append(f"报告链接: {current_filing['url']}")
    report.append("")
    
    # 核心指标对比
    report.append("-" * 60)
    report.append("【核心指标对比】")
    report.append("-" * 60)
    report.append("")
    
    metrics_display = [
        ("revenue", "营业收入", True),
        ("net_income", "净利润", True),
        ("gross_margin", "毛利率", False),
        ("rd_expense", "研发费用", True),
        ("cash", "现金及等价物", True),
        ("total_assets", "总资产", True),
        ("automotive_revenue", "汽车业务营收", True),
        ("energy_revenue", "能源业务营收", True),
        ("services_revenue", "服务业务营收", True),
        ("eps", "每股收益", True),
    ]
    
    for key, chinese_name, show_change in metrics_display:
        curr = current_metrics.get(key)
        prev = previous_metrics.get(key)
        
        if curr is not None:
            curr_str = format_number(curr) if not key == "gross_margin" else f"{curr:.1f}%"
            change = calculate_change(curr, prev)
            
            if show_change and change is not None:
                arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                change_str = f"{arrow} {abs(change):.1f}%"
                report.append(f"  {chinese_name}: {curr_str}  ({change_str})")
            elif key == "gross_margin":
                report.append(f"  {chinese_name}: {curr_str}")
            else:
                report.append(f"  {chinese_name}: {curr_str}")
        elif prev is not None:
            prev_str = format_number(prev) if not key == "gross_margin" else f"{prev:.1f}%"
            report.append(f"  {chinese_name}: {prev_str} (上期)")
    
    report.append("")
    
    # 关键变化分析
    report.append("-" * 60)
    report.append("【关键变化分析】")
    report.append("-" * 60)
    report.append("")
    
    changes = []
    
    if 'revenue' in current_metrics and 'revenue' in previous_metrics:
        rev_change = calculate_change(current_metrics['revenue'], previous_metrics['revenue'])
        if rev_change is not None:
            if abs(rev_change) > 5:
                direction = "增长" if rev_change > 0 else "下降"
                changes.append(f"  • 营业收入{direction} {abs(rev_change):.1f}%，{direction}至 {format_number(current_metrics['revenue'])}")
    
    if 'net_income' in current_metrics and 'net_income' in previous_metrics:
        ni_change = calculate_change(current_metrics['net_income'], previous_metrics['net_income'])
        if ni_change is not None:
            if abs(ni_change) > 10:
                direction = "增长" if ni_change > 0 else "下降"
                changes.append(f"  • 净利润{direction} {abs(ni_change):.1f}%，{direction}至 {format_number(current_metrics['net_income'])}")
    
    if 'automotive_revenue' in current_metrics and 'automotive_revenue' in previous_metrics:
        auto_change = calculate_change(current_metrics['automotive_revenue'], previous_metrics['automotive_revenue'])
        if auto_change is not None and abs(auto_change) > 3:
            direction = "增长" if auto_change > 0 else "下降"
            changes.append(f"  • 汽车业务{direction} {abs(auto_change):.1f}%，{direction}至 {format_number(current_metrics['automotive_revenue'])}")
    
    if 'gross_margin' in current_metrics and 'gross_margin' in previous_metrics:
        gm_change = current_metrics['gross_margin'] - previous_metrics['gross_margin']
        if abs(gm_change) > 1:
            direction = "上升" if gm_change > 0 else "下降"
            changes.append(f"  • 毛利率{direction} {abs(gm_change):.1f}个百分点，至 {current_metrics['gross_margin']:.1f}%")
    
    if 'cash' in current_metrics and 'cash' in previous_metrics:
        cash_change = calculate_change(current_metrics['cash'], previous_metrics['cash'])
        if cash_change is not None and abs(cash_change) > 10:
            direction = "增加" if cash_change > 0 else "减少"
            changes.append(f"  • 现金{direction} {abs(cash_change):.1f}%，当前 {format_number(current_metrics['cash'])}")
    
    if changes:
        for c in changes:
            report.append(c)
    else:
        report.append("  • 主要财务指标相对稳定")
    
    report.append("")
    
    # 业务构成分析
    report.append("-" * 60)
    report.append("【业务构成】")
    report.append("-" * 60)
    report.append("")
    
    if 'revenue' in current_metrics:
        total_rev = current_metrics['revenue']
        
        if 'automotive_revenue' in current_metrics:
            auto_pct = (current_metrics['automotive_revenue'] / total_rev) * 100
            report.append(f"  • 汽车业务: {auto_pct:.1f}% ({format_number(current_metrics['automotive_revenue'])})")
        
        if 'energy_revenue' in current_metrics:
            energy_pct = (current_metrics['energy_revenue'] / total_rev) * 100
            report.append(f"  • 能源业务: {energy_pct:.1f}% ({format_number(current_metrics['energy_revenue'])})")
        
        if 'services_revenue' in current_metrics:
            svc_pct = (current_metrics['services_revenue'] / total_rev) * 100
            report.append(f"  • 服务业务: {svc_pct:.1f}% ({format_number(current_metrics['services_revenue'])})")
    
    report.append("")
    
    # 总结
    report.append("-" * 60)
    report.append("【总结】")
    report.append("-" * 60)
    report.append("")
    
    # 生成简要总结
    summary_parts = []
    
    if 'revenue' in current_metrics and 'revenue' in previous_metrics:
        rev_change = calculate_change(current_metrics['revenue'], previous_metrics['revenue'])
        if rev_change and rev_change > 0:
            summary_parts.append(f"营收{format_number(current_metrics['revenue'])}，同比增长{rev_change:.0f}%")
        elif rev_change and rev_change < 0:
            summary_parts.append(f"营收{format_number(current_metrics['revenue'])}，同比下降{abs(rev_change):.0f}%")
    
    if 'net_income' in current_metrics:
        ni = current_metrics['net_income']
        if ni > 0:
            summary_parts.append(f"净利润{format_number(ni)}")
        else:
            summary_parts.append(f"净亏损{format_number(abs(ni))}")
    
    if 'gross_margin' in current_metrics:
        summary_parts.append(f"毛利率{gross_margin:.1f}%")
    
    if summary_parts:
        report.append("  " + " | ".join(summary_parts))
    
    report.append("")
    report.append("=" * 60)
    report.append(f"报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"数据来源: SEC EDGAR | Tesla {form_name}")
    report.append("=" * 60)
    
    return "\n".join(report)


def send_email(subject, content, recipient):
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "未设置邮件账户"

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
        filings = get_recent_filings(forms=["10-K", "10-Q"], days_back=730)
        print(f"找到 {len(filings)} 个财报")
        
        # 获取最近两份同类型财报
        current_filing = None
        previous_filing = None
        
        for f in filings:
            if f["form"] in ["10-Q", "10-K"]:
                if current_filing is None:
                    current_filing = f
                elif current_filing["form"] == f["form"]:
                    previous_filing = f
                    break
        
        if not current_filing:
            print("未找到财报")
            return
        
        print(f"当前: {current_filing['form']} {current_filing['date']}")
        if previous_filing:
            print(f"上期: {previous_filing['form']} {previous_filing['date']}")
        else:
            print("未找到上期财报，将只分析当前期")
        
        # 下载并提取数据
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
        
        # 生成报告
        print("生成分析报告...")
        report = generate_report(current_filing, current_metrics, previous_filing, previous_metrics)
        
        # 保存
        filename_key = f"{current_filing['form']}_{current_filing['date']}_report.txt"
        report_file = os.path.join(OUTPUT_DIR, filename_key)
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        
        # 发送邮件
        form_name = "年报" if current_filing["form"] == "10-K" else "季报"
        email_subject = f"【Tesla分析报告】{form_name} {current_filing['date']}"
        
        print(f"发送邮件至 {RECIPIENT}...")
        success, error = send_email(email_subject, report, RECIPIENT)
        
        if success:
            print("✅ 报告已发送")
        else:
            print(f"❌ 邮件发送失败: {error}")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    analyze_filings()
