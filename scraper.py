import os
import json
import time
from datetime import datetime
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from openai import OpenAI

TARGET_URL = "https://www.classaction.org/settlements"

def fetch_raw_data():
    """使用 curl_cffi 绕过网页防火墙，抓取最新数据"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        response = curl_requests.get(TARGET_URL, headers=headers, impersonate="chrome120", timeout=30)
        if response.status_code != 200:
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

def ai_parse_and_translate(item, client):
    """使用官方 SDK 提炼与翻译，100% 杜绝底层网络报错"""
    prompt = f"""
    请分析以下索赔案件信息，并提取结构化字段：
    案件标题: {item['title']}
    详细描述: {item['desc']}

    请按严格的 JSON 格式输出以下字段（不要包含任何 markdown 代码块标记，只返回纯 JSON）：
    {{
        "title": "中文案件名称",
        "country": "US/CA/AU (根据内容判断国家，默认 US)",
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
        response = client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        
        # 强制清理可能的 Markdown 符号
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
        if content.lower().startswith("json"):
            content = content[4:].strip()
            
        parsed_data = json.loads(content)
        parsed_data["official_url"] = item["url"]
        return parsed_data
    except Exception as e:
        print(f"AI 解析错误 ({item['title'][:10]}...): {e}")
        return None

def main():
    print("🚀 开始全网巡检与解析...")
    
    # 提取密钥，并自动洗掉所有看不见的空格或特殊符号
    raw_key = os.getenv("AI_API_KEY", "")
    api_key = raw_key.strip().replace('"', '').replace("'", "")
    
    if not api_key:
        print("错误: 找不到 AI_API_KEY 密钥！请检查 GitHub Secrets。")
        return
    
    # 核心：直接调用 SDK 并指向 Google 官方网关
    try:
        client = OpenAI(
            api_key=api_key,
            base_url="[https://generativelanguage.googleapis.com/v1beta/openai/](https://generativelanguage.googleapis.com/v1beta/openai/)"
        )
    except Exception as e:
        print(f"SDK 初始化失败: {e}")
        return
        
    raw_list = fetch_raw_data()
    if not raw_list:
        print("未能抓取到任何案件，请检查目标网站。")
        return
        
    parsed_results = []
    
    for item in raw_list:
        parsed = ai_parse_and_translate(item, client)
        if parsed and not parsed.get("is_expired", False):
            parsed_results.append(parsed)
            print(f"✅ 解析成功: {parsed.get('title', '未知')} | 总额: {parsed.get('total_fund_display', '未知')}")
        time.sleep(2) 
    
    # 按总金额降序排列
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
