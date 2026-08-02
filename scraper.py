import os
import json
import time
from datetime import datetime
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from openai import OpenAI

TARGET_URL = "https://www.classaction.org/settlements"

def fetch_raw_data():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        response = curl_requests.get(TARGET_URL, headers=headers, impersonate="chrome120", timeout=30)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".card, .settlement-card, article.settlement")
        
        raw_items = []
        for card in cards[:15]:
            title = card.find(["h2", "h3", "h4"]).get_text(strip=True) if card.find(["h2", "h3", "h4"]) else ""
            desc = card.select_one(".description, p").get_text(strip=True) if card.select_one(".description, p") else ""
            link = card.find("a", href=True)["href"] if card.find("a", href=True) else ""
            if link.startswith("/"): link = "https://www.classaction.org" + link
            if title and link: raw_items.append({"title": title, "desc": desc, "url": link})
        return raw_items
    except Exception as e:
        return []

def ai_parse_and_translate(item, client):
    prompt = f"""
    请提取以下索赔信息，仅返回 JSON：
    标题: {item['title']}
    描述: {item['desc']}
    格式：{{"title":"中文名", "country":"US/CA/AU", "payout_per_person":"金额", "total_fund_usd":数字, "total_fund_display":"文本", "deadline":"YYYY-MM-DD", "is_expired":false, "is_consumer_goods":true/false, "no_proof_required":true/false, "no_invite_code":true/false, "summary":"30字摘要"}}
    """
    try:
        response = client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"): content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
        if content.lower().startswith("json"): content = content[4:].strip()
        parsed_data = json.loads(content)
        parsed_data["official_url"] = item["url"]
        return parsed_data
    except Exception as e:
        print(f"解析失败: {e}")
        return None

def main():
    api_key = os.getenv("AI_API_KEY", "").strip().replace('"', '').replace("'", "")
    if not api_key: return
    
    # 使用极度稳定的 OpenAI 兼容网关
    client = OpenAI(
        api_key=api_key,
        base_url="[https://generativelanguage.googleapis.com/v1beta/openai/](https://generativelanguage.googleapis.com/v1beta/openai/)"
    )
        
    raw_list = fetch_raw_data()
    parsed_results = []
    
    for item in raw_list:
        parsed = ai_parse_and_translate(item, client)
        if parsed and not parsed.get("is_expired", False):
            parsed_results.append(parsed)
        time.sleep(5) 
    
    parsed_results.sort(key=lambda x: x.get("total_fund_usd", 0) or 0, reverse=True)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "items": parsed_results}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
