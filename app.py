import os
import sqlite3
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # 請替換成你專屬的 Session 密鑰

# 設定資料庫絕對路徑
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

def init_db():
    """初始化資料庫與資料表結構"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 建立開放時段資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time_str TEXT,
            max_limit INTEGER,
            area TEXT,
            UNIQUE(time_str, area)
        )
    """)
    
    # 2. 建立學生預約紀錄資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE,
            name TEXT,
            job TEXT,
            time1 TEXT,
            time2 TEXT,
            time3 TEXT,
            note TEXT,
            area TEXT
        )
    """)
    conn.commit()
    conn.close()

# 啟動時立刻初始化資料庫
init_db()

# ----------------- 🎯 前台學生預約路由 -----------------

@app.route("/")
def index():
    """預約首頁"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 撈取所有開放時段，並依照時間由早到晚自動排序
    cursor.execute("SELECT time_str, max_limit, area FROM slots ORDER BY time_str ASC")
    slots_data = cursor.fetchall()
    
    # 統計各時段目前已被預約的人數
    cursor.execute("SELECT area, time1, time2, time3 FROM records")
    records = cursor.fetchall()
    
    slot_counts = {}
    for r in records:
        area_val = r[0]
        for t in [r[1], r[2], r[3]]:
            if t:
                key = f"{area_val}_{t}"
                slot_counts[key] = slot_counts.get(key, 0) + 1
                
    conn.close()
    return render_template("index.html", slots_data=slots_data, slot_counts=slot_counts)


@app.route("/get_occupied_beds")
def get_occupied_beds():
    """API: 取得已被預約的床位或打掃負責區域"""
    area = request.args.get("area", "").strip()
    room_no = request.args.get("room_no", "").strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if room_no:
        # 查詢同寢室已被挑走的工作
        cursor.execute("SELECT job FROM records WHERE area = ? AND student_id LIKE ?", (area, f"{room_no}%"))
        occupied_jobs = [r[0] for r in cursor.fetchall()]
        conn.close()
        return jsonify({"occupied_jobs": occupied_jobs})
    else:
        # 確實補上元組參數 (area,) 確保 SQL 問號順利綁定
        cursor.execute("SELECT student_id FROM records WHERE area = ?", (area,))
        occupied_beds = [r[0] for r in cursor.fetchall()]
        conn.close()
        return jsonify({"occupied": occupied_beds})


@app.route("/submit", methods=["POST"])
def submit():
    """處理學生預約表單送出"""
    data = request.get_json()
    area = data.get("area")
    student_id = data.get("student_id")
    name = data.get("name")
    job = data.get("job")
    times = data.get("times", [])  # 包含 3 個排序好時段的陣列
    note = data.get("note", "")

    if not area or not student_id or not name or not job or len(times) != 3:
        return jsonify({"status": "error", "message": "❌ 資料填寫不完整，請重新確認！"})

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 寫入學生預約名冊
        cursor.execute("""
            INSERT INTO records (student_id, name, job, time1, time2, time3, note, area)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (student_id, name, job, times[0], times[1], times[2], note, area))
        
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"🎉 預約成功！\n同學 {name}（床位 {student_id}）已完成登記。"})
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "❌ 預約失敗！該房號床位已經被登記過了。"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"錯誤: {str(e)}"})


# ----------------- 👑 後台管理員路由 -----------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """後台登入"""
    if request.method == "POST":
        area = request.form.get("area")
        password = request.form.get("password")
        
        if (area == "國際5樓" and password == "555") or \
           (area == "國際3樓" and password == "333") or \
           (password == "admin123"):
            session["admin_logged_in"] = True
            session["admin_area"] = area
            return redirect(url_for("admin_dashboard"))
        else:
            return "<h3>❌ 密碼錯誤或分區不正確！請按上一頁重新輸入。</h3>"
            
    return """
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>管理後台登入</title>
        <div style="max-width:350px; margin:80px auto; padding:25px; border:1px solid #ddd; border-radius:8px; font-family:sans-serif;">
            <h2 style="text-align:center;">👑 樓長後台登入</h2>
            <form method="POST">
                <p>管理樓層：<br>
                <select name="area" style="width:100%; padding:8px;">
                    <option value="國際3樓">國際3樓</option>
                    <option value="國際5樓">國際5樓</option>
                    <option value="國際6樓">國際6樓</option>
                    <option value="國際7樓">國際7樓</option>
                    <option value="國際8樓">國際8樓</option>
                </select></p>
                <p>管理後台密碼：<br>
                <input type="password" name="password" required style="width:100%; padding:8px; box-sizing:border-box;"></p>
                <button type="submit" style="width:100%; padding:10px; background:#34495e; color:white; border:none; cursor:pointer; font-weight:bold;">進入後台</button>
            </form>
        </div>
    """


@app.route("/admin")
@app.route("/admin/dashboard")
def admin_dashboard():
    """管理員後台主面板"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
        
    current_admin_area = session.get("admin_area")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 時段列表加上 ORDER BY time_str ASC，由早到晚排序
    cursor.execute("SELECT id, time_str, max_limit, area FROM slots ORDER BY time_str ASC")
    slots_data = [list(row) for row in cursor.fetchall()]
    
    # 學生預約名冊加上 ORDER BY student_id ASC，讓房號（如 501A 到 512D）整齊排列
    cursor.execute("""
        SELECT id, student_id, name, job, time1, time2, time3, note 
        FROM records 
        WHERE area = ? 
        ORDER BY student_id ASC
    """, (current_admin_area,))
    records = cursor.fetchall()
    
    # 統計時段計數器
    cursor.execute("SELECT area, time1, time2, time3 FROM records")
    all_records_for_count = cursor.fetchall()
    slot_counts = {}
    for r in all_records_for_count:
        area_val = r["area"]
        for t in [r["time1"], r["time2"], r["time3"]]:
            if t:
                key = f"{area_val}_{t}"
                slot_counts[key] = slot_counts.get(key, 0) + 1
                
    conn.close()
    return render_template("admin.html", slots_data=slots_data, slot_counts=slot_counts, records=records)


@app.route("/admin/add_slot", methods=["POST"])
def add_slot():
    """後台功能：新增開放時段"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "權限不足！"})
        
    data = request.get_json()
    time_str = data.get("time_str", "").strip()
    max_limit = int(data.get("max_limit", 3))
    current_admin_area = session.get("admin_area")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO slots (time_str, max_limit, area) VALUES (?, ?, ?)
        """, (time_str, max_limit, current_admin_area))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"✅ 成功上架時段：【{time_str}】！"})
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "❌ 該時段已經存在，請勿重複新增！"})


@app.route("/admin/delete_slot", methods=["POST"])
def delete_slot():
    """後台功能：刪除開放時段"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "權限不足！"})
        
    data = request.get_json()
    time_str = data.get("time_str", "").strip()
    current_admin_area = session.get("admin_area")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM slots WHERE time_str = ? AND area = ?", (time_str, current_admin_area))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": f"🗑️ 已成功移除時段：【{time_str}】。"})


@app.route("/admin/delete_student", methods=["POST"])
def delete_student():
    """後台功能：精準單獨刪除某一學生的預約紀錄"""
    if not session.get("admin_logged_in"): 
        return jsonify({"status": "error", "message": "權限不足，請重新登入！"})
        
    current_admin_area = session.get("admin_area")
    data = request.get_json()
    bed_no = data.get("student_id", "").strip()
    
    if not bed_no: 
        return jsonify({"status": "error", "message": "缺少必要的房號床位參數！"})
        
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM records WHERE area = ? AND student_id = ?", (current_admin_area, bed_no))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"🎉 成功刪除【{bed_no}】的預約紀錄！\n該床位與打掃工作已重新釋放。"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/admin/clear", methods=["POST"])
def admin_clear():
    """後台功能：清空當前樓層所有預約紀錄"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "權限不足！"})
        
    current_admin_area = session.get("admin_area")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM records WHERE area = ?", (current_admin_area,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": f"💥 已全數清空【{current_admin_area}】的所有學生登記紀錄！"})


@app.route("/admin/logout")
def admin_logout():
    """後台登出"""
    session.clear()
    return redirect(url_for("admin_login"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)