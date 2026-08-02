import os
import json
import time
from datetime import datetime
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
import google.generativeai as genai  # 引入 Google 官方包

TARGET_URL = "https://www.classaction.org/settlements"

def fetch_raw_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        response = curl_requests.get(TARGET_URL, headers=headers, impersonate="chrome120", timeout=30)
        if response.status_code != 200:
            print(f"抓取网页失败，状态码: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".card, .settlement-card, article.settlement")
        
        raw_items = []
        for card in cards[:15]:
            title_elem = card.find(["h2", "h3", "h4"])
            title = title_elem.get_text(strip=True) if title_elem else ""
            
            desc_elem = card.select_one(".description, p")
            desc = desc_elem.get_text(strip=True) if desc_elem else ""
            
            link_elem = card.find("a", href=True)
            link = link_elem["href"] if link_elem else ""
            if link.startswith("/"):
                link = "https://www.classaction.org" + link
            
            if title and link:
                raw_items.append({"title": title, "desc": desc, "url": link})
        return raw_items
    except Exception as e:
        print(f"网页抓取异常: {e}")
        return []

def ai_parse_and_translate(item):
    prompt = f"""
    请分析以下索赔案件信息，并提取结构化字段：
    案件标题: {item['title']}
    详细描述: {item['desc']}

    请按严格的 JSON 格式输出以下字段（不要包含任何 markdown 代码块标记，只返回纯 JSON）：
    {{
        "title": "中文案件名称",
        "country": "US/CA/AU",
        "payout_per_person": "预计单人赔偿金额 (如 $92.26，未知填'不明确')",
        "total_fund_usd": 数值 (案件总赔偿金额折合美元的数字，如 5000000。如果没提到或未知，必须填 0),
        "total_fund_display": "总金额显示文本 (如 '$5,000万' 或 '未披露')",
        "deadline": "截止日期 (格式如 YYYY-MM-DD，未知填 '近期')",
        "is_expired": false,
        "is_consumer_goods": true/false (是否属于消费/购物/日用品类索赔),
        "no_proof_required": true/false (是否明确不需要购物发票/凭证),
        "no_invite_code": true/false (参与在线申领是否不需要邀请码/PIN，支持通用申领即为 true),
        "summary": "一句话中文摘要（30字以内，说明什么人能领什么钱）"
    }}
    """
    
    try:
        # 完全依照官方文档规范调用
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.1)
        )
        
        content = response.text.strip()
        
        # 清理可能存在的 Markdown 代码块标记
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
        if content.lower().startswith("json"):
            content = content[4:].strip()
            
        parsed_data = json.loads(content)
        parsed_data["official_url"] = item["url"]
        return parsed_data
        
    except Exception as e:
        print(f"AI 解析异常 ({item['title'][:10]}...): {e}")
        return None

def main():
    print("🚀 开始全网巡检与解析...")
    
    # 提取并清理密钥
    raw_key = os.getenv("AI_API_KEY", "")
    api_key = "".join(raw_key.split()).replace('"', '').replace("'", "")
    
    if not api_key:
        print("错误: 找不到 AI_API_KEY 密钥！")
        return
        
    # 按照官方文档：全局配置一次密钥即可
    genai.configure(api_key=api_key)
        
    raw_list = fetch_raw_data()
    if not raw_list:
        print("未能抓取到任何案件，请检查目标网站。")
        return
        
    parsed_results = []
    
    for item in raw_list:
        parsed = ai_parse_and_translate(item)
        if parsed and not parsed.get("is_expired", False):
            parsed_results.append(parsed)
            print(f"✅ 解析成功: {parsed.get('title', '未知')} | 总额: {parsed.get('total_fund_display', '未知')}")
        time.sleep(3) # 遵守官方频率限制
    
    parsed_results.sort(key=lambda x: x.get("total_fund_usd", 0) or 0, reverse=True)
    
    output = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": parsed_results
    }
    
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 完美收工！共保留 {len(parsed_results)} 个有效案件，数据已推送到网页。")

if __name__ == "__main__":
    main()
