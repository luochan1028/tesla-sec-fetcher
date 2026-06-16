#!/usr/bin/env python3
"""
Tesla SEC Financial Reports Fetcher
定期抓取特斯拉财报、提取关键财务数据、翻译成中文、发送到邮箱
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
RECIPIENT = os.getenv("RECIPIENT", "luochan1028@126.com")


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
    
    # 关键财务术语模式
    keyword_patterns = [
        (r'(?:total\s+)?(?:revenues?|net\s+sales?)\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '营收'),
        (r'(?:net\s+)?income\s*(?:loss)?\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '净利润'),
        (r'(?:gross\s+(?:profit|margin))\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:%|million|billion)?', '毛利润'),
        (r'(?:gross\s+margin)\s*[:\-]?\s*[\d,]+(?:\.\d+)?\s*%', '毛利率'),
        (r'(?:total\s+)?assets\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '总资产'),
        (r'(?:stockholders?|shareholders?)\s+(?:equity|deficit)\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '股东权益'),
        (r'cash\s+(?:and\s+)?(?:cash\s+)?equivalents?\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '现金及等价物'),
        (r'research\s+and\s+development\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '研发费用'),
        (r'(?:operating\s+(?:income|expenses?|loss))\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '运营收入/支出'),
        (r'(?:earnings?|net\s+income)\s+per\s+share\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?', '每股收益'),
        (r'(?:automotive|vehicle)\s+(?:sales?|revenue)\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '汽车业务'),
        (r'(?:energy|storage)\s+(?:revenue|generation|segment)\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '能源业务'),
        (r'services?\s+revenue\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '服务业务'),
        (r'(?:free\s+cash\s+flow)\s*[:\-]?\s*\$?\s*[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand)?', '自由现金流'),
        (r'(?:net\s+margin|profit\s+margin)\s*[:\-]?\s*[\d,]+(?:\.\d+)?\s*%', '净利率'),
        (r'(?:return\s+on\s+(?:assets?|equity))\s*[:\-]?\s*[\d,]+(?:\.\d+)?\s*%', '资产/权益回报率'),
    ]
    
    found_snippets = []
    text_lower = text.lower()
    
    for pattern, label in keyword_patterns:
        matches = [(m.start(), m.end()) for m in re.finditer(pattern, text_lower, re.IGNORECASE)]
        for start, end in matches[:5]:
            snippet_start = max(0, start - 30)
            snippet_end = min(len(text), end + 100)
            snippet = re.sub(r'\s+', ' ', text[snippet_start:snippet_end]).strip()
            if len(snippet) > 20:
                found_snippets.append((label, snippet))
    
    # 去重
    seen = set()
    unique = []
    for label, snippet in found_snippets:
        key = snippet[:60]
        if key not in seen:
            seen.add(key)
            unique.append((label, snippet))
    
    return unique[:25]


def translate_chunk(text, retries=3):
    url = "https://api.mymemory.translated.net/get"
    encoded_text = urllib.parse.quote(text)
    full_url = f"{url}?q={encoded_text}&langpair=en|zh-CN"

    for attempt in range(retries):
        try:
            resp = requests.get(full_url, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("responseStatus") == 200:
                    translated = result.get("responseData", {}).get("translatedText", "")
                    if translated and translated != "NO QUERY SPECIFIED":
                        return translated
        except:
            pass
        if attempt < retries - 1:
            time.sleep(random.uniform(3, 7))
    return None


def translate_to_chinese(text):
    # 分段翻译，每段单独翻再组合
    sentences = re.split(r'(?<=[.;])\s+', text)
    chunks = []
    current = ""
    for s in sentences:
        if len(current) + len(s) > 180:
            if current:
                chunks.append(current)
            current = s
        else:
            current = (current + " " + s).strip()
    if current:
        chunks.append(current)
    
    chunks = chunks[:8]
    translated_parts = []
    
    for i, chunk in enumerate(chunks):
        print(f"    翻译第 {i+1}/{len(chunks)} 段...")
        t = translate_chunk(chunk)
        if t:
            translated_parts.append(t)
        time.sleep(random.uniform(2, 5))
    
    return " ".join(translated_parts) if translated_parts else text


def send_email(subject, content, recipient):
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "未设置邮件账户"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient
    msg.attach(MIMEText(content, "plain", "utf-8"))

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
    snippets = extract_key_financial_data(html_content)
    print(f"    找到 {len(snippets)} 条财务数据")
    
    if not snippets:
        print(f"    警告: 没有找到财务数据")
        return None
    
    # 只保留中文翻译
    email_lines = [
        f"Tesla {form_name} 财务摘要",
        f"报告期: {date_cn}",
        f"原文: {filing['url']}",
        "",
        "=" * 50,
        "【关键财务数据】",
        "=" * 50,
        "",
    ]
    
    for i, (label, original) in enumerate(snippets):
        print(f"    翻译 [{label}] ({i+1}/{len(snippets)})...")
        chinese = translate_to_chinese(original)
        if chinese and len(chinese) > 5:
            email_lines.append(f"• {label}: {chinese}")
        else:
            # 翻译失败则跳过，不用英文
            pass
        time.sleep(random.uniform(1, 3))
    
    email_lines.extend([
        "",
        "=" * 50,
        f"完整报告: {filing['url']}",
        "（以上为机器翻译，仅供参考）",
    ])
    
    email_content = "\n".join(email_lines)
    
    # 保存
    translated_file = os.path.join(OUTPUT_DIR, f"{filename_key}_zh.txt")
    with open(translated_file, "w", encoding="utf-8") as f:
        f.write(email_content)
    
    email_subject = f"【Tesla】{form_name} {date_cn} 财务摘要"
    
    print(f"    发送邮件至 {RECIPIENT}...")
    success, error = send_email(email_subject, email_content, RECIPIENT)

    if success:
        print(f"    ✅ 邮件已发送")
        with open(marker_file, "w") as f:
            f.write(datetime.now().isoformat())
    else:
        print(f"    邮件发送失败: {error}")

    return email_content


def check_new_filings():
    print(f"[{datetime.now().isoformat()}] 检查 Tesla 最新 SEC 文件...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        filings = get_recent_filings(forms=["10-K", "10-Q"], days_back=90)
        print(f"找到 {len(filings)} 个财报")

        for filing in filings:
            process_filing(filing)

        print("检查完成")

    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    check_new_filings()
