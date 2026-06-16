#!/usr/bin/env python3
"""
Tesla SEC Financial Reports Fetcher
定期抓取特斯拉财报、翻译成中文、发送到邮箱
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
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

CIK = "0001318605"
OUTPUT_DIR = "sec_filings"

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.126.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
RECIPIENT = os.getenv("RECIPIENT", "luochan@126.com")


def get_recent_filings(forms=None, days_back=90):
    if forms is None:
        forms = ["10-K", "10-Q"]

    url = f"https://data.sec.gov/submissions/CIK{CIK}.json"
    headers = {"User-Agent": "TeslaFetcher/1.0 (contact@example.com)"}

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()

    filings = []
    recent_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    for idx, form_type in enumerate(data.get("filings", {}).get("recent", {}).get("form", [])):
        if form_type in forms:
            filing_date = data["filings"]["recent"]["filingDate"][idx]
            accession_number = data["filings"]["recent"]["accessionNumber"][idx]
            primary_document = data["filings"]["recent"]["primaryDocument"][idx]

            if filing_date >= recent_date:
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
    response.raise_for_status()
    return response.text


def extract_key_financial_data(html_content):
    """从财报中提取关键财务数据"""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    print(f"    文本总长度: {len(text)} 字符")
    
    # 关键财务术语和关键词
    keyword_patterns = [
        (r'(?:total\s+)?(?:revenues?|net\s+sales?)', '营收/收入'),
        (r'(?:net\s+)?income[s]?', '净利润'),
        (r'(?:gross\s+)?(?:profit|margin)', '毛利率/利润'),
        (r'total\s+assets', '总资产'),
        (r'total\s+liabilit', '总负债'),
        (r'(?:stockholders?|shareholders?)\s+(?:equity|deficit)', '股东权益'),
        (r'cash\s+(?:and\s+)?(?:cash\s+)?equivalents?', '现金及等价物'),
        (r'operating\s+(?:expenses?|income|loss)', '运营费用/收入'),
        (r'research\s+and\s+development', '研发费用'),
        (r'earnings?\s+per\s+share', '每股收益'),
        (r'automotive\s+(?:sales?|revenue)', '汽车业务营收'),
        (r'energy\s+(?:generation|storage|segment)', '能源业务'),
        (r'services?\s+revenue', '服务业务营收'),
    ]
    
    # 在全文中搜索这些关键词的上下文
    found_snippets = []
    text_lower = text.lower()
    
    for pattern, chinese_label in keyword_patterns:
        matches = [(m.start(), m.end()) for m in re.finditer(pattern, text_lower)]
        for start, end in matches[:3]:  # 每个关键词取前3个
            snippet_start = max(0, start - 50)
            snippet_end = min(len(text), end + 150)
            snippet = text[snippet_start:snippet_end]
            # 清理多余空格
            snippet = re.sub(r'\s+', ' ', snippet).strip()
            found_snippets.append((chinese_label, snippet))
    
    print(f"    找到 {len(found_snippets)} 个财务相关片段")
    
    # 去重，合并相似内容
    seen_snippets = set()
    unique_snippets = []
    for label, snippet in found_snippets:
        # 用前50字符作为去重key
        key = snippet[:80].strip()
        if key not in seen_snippets and len(snippet) > 50:
            seen_snippets.add(key)
            unique_snippets.append((label, snippet))
    
    return unique_snippets[:30]  # 最多取30段


def translate_chunk(text, retries=3):
    url = "https://api.mymemory.translated.net/get"
    encoded_text = urllib.parse.quote(text)
    full_url = f"{url}?q={encoded_text}&langpair=en|zh-CN"

    for attempt in range(retries):
        try:
            resp = requests.get(full_url, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                response_status = result.get("responseStatus", 200)
                if response_status == 200:
                    translated = result.get("responseData", {}).get("translatedText", "")
                    if translated and translated != "NO QUERY SPECIFIED":
                        return translated, None
        except Exception as e:
            pass
        
        if attempt < retries - 1:
            time.sleep(random.uniform(5, 10))
    
    return None, "翻译失败"


def translate_financial_snippets(snippets):
    """翻译财务数据片段"""
    translated_pairs = []
    
    print(f"    开始翻译 {len(snippets)} 段财务数据...")
    
    for i, (label, original_text) in enumerate(snippets):
        # 缩短片段，提高翻译质量
        snippet = original_text[:200].strip()
        
        print(f"    翻译 [{label}] ({i+1}/{len(snippets)})...")
        translated, error = translate_chunk(snippet)
        
        if error:
            print(f"      翻译失败，保留原文")
            translated_pairs.append((label, snippet, snippet))
        else:
            translated_pairs.append((label, snippet, translated))
        
        time.sleep(random.uniform(3, 6))
    
    return translated_pairs


def send_email(subject, content, recipient):
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "未设置邮件账户"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient

    msg.attach(MIMEText(content, "plain", "utf-8"))

    configs = [
        (SMTP_SERVER, 25, "starttls"),
        (SMTP_SERVER, 587, "starttls"),
        (SMTP_SERVER, 465, "ssl"),
    ]
    
    last_error = None
    for server_host, port, method in configs:
        try:
            print(f"      尝试 {server_host}:{port} ({method})...")
            
            if method == "ssl":
                server = smtplib.SMTP_SSL(server_host, port, timeout=30)
            else:
                server = smtplib.SMTP(server_host, port, timeout=30)
                server.starttls()
            
            print(f"      连接成功，正在登录...")
            server.login(SMTP_USER, SMTP_PASSWORD)
            print(f"      登录成功，正在发送...")
            server.sendmail(SMTP_USER, recipient, msg.as_string())
            server.quit()
            print(f"      ✅ 邮件发送成功!")
            return True, None
        except Exception as e:
            last_error = str(e)
            print(f"      ❌ 失败: {e}")
    
    return False, last_error


def process_filing(filing):
    form_name = "年报" if filing["form"] == "10-K" else "季报"
    date_cn = filing["date"]
    filename_key = f"{filing['form']}_{filing['date']}"

    print(f"  处理 {filing['form']} ({form_name}) 提交于 {date_cn}...")

    marker_file = os.path.join(OUTPUT_DIR, f"{filename_key}.done")
    if os.path.exists(marker_file):
        print(f"    已处理，跳过")
        return None

    print(f"    下载中...")
    html_content = fetch_filing_content(filing["url"])
    
    print(f"    提取关键财务数据...")
    financial_snippets = extract_key_financial_data(html_content)
    
    if not financial_snippets:
        print(f"    警告: 没有找到财务数据")
        return None
    
    print(f"    翻译财务数据...")
    translated_pairs = translate_financial_snippets(financial_snippets)
    
    # 构建邮件内容
    email_body = []
    email_body.append(f"Tesla {form_name} ({filing['form']})")
    email_body.append(f"提交日期: {date_cn}")
    email_body.append(f"原文链接: {filing['url']}")
    email_body.append("")
    email_body.append("=" * 60)
    email_body.append("关键财务数据摘要 (英译中):")
    email_body.append("=" * 60)
    email_body.append("")
    
    current_label = None
    for i, (label, original, translated) in enumerate(translated_pairs):
        if label != current_label:
            email_body.append(f"\n【{label}】")
            current_label = label
        email_body.append(f"{i+1}. 原文: {original[:150]}")
        email_body.append(f"   中文: {translated[:150]}")
        email_body.append("")
    
    email_body.append("")
    email_body.append("=" * 60)
    email_body.append("注意: 这是机器翻译的财务数据摘要，请结合原文理解")
    email_body.append(f"完整财报: {filing['url']}")
    
    email_content = "\n".join(email_body)
    
    # 保存原文
    translated_file = os.path.join(OUTPUT_DIR, f"{filename_key}_financial_data.txt")
    with open(translated_file, "w", encoding="utf-8") as f:
        f.write(email_content)
    
    email_subject = f"[Tesla SEC] {form_name} {date_cn} - 财务摘要"
    
    print(f"    发送邮件至 {RECIPIENT}...")
    success, email_error = send_email(email_subject, email_content, RECIPIENT)

    if success:
        print(f"    ✅ 邮件已发送")
        with open(marker_file, "w") as f:
            f.write(datetime.now().isoformat())
    else:
        print(f"    邮件发送失败: {email_error}")

    return translated_pairs


def check_new_filings():
    print(f"[{datetime.now().isoformat()}] 检查 Tesla (TSLA) 最新 SEC 文件...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        filings = get_recent_filings(forms=["10-K", "10-Q"], days_back=90)
        print(f"找到 {len(filings)} 个最近财报 (10-K, 10-Q)")

        for filing in filings:
            process_filing(filing)

        print("检查完成")

    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    check_new_filings()
