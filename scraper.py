import os
import json
import time
from datetime import datetime
import requests as std_requests
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

TARGET_URL = "https://www.classaction.org/settlements"

def fetch_raw_data():
    """使用 curl_cffi 绕过 Cloudflare 防火墙抓取数据"""
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
        for card in cards[:15]:  # 获取最新15条
            title = card.find(["h2", "h3", "h4"]).get_text(strip=True) if card.find(["h2", "h3", "h4"]) else ""
            desc = card.select_one(".description, p").get_text(strip=True) if card.select_one(".description, p") else ""
            link = card.find("a", href=True)["href"] if card.find("a", href=True) else ""
            if link.startswith("/"):
                link = "https://www.classaction.org" + link
            
            if title and link:
                raw_items.append({"title": title, "desc": desc, "url": link})
        return raw_items
    except Exception as e:
        print(f"抓取异常: {e}")
        return []

def ai_parse_and_translate(item):
    """原生直连 Gemini API 进行解析与翻译"""
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
    
    api_key = os.getenv("AI_API_KEY")
    if not api_key:
        print("错误: 找不到 AI_API_KEY 密钥！")
        return None
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        # 直接通过原生接口发送请求
        response = std_requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # 提取返回的内容
        content = data['candidates'][0]['content']['parts'][0]['text'].strip()
        
        # 清理多余的 Markdown 标记确保 JSON 纯净
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
        if content.lower().startswith("json"):
            content = content[4:].strip()
            
        parsed_data = json.loads(content)
        parsed_data["official_url"] = item["url"]
        return parsed_data
    except Exception as e:
        print(f"AI 解析错误: {e}")
        return None

def main():
    print("🚀 开始全网巡检与解析...")
    raw_list = fetch_raw_data()
    parsed_results = []
    
    for item in raw_list:
        parsed = ai_parse_and_translate(item)
        if parsed and not parsed.get("is_expired", False):
            parsed_results.append(parsed)
            print(f"✅ 解析成功: {parsed.get('title', '未知')} | 总额: {parsed.get('total_fund_display', '未知')}")
        time.sleep(2) # 停顿2秒防止触发接口限流
    
    # 按总金额降序排序
    parsed_results.sort(key=lambda x: x.get("total_fund_usd", 0) or 0, reverse=True)
    
    output = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": parsed_results
    }
    
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 数据处理完毕，共保留 {len(parsed_results)} 个未过期案件，已写入 data.json。")

if __name__ == "__main__":
    main()
