import os
import json
import time
from datetime import datetime
from curl_cffi import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# 初始化 AI 客户端 (自动从云端配置中获取 API 密钥)
client = OpenAI(
    api_key=os.getenv("AI_API_KEY"),
    base_url=os.getenv("AI_BASE_URL", "https://api.deepseek.com") # 默认支持 DeepSeek，也可换 GPT
)

TARGET_URL = "https://www.classaction.org/settlements"

def fetch_raw_data():
    """使用模拟真实 Chrome 的底层请求，绕过 Cloudflare 防火墙"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        response = requests.get(TARGET_URL, headers=headers, impersonate="chrome120", timeout=20)
        if response.status_code != 200:
            print(f"请求失败，状态码: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".card, .settlement-card, article.settlement")
        
        raw_items = []
        for card in cards[:15]:  # 每次扫描最前沿的 15 个案件
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
    """调用大模型提炼核心要素、清洗数据并翻译成中文"""
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
        "is_expired": true/false (判断截止日期是否已经过期，已过期的填 true),
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
        # 清理可能存在的 markdown 代码块符号
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("\n", 1)[0]
        data = json.loads(content)
        data["official_url"] = item["url"]
        return data
    except Exception as e:
        print(f"AI 解析错误: {e}")
        return None

def main():
    print("🚀 开始全网巡检与解析...")
    raw_list = fetch_raw_data()
    parsed_results = []
    
    for item in raw_list:
        parsed = ai_parse_and_translate(item)
        # 过滤规则：必须没过期
        if parsed and not parsed.get("is_expired", False):
            parsed_results.append(parsed)
            print(f"✅ 解析成功: {parsed['title']} | 总额: {parsed['total_fund_display']}")
        time.sleep(1) # 防频繁请求
    
    # 核心排序逻辑：按总金额从大到小排序，未知/未披露的排在最后 (total_fund_usd 为 0 的排最后)
    parsed_results.sort(key=lambda x: x.get("total_fund_usd", 0), reverse=True)
    
    # 保存为前端读取的 data.json
    output = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": parsed_results
    }
    
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 数据处理完毕，共保留 {len(parsed_results)} 个未过期案件，已写入 data.json。")

if __name__ == "__main__":
    main()
