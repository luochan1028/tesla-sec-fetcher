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


def extract_text_from_html(html_content):
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html_content)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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
                else:
                    print(f"      API返回错误状态: {response_status}")
            else:
                print(f"      HTTP错误: {resp.status_code}")
        except Exception as e:
            print(f"      请求异常: {e}")
        
        if attempt < retries - 1:
            time.sleep(random.uniform(5, 10))
    
    return None, "翻译失败"


def translate_to_chinese(text):
    chunks = []
    chunk_size = 150
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i+chunk_size].strip()
        if chunk:
            chunks.append(chunk)

    chunks = chunks[:15]
    print(f"    共 {len(chunks)} 段需要翻译 (每段约{chunk_size}字符)")

    translated_chunks = []
    for i, chunk in enumerate(chunks):
        print(f"    翻译第 {i+1}/{len(chunks)} 段...")
        result, error = translate_chunk(chunk)
        if error:
            print(f"    警告: {error}, 使用原文")
            translated_chunks.append(chunk)
        else:
            translated_chunks.append(result)
        time.sleep(random.uniform(3, 6))

    return "\n".join(translated_chunks), None


def send_email(subject, content, recipient):
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "未设置邮件账户"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient

    msg.attach(MIMEText(content, "plain", "utf-8"))

    ports = [587, 25, 465]
    
    for port in ports:
        for attempt in range(2):
            try:
                if port == 465:
                    server = smtplib.SMTP_SSL(SMTP_SERVER, port, timeout=60)
                else:
                    server = smtplib.SMTP(SMTP_SERVER, port, timeout=60)
                    server.starttls()
                
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, recipient, msg.as_string())
                server.quit()
                return True, None
            except Exception as e:
                print(f"      SMTP端口{port}失败 ({attempt+1}/2): {e}")
                if attempt < 1:
                    time.sleep(5)
    
    return False, "所有SMTP端口都失败"


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
    text_content = extract_text_from_html(html_content)
    print(f"    提取文本完成 (长度: {len(text_content)}字符)")

    if len(text_content) < 200:
        print(f"    文本内容过少，可能格式异常")
        return None

    text_to_translate = text_content[:3000]

    print(f"    翻译中 (英→中, 约{len(text_to_translate)}字符)...")
    translated, error = translate_to_chinese(text_to_translate)

    if error:
        print(f"    翻译失败: {error}")
        translated = text_content[:1500]

    translated_file = os.path.join(OUTPUT_DIR, f"{filename_key}_translated.txt")
    with open(translated_file, "w", encoding="utf-8") as f:
        f.write(translated)
    print(f"    翻译结果已保存")

    email_subject = f"[Tesla SEC] {form_name} {date_cn}"
    email_content = f"""Tesla {form_name} ({filing['form']})
提交日期: {date_cn}
原文链接: {filing['url']}

{translated}
"""

    print(f"    发送邮件至 {RECIPIENT}...")
    success, email_error = send_email(email_subject, email_content, RECIPIENT)

    if success:
        print(f"    邮件已发送")
        with open(marker_file, "w") as f:
            f.write(datetime.now().isoformat())
    else:
        print(f"    邮件发送失败: {email_error}")

    return translated


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
