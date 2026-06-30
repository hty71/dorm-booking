import os
import sqlite3
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)
app.secret_key = "dorm_secret_key_change_this_in_production"

# 🚀 修正：為了配合 Render 免費版不支援 Disks 的限制，直接將資料庫存在專案當前目錄下
DB_PATH = "database.db"

# 初始化資料庫（若檔案不存在會自動建立，並補上必要的欄位與測試時段）
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 建立預約紀錄表 (records)
    # 🚀 修正：將原本誤植的 TEXT NOT EXISTS 修正為正規的 TEXT NOT NULL
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area TEXT NOT NULL,
            student_id TEXT UNIQUE,
            name TEXT,
            job TEXT,
            time1 TEXT,
            time2 TEXT,
            time3 TEXT,
            note TEXT
        )
    """)
    
    # 建立開放時段設定表 (slots)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time_str TEXT,
            max_limit INTEGER,
            area TEXT,
            UNIQUE(time_str, area)
        )
    """)
    
    # 為了避免初次運行時完全沒時段可測，幫各區預塞一些 6/8, 6/9 的測試時段
    cursor.execute("SELECT COUNT(*) FROM slots")
    if cursor.fetchone()[0] == 0:
        test_areas = ["國際3樓", "國際5樓", "國際6樓", "國際7樓", "國際8樓"]
        test_times = [
            "6/8 13:00", "6/8 13:30", "6/8 14:00", "6/8 14:30", 
            "6/9 09:00", "6/9 09:30", "6/9 10:00", "6/9 10:30"
        ]
        for a in test_areas:
            for t in test_times:
                cursor.execute("INSERT OR IGNORE INTO slots (time_str, max_limit, area) VALUES (?, ?, ?)", (t, 3, a))
                
    conn.commit()
    conn.close()

# 啟動時跑初始化
init_db()

# 輔助函式：計算目前各時段已經被預約的人數
def get_slot_counts():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT area, time1, time2, time3 FROM records")
    rows = cursor.fetchall()
    conn.close()
    
    counts = {}
    for area, t1, t2, t3 in rows:
        for t in [t1, t2, t3]:
            if t:
                key = f"{area}_{t}"
                counts[key] = counts.get(key, 0) + 1
    return counts


# ==========================================
# 🙋‍♂️ 學生填寫端路由
# ==========================================

@app.route("/")
def index():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 撈出所有時段配置，並按照時間排序
    cursor.execute("SELECT time_str, max_limit, area, time_str FROM slots ORDER BY id ASC")
    slots_data = cursor.fetchall()
    conn.close()
    
    slot_counts = get_slot_counts()
    return render_template("index.html", slots_data=slots_data, slot_counts=slot_counts)

@app.route("/get_occupied_beds")
def get_occupied_beds():
    area = request.args.get("area", "").strip()
    room_no = request.args.get("room_no", "").strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if room_no:
        # 如果有傳房號，代表是要查該房內「有哪些打掃工作已經被挑走了」
        cursor.execute("SELECT job FROM records WHERE area = ? AND student_id LIKE ?", (area, f"{room_no}%"))
        occupied_jobs = [r[0] for r in cursor.fetchall()]
        conn.close()
        return jsonify({"occupied_jobs": occupied_jobs})
    else:
        # 否則就是純查該樓層「有哪些床位代碼已經被註冊了」
        cursor.execute("SELECT student_id FROM records WHERE area = ?")
        occupied_beds = [r[0] for r in cursor.fetchall()]
        conn.close()
        return jsonify({"occupied": occupied_beds})

@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json()
    area = data.get("area")
    student_id = data.get("student_id", "").strip().upper()
    name = data.get("name", "").strip()
    job = data.get("job")
    times = data.get("times", [])
    note = data.get("note", "").strip()
    
    if not (area and student_id and name and job and len(times) == 3):
        return jsonify({"status": "error", "message": "❌ 欄位填寫不完整或未選滿 3 個時段！"})
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 檢查該床位是否已被捷足先登
    cursor.execute("SELECT id FROM records WHERE area = ? AND student_id = ?", (area, student_id))
    if cursor.fetchone():
        conn.close()
        return jsonify({"status": "error", "message": f"❌ 預約失敗！【{student_id}】這個床位已經被其他人登記過了！"})
        
    # 檢查同房間內該打掃工作是否已被搶走
    room_no = student_id[:3]
    cursor.execute("SELECT id FROM records WHERE area = ? AND student_id LIKE ? AND job = ?", (area, f"{room_no}%", job))
    if cursor.fetchone():
        conn.close()
        return jsonify({"status": "error", "message": f"❌ 預約失敗！該房的【{job}】工作已被同房室友選走了！"})
        
    # 檢查選擇的三個時段是否還有餘額
    slot_counts = get_slot_counts()
    cursor.execute("SELECT time_str, max_limit FROM slots WHERE area = ?", (area,))
    limits = {r[0]: r[1] for r in cursor.fetchall()}
    
    for t in times:
        current_booked = slot_counts.get(f"{area}_{t}", 0)
        max_allow = limits.get(t, 0)
        if current_booked >= max_allow:
            conn.close()
            return jsonify({"status": "error", "message": f"❌ 殘念！時段【{t}】剛剛好額滿了，請重選其他時段。"})
            
    # 安全過關，寫入資料庫
    try:
        cursor.execute("""
            INSERT INTO records (area, student_id, name, job, time1, time2, time3, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (area, student_id, name, job, times[0], times[1], times[2], note))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "🎉 恭喜你！三段離宿檢查時間已成功預約儲存！"})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "error", "message": "❌ 該床位已被重複登記。"})


# ==========================================
# 👑 管理員後台路由
# ==========================================

# 密碼對照表
PASSWORDS = {
    "333": "國際3樓",
    "555": "國際5樓",
    "666": "國際6樓",
    "777": "國際7樓",
    "888": "國際8樓"
}

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pwd = request.form.get("password", "").strip()
        if pwd in PASSWORDS:
            session["admin_logged_in"] = True
            session["admin_area"] = PASSWORDS[pwd]
            return redirect(url_for("admin_dashboard"))
        else:
            return render_template("admin_login.html", error="❌ 密碼錯誤，請重新輸入！")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
        
    current_admin_area = session.get("admin_area")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    # 撈出該層管理員管轄的學生名冊
    cursor.execute("SELECT * FROM records WHERE area = ? ORDER BY student_id ASC", (current_admin_area,))
    records = cursor.fetchall()
    
    # 撈出全台時段
    cursor.execute("SELECT id, time_str, max_limit, area, time_str FROM slots ORDER BY id ASC")
    raw_slots = cursor.fetchall()
    conn.close()
    
    slot_counts = get_slot_counts()
    return render_template("admin.html", records=records, slots_data=raw_slots, slot_counts=slot_counts)

@app.route("/admin/add_slot", methods=["POST"])
def add_slot():
    if not session.get("admin_logged_in"): return jsonify({"status": "error", "message": "未登入"})
    
    current_admin_area = session.get("admin_area")
    data = request.get_json()
    time_str = data.get("time_str", "").strip()
    max_limit = int(data.get("max_limit", 3))
    
    if not time_str: return jsonify({"status": "error", "message": "時間不可為空"})
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO slots (time_str, max_limit, area) VALUES (?, ?, ?)", (time_str, max_limit, current_admin_area))
        conn.commit()
        msg = f"成功為【{current_admin_area}】新增時段：{time_str}"
    except sqlite3.IntegrityError:
        msg = "❌ 該時段已存在，不可重複建立！"
    conn.close()
    return jsonify({"message": msg})

@app.route("/admin/delete_slot", methods=["POST"])
def delete_slot():
    if not session.get("admin_logged_in"): return jsonify({"status": "error", "message": "未登入"})
    
    current_admin_area = session.get("admin_area")
    data = request.get_json()
    time_str = data.get("time_str", "").strip()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM slots WHERE area = ? AND time_str = ?", (current_admin_area, time_str))
    conn.commit()
    conn.close()
    return jsonify({"message": f"已成功刪除時段：{time_str}"})

@app.route("/admin/delete_student", methods=["POST"])
def delete_student():
    if not session.get("admin_logged_in"): 
        return jsonify({"status": "error", "message": "權限不足"})
        
    current_admin_area = session.get("admin_area")
    data = request.get_json()
    bed_no = data.get("student_id", "").strip()
    
    if not bed_no: 
        return jsonify({"status": "error", "message": "缺少房號床號參數"})
        
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM records WHERE area = ? AND student_id = ?", (current_admin_area, bed_no))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"成功刪除【{bed_no}】的預約紀錄！床位與打掃工作已重新釋放。"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/admin/clear", methods=["POST"])
def clear_database():
    if not session.get("admin_logged_in"): return jsonify({"status": "error", "message": "未登入"})
    current_admin_area = session.get("admin_area")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM records WHERE area = ?", (current_admin_area,))
    conn.commit()
    conn.close()
    return jsonify({"message": f"💥 【{current_admin_area}】的所有學生預約紀錄已成功全數清空！"})


# ==========================================
# 🏁 啟動引擎
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)