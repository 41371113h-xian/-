from flask import Flask, request, jsonify, render_template
import requests
import os
from dotenv import load_dotenv

# 引入 Google GenAI 相關函式庫
from google import genai
from google.genai.errors import APIError

# 加載 .env 檔案中的環境變數
load_dotenv()

app = Flask(__name__)

# --- 1. 從環境變數中獲取 API Key ---
AUDDIO_API_KEY = os.getenv("AUDDIO_API_KEY", "3519b325d66d158312f4677cc81f5d2e")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")# 獲取 Gemini API Key

# 檢查 Gemini Key 是否存在
if not GEMINI_API_KEY:
    print("⚠️ 錯誤：未在 .env 檔案中找到 GEMINI_API_KEY，將無法使用 AI 查詢歌詞。")
    # 可以選擇在此處退出或使用一個預設值，但建議要求使用者配置
    
# --- 2. 初始化 Gemini Client ---
try:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    print(f"⚠️ 錯誤：初始化 Gemini 客戶端失敗。{e}")
    gemini_client = None


# --- 3. 新增一個函式來呼叫 Gemini API 查詢資訊 ---
def get_song_info_from_gemini(title, artist):
    """使用 Gemini 查詢歌詞和歌手資訊"""
    if not gemini_client:
        return {"lyrics": "AI 服務未啟動。", "artist_info": "AI 服務未啟動。"}

    # 構造一個清晰且具體的 Prompt
    prompt = f"""
    請針對這首歌：
    歌曲名稱: "{title}"
    歌手: "{artist}"
    
    執行以下兩個任務：
    1. **歌詞 (Lyrics)**: 提供這首歌的完整歌詞。如果無法提供完整歌詞，請提供至少兩段，並註明「部分歌詞」。
    2. **歌手簡介 (Artist Info)**: 簡要介紹歌手 "{artist}" 的主要風格、重要成就，長度控制在 100 字以內。
    
    請以一個 JSON 格式回傳結果，確保回傳內容是純 JSON，且可以被 Python 的 json.loads 函式解析。格式如下：
    {{
      "lyrics": "這裡放歌詞內容...",
      "artist_info": "這裡放歌手簡介..."
    }}
    """
    
    try:
        # 呼叫 Gemini 模型
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash', # 推薦使用快速且強大的 flash 模型
            contents=prompt
        )
        
        # 嘗試解析 AI 回傳的 JSON 字串
        import json
        # 由於 AI 回傳的內容可能有多餘的 Markdown 格式 (如 ```json ... ```)，需要去除
        cleaned_text = response.text.strip().lstrip('```json').rstrip('```')
        
        return json.loads(cleaned_text)
        
    except APIError as e:
        print(f"Gemini API 呼叫錯誤: {e}")
        return {"lyrics": "Gemini API 呼叫失敗。", "artist_info": f"Gemini API 呼叫失敗。錯誤：{e}"}
    except json.JSONDecodeError:
        print(f"無法解析 Gemini 回傳的 JSON：{response.text}")
        return {"lyrics": "AI 回傳格式錯誤。", "artist_info": "AI 回傳格式錯誤。"}
    except Exception as e:
        print(f"Gemini 查詢未知錯誤: {e}")
        return {"lyrics": "未知錯誤。", "artist_info": "未知錯誤。"}

# --- 4. 修改 recognize 路由，加入 Gemini 查詢邏輯 ---
@app.route('/')
def index():
    """渲染前端 HTML 頁面"""
    return render_template('index.html')

@app.route('/recognize', methods=['POST'])
def recognize_endpoint():
    """處理前端發送的音樂檔案並呼叫 Audd.io & Gemini API"""
    # ... (Audd.io 檔案檢查與 API 呼叫部分保持不變) ...
    if 'audio_file' not in request.files:
        return jsonify({"status": "error", "message": "未找到音訊檔案。"}), 400

    audio_file = request.files['audio_file']
    url = "https://api.audd.io/"
    
    files = {
        'file': (audio_file.filename, audio_file.read(), audio_file.mimetype)
    }
    data = {
        'api_token': AUDDIO_API_KEY, # 注意：這裡要用 AUDDIO_API_KEY
        'return': 'spotify,apple_music,youtube,deezer'
    }

    try:
        # 1. 呼叫 Audd.io 辨識音樂
        response = requests.post(url, data=data, files=files)
        response.raise_for_status()
        result = response.json()
        
        # ... (Audd.io 錯誤處理部分保持不變) ...
        if result.get("status") == "error":
            error_info = result.get("error", {})
            error_message = error_info.get("error_message", "Audd.io 回傳了未知的錯誤訊息。")
            return jsonify({
                "status": "fail", 
                "message": f"服務錯誤 ({error_info.get('error_code', 'N/A')})：{error_message}"
            }), 200
        
        if not result.get("result"):
            # 如果 Audd.io 辨識失敗，直接回傳結果
            return jsonify({
                "status": "fail", 
                "message": "無法辨識：成功連線至 Audd.io，但無法在資料庫中找到匹配的音樂。"
            }), 200

        r = result["result"]
        title = r.get('title')
        artist = r.get('artist')
        
        # --- 2. 呼叫 Gemini 查詢歌詞和歌手資訊 ---
        gemini_data = get_song_info_from_gemini(title, artist)
        
        # 3. 準備最終要傳回給前端的結構化數據 (整合 Audd.io 和 Gemini 結果)
        links = {}
        if r.get("spotify"):
            links["Spotify"] = r['spotify']['external_urls']['spotify']
        if r.get("youtube"):
            links["YouTube Music"] = r['youtube']['url']
        if r.get("apple_music"):
            links["Apple Music"] = r['apple_music']['url']
        if r.get("deezer"):
            links["Deezer"] = r['deezer']['link']

        return jsonify({
            "status": "success",
            "title": title,
            "artist": artist,
            "album": r.get('album'),
            "links": links,
            # 新增 Gemini 查詢到的結果
            "lyrics": gemini_data.get("lyrics", "未能獲取歌詞。"),
            "artist_info": gemini_data.get("artist_info", "未能獲取歌手簡介。")
        }), 200

    except requests.exceptions.HTTPError as e:
        return jsonify({"status": "error", "message": f"HTTP 連線錯誤：{e.response.status_code}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"後端未知錯誤：{str(e)}"}), 500

if __name__ == '__main__':
    # 確保您在專案目錄中創建了一個名為 'templates' 的資料夾
    # 並將 index.html 放在該資料夾內
    app.run(debug=True)