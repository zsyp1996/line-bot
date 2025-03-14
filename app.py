# 📌 1️⃣ **導入函式庫（Import Libraries）**
import os
import re
import gspread
import json
import base64
from google.oauth2.service_account import Credentials
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FollowEvent
from openai import OpenAI  # 確保 import 最新的 OpenAI 函式庫
from datetime import datetime, timedelta  # 🆕 計算年齡所需

# 📌 2️⃣ **初始化 Flask 與 API 相關變數**
app = Flask(__name__)
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_SECRET = os.getenv("LINE_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 初始化 LINE Bot API
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# 初始化 OpenAI API
client = OpenAI(api_key=OPENAI_API_KEY)

# 📌 3️⃣ **連接 Google Sheets API（使用 Base64 環境變數）**
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# **從環境變數讀取 Base64 JSON 並解碼**
service_account_json_base64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if service_account_json_base64:
    service_account_info = json.loads(base64.b64decode(service_account_json_base64))
    creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    gspread_client = gspread.authorize(creds)

    # **設定試算表 ID**
    SPREADSHEET_ID = "1twgKpgWZIzzy7XoMg08jQfweJ2lP4S2LEcGGq-txMVk"
    sheet = gspread_client.open_by_key(SPREADSHEET_ID).sheet1  # 連接第一個工作表
    print("✅ 成功連接 Google Sheets！")
else:
    print("❌ 無法獲取 GOOGLE_SERVICE_ACCOUNT_JSON，請確認環境變數是否正確設定！")

# 📌 4️⃣ **測試是否成功讀取 Google Sheets**
try:
    sheet_data = sheet.get_all_values()
    print("✅ 成功連接 Google Sheets，內容如下：")
    for row in sheet_data:
        print(row)  # Debug：顯示試算表內容
except Exception as e:
    print("❌ 無法讀取 Google Sheets，錯誤訊息：", e)

# 📌 5️⃣ **計算年齡函式（用於判斷兒童月齡）**
def calculate_age(birthdate_str):
    """計算孩子的實足月齡（滿 30 天進位一個月）"""
    try:
        birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
        today = datetime.today().date()

        years = today.year - birthdate.year
        months = today.month - birthdate.month
        days = today.day - birthdate.day

        if days < 0:
            months -= 1
            last_month_end = today.replace(day=1) - timedelta(days=1)
            days += last_month_end.day

        if months < 0:
            years -= 1
            months += 12

        total_months = years * 12 + months
        if days >= 30:
            total_months += 1

        return total_months
    except ValueError:
        return None

# 📌 6️⃣ **與 OpenAI ChatGPT 互動的函式**
def chat_with_gpt(prompt):
    """與 OpenAI ChatGPT 互動，確保 Bot 只回答篩檢問題"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "你是一個語言篩檢助手，負責回答家長的問題與記錄兒童的語言發展情況，請提供幫助。請使用繁體中文回答。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content  # ✅ 正確回傳 ChatGPT 回應

# 📌 7️⃣ **Flask 路由（API 入口點）**
@app.route("/", methods=["GET"])
def home():
    """首頁（測試用）"""
    return "LINE Bot is Running!"

@app.route("/callback", methods=["POST"])
def callback():
    """處理 LINE Webhook 請求"""
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400

    return "OK"

@app.route("/test_sheets", methods=["GET"])
def test_sheets():
    """測試 Google Sheets API 讀取資料"""
    try:
        sheet_data = sheet.get_all_values()  # 讀取試算表的所有內容
        formatted_data = "\n".join([", ".join(row) for row in sheet_data])  # 轉換為可讀的字串格式
        return f"✅ 成功讀取試算表內容：\n{formatted_data}"
    except Exception as e:
        return f"❌ 無法讀取 Google Sheets，錯誤訊息：{e}"

# 📌 8️⃣ **處理使用者加入 Bot 時的回應**
@handler.add(FollowEvent)
def handle_follow(event):
    """使用者加入時，發送歡迎訊息並請求輸入孩子出生年月日"""
    welcome_message = """🎉 歡迎來到 **兒童語言篩檢 BOT**！
請選擇您需要的功能，輸入對應的關鍵字開始：
🔹 **篩檢** → 進行兒童語言發展篩檢
🔹 **提升** → 獲取語言發展建議
🔹 **我想治療** → 查找附近語言治療服務

⚠️ 若要進行篩檢，請輸入「篩檢」開始測驗。
⚠️ 若輸入其他內容，BOT 會重複此訊息。"""
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=welcome_message)
    )
    
# 🔹 讀取 Google Sheets 並篩選符合年齡的題目
def get_questions_by_age(months):
    """從 Google Sheets 讀取符合年齡的篩檢題目"""
    try:
        sheet_data = sheet.get_all_values()  # 讀取試算表
        questions = []  # 存放符合條件的題目

        for row in sheet_data[1:]:  # 跳過標題列
            age_range = row[0]  # 年齡區間（例如 "9-12 個月"）
            question = row[2]  # 題目內容

            # 檢查該題目是否符合目前的年齡
            if "-" in age_range:
                min_age, max_age = map(int, re.findall(r'\d+', age_range))
                if min_age <= months <= max_age:
                    questions.append(question)

        return questions if questions else None  # 若沒有符合的題目則回傳 None
    except Exception as e:
        print("❌ 讀取 Google Sheets 失敗，錯誤訊息：", e)
        return None


# 🔹 追蹤使用者狀態（模式），這裡用字典模擬（正式可用資料庫）
user_states = {}

# 🔹 定義不同模式
MODE_MAIN_MENU = "主選單"
MODE_SCREENING = "篩檢模式"
MODE_TIPS = "語言發展建議模式"
MODE_TREATMENT = "語言治療資訊模式"
MODE_TESTING = "進行篩檢"

@handler.add(MessageEvent, message=TextMessage)
@handler.add(MessageEvent, message=TextMessage)
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理使用者輸入的文字訊息"""
    user_id = event.source.user_id  # 取得使用者 ID
    user_message = event.message.text.strip()  # 去除空格

    # 🔹 檢查使用者狀態，預設為「主選單」
    if user_id not in user_states:
        user_states[user_id] = {"mode": MODE_MAIN_MENU}

    user_mode = user_states[user_id]["mode"]  # 取得使用者目前模式

    # 🔹 返回主選單
    if user_message == "返回":
        user_states[user_id] = {"mode": MODE_MAIN_MENU}
        response_text = "✅ 已返回主選單。\n\n請選擇功能：\n- 「篩檢」開始語言篩檢\n- 「提升」獲取語言發展建議\n- 「我想治療」獲取語言治療資源"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

    # 🔹 測驗模式（逐題篩檢）
    if user_mode == MODE_TESTING:
        state = user_states[user_id]
        questions = state["questions"]
        current_index = state["current_index"]
        score = state["score"]

        if current_index >= len(questions):  # 篩檢完成
            response_text = f"篩檢結束！\n您的孩子在測驗中的總得分為：{score} 分。\n\n請記住，測驗結果僅供參考，若有疑問請聯絡語言治療師。\n\n輸入「返回」回到主選單。"
            user_states[user_id] = {"mode": MODE_MAIN_MENU}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return

        # 讀取該題目的「通過標準」和「提示」
        current_question = questions[current_index]
        pass_criteria = sheet.cell(current_index + 2, 6).value  # Google Sheets 第 F 欄（通過標準）
        hint = sheet.cell(current_index + 2, 5).value  # Google Sheets 第 E 欄（提示）

        # 讓 GPT 判斷回應是否符合標準
        gpt_prompt = f"根據以下的通過標準，請判斷使用者的回答是否符合標準。\n\n題目：{current_question}\n通過標準：{pass_criteria}\n使用者回答：{user_message}\n請回覆「符合」、「不符合」或「不清楚」。"
        gpt_response = chat_with_gpt(gpt_prompt)

        if "符合" in gpt_response:
            score += 1
            user_states[user_id]["score"] = score
            move_to_next_question = True
        elif "不符合" in gpt_response:
            move_to_next_question = True
        else:  # 回答不清楚
            gpt_hint_prompt = f"請基於以下提示，用簡單易懂的語言重新表達：{hint}"
            hint_response = chat_with_gpt(gpt_hint_prompt)
            response_text = f"⚠️ 回答不明確，請再試一次。\n提示：{hint_response}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
            return  # 不進入下一題，讓使用者再回答一次

        # 進入下一題
        current_index += 1
        if current_index < len(questions):
            next_question = questions[current_index]
            response_text = f"第 {current_index + 1} 題：{next_question}\n\n輸入「返回」可中途退出篩檢。"
            user_states[user_id]["current_index"] = current_index
        else:
            response_text = f"篩檢完成！您的總得分：{score} 分。\n\n輸入「返回」回到主選單。"
            user_states[user_id] = {"mode": MODE_MAIN_MENU}

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response_text))
        return

# 📌 🔟 **啟動 Flask 應用**
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
