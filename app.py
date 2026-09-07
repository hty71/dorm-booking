import os
import csv
import io
from io import StringIO
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, make_response, Response
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import DictCursor

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

DATABASE_URL = "postgresql://neondb_owner:npg_f4ysNWhJ9AHR@ep-patient-hat-aoqiwbl5.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"

def get_db_connection():
    """建立並回傳 PostgreSQL 資料庫連線"""
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn

def init_db():
    """初始化雲端資料庫與資料表結構"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 建立開放時段資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            id SERIAL PRIMARY KEY,
            time_str TEXT,
            max_limit INTEGER,
            area TEXT,
            UNIQUE(time_str, area)
        )
    """)
    
    # 2. 建立學生預約紀錄資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
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

    # 自動升級：為 records 表檢查並補上 status 欄位
    cursor.execute("""
        DO $$ 
        BEGIN 
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='records' AND column_name='status'
            ) THEN 
                ALTER TABLE records ADD COLUMN status TEXT DEFAULT '未檢查'; 
            END IF; 
        END $$;
    """)

    # 3. 建立離宿注意事項/公告資料表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            area TEXT PRIMARY KEY,
            content TEXT
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()

init_db()

# ----------------- 🎯 前台學生預約路由 -----------------

@app.route("/")
def index():
    """預約首頁"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT time_str, max_limit, area FROM slots ORDER BY time_str ASC")
    slots_data = cursor.fetchall()
    
    cursor.execute("SELECT area, time1, time2, time3 FROM records")
    records = cursor.fetchall()
    
    slot_counts = {}
    for r in records:
        area_val = r[0]
        for t in [r[1], r[2], r[3]]:
            if t:
                key = f"{area_val}_{t}"
                slot_counts[key] = slot_counts.get(key, 0) + 1
                
    cursor.close()
    conn.close()
    return render_template("index.html", slots_data=slots_data, slot_counts=slot_counts)

@app.route("/get_announcement")
def get_announcement():
    """API: 取得特定樓層的離宿注意事項"""
    area = request.args.get("area", "").strip()
    if not area:
        return jsonify({"content": ""})
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM announcements WHERE area = %s", (area,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        default_text = "1. 請確實清空個人物品與寢室垃圾。\n2. 離宿前請將個人負責打掃空間清理乾淨。\n3. 請於預約時段準時於寢室等候幹部檢查。"
        content = row[0] if row and row[0] else default_text
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"content": "", "error": str(e)})

@app.route("/get_occupied_beds")
def get_occupied_beds():
    """API: 取得已被預約的床位或打掃負責區域"""
    area = request.args.get("area", "").strip()
    room_no = request.args.get("room_no", "").strip()
    
    if not area:
        return jsonify({"occupied": [], "occupied_jobs": []})
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if room_no:
            cursor.execute("SELECT job FROM records WHERE area = %s AND student_id LIKE %s", (area, f"{room_no}%"))
            raw_jobs = [r[0] for r in cursor.fetchall()]
            
            occupied_jobs = []
            for job_str in raw_jobs:
                if job_str:
                    parts = [p.strip() for p in job_str.split("+")]
                    occupied_jobs.extend(parts)
                    
            cursor.close()
            conn.close()
            return jsonify({"occupied": [], "occupied_jobs": occupied_jobs})
        else:
            cursor.execute("SELECT student_id FROM records WHERE area = %s", (area,))
            occupied_beds = [r[0] for r in cursor.fetchall()]
            cursor.close()
            conn.close()
            return jsonify({"occupied": occupied_beds, "occupied_jobs": []})
            
    except Exception as e:
        return jsonify({"occupied": [], "occupied_jobs": [], "error": str(e)})

@app.route("/submit", methods=["POST"])
def submit():
    """處理學生預約表單送出"""
    data = request.get_json()
    area = data.get("area")
    student_id = data.get("student_id")
    name = data.get("name")
    job = data.get("job")
    times = data.get("times", [])
    note = data.get("note", "")

    if not area or not student_id or not name or not job or len(times) != 3:
        return jsonify({"status": "error", "message": "❌ 資料填寫不完整，請重新確認！"})

    dates = []
    for t in times:
        if not t:
            continue
        date_part = t.strip().split()[0]
        dates.append(date_part)

    if len(set(dates)) < 3:
        return jsonify({"status": "error", "message": "❌ 規定：優先時段 1、2、3 必須分屬不同天，不可選擇同一天的時段！"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO records (student_id, name, job, time1, time2, time3, note, area, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '未檢查')
        """, (student_id, name, job, times[0], times[1], times[2], note, area))
        
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": f"🎉 預約成功！\n同學 {name}（床位 {student_id}）已完成登記。"})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"status": "error", "message": "❌ 預約失敗！該房號床位已經被登記過了。"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"錯誤: {str(e)}"})

# ----------------- 👑 後台管理員路由 -----------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """後台登入"""
    if request.method == "POST":
        area = request.form.get("area", "").strip()
        password = request.form.get("password", "").strip()
        
        floor_digits = "".join([char for char in area if char.isdigit()])
        expected_floor_password = floor_digits * 3 if floor_digits else ""
        
        if (password == "admin123") or (expected_floor_password and password == expected_floor_password):
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
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    
    cursor.execute("SELECT time_str, max_limit, area FROM slots ORDER BY time_str ASC")
    slots_data = [list(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT id, student_id, name, job, time1, time2, time3, note, COALESCE(status, '未檢查') as status
        FROM records 
        WHERE area = %s 
        ORDER BY student_id ASC
    """, (current_admin_area,))
    records = cursor.fetchall()
    
    cursor.execute("SELECT area, time1, time2, time3 FROM records")
    all_records_for_count = cursor.fetchall()
    slot_counts = {}
    for r in all_records_for_count:
        area_val = r["area"]
        for t in [r["time1"], r["time2"], r["time3"]]:
            if t:
                key = f"{area_val}_{t}"
                slot_counts[key] = slot_counts.get(key, 0) + 1

    cursor.execute("SELECT content FROM announcements WHERE area = %s", (current_admin_area,))
    ann_row = cursor.fetchone()
    default_text = "1. 請確實清空個人物品與寢室垃圾。\n2. 離宿前請將個人負責打掃空間清理乾淨。\n3. 請於預約時段準時於寢室等候幹部檢查。"
    announcement_content = ann_row["content"] if ann_row and ann_row["content"] else default_text

    # 聚合行事曆資料：按開放時段整理出有哪些同學預約
    schedule_data = {}
    for slot in slots_data:
        if slot[2] == current_admin_area:
            schedule_data[slot[0]] = []

    for r in records:
        student_info = {
            "student_id": r["student_id"],
            "name": r["name"],
            "job": r["job"],
            "status": r["status"]
        }
        for idx, t in enumerate([r["time1"], r["time2"], r["time3"]], start=1):
            if t in schedule_data:
                schedule_data[t].append({**student_info, "priority": idx})
                
    cursor.close()
    conn.close()
    return render_template(
        "admin.html", 
        slots_data=slots_data, 
        slot_counts=slot_counts, 
        records=records, 
        announcement_content=announcement_content,
        schedule_data=schedule_data
    )

@app.route("/admin/update_status", methods=["POST"])
def update_status():
    """後台功能：即時更新檢查狀態"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "權限不足！"})
        
    data = request.get_json()
    student_id = data.get("student_id")
    new_status = data.get("status")
    current_admin_area = session.get("admin_area")

    if not student_id or not new_status:
        return jsonify({"status": "error", "message": "參數不完整！"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE records 
            SET status = %s 
            WHERE area = %s AND student_id = %s
        """, (new_status, current_admin_area, student_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": f"狀態已更新為：{new_status}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/admin/update_announcement", methods=["POST"])
def update_announcement():
    """後台功能：儲存/更新當前樓層的離宿注意事項"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "權限不足！"})
        
    data = request.get_json()
    content = data.get("content", "").strip()
    current_admin_area = session.get("admin_area")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO announcements (area, content)
            VALUES (%s, %s)
            ON CONFLICT (area) 
            DO UPDATE SET content = EXCLUDED.content
        """, (current_admin_area, content))
        
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "✅ 離宿注意事項已成功儲存！前台已即時套用。"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"系統錯誤: {str(e)}"})

@app.route("/admin/export/redirect")
def admin_export_redirect():
    """【功能】一鍵跳轉到樓長專屬的 Google 試算表"""
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
        
    current_admin_area = session.get("admin_area")
    sheets_urls = {
        "國際3樓": "https://docs.google.com/spreadsheets/d/1f4Av2caVDeo7wcC5RFooKhoe5OzLSD0PV3YTerKaQpg/edit?usp=sharing",
        "國際5樓": "https://docs.google.com/spreadsheets/d/1oYne8tMUBT86GKVxwzevtiYJvcW7F_AxnUIN5Ancy4M/edit?usp=sharing",
        "國際6樓": "https://docs.google.com/spreadsheets/d/1a7Vy0xrVqDUINTbeSOUweAjvILHfOZJJ_tatjNK0L78/edit?usp=sharing",
        "國際7樓": "https://docs.google.com/spreadsheets/d/19v8gNR_l_pyHnkO4zpGp9cyJOeNkXEhSw5PI-75i6Wo/edit?usp=sharing",
        "國際8樓": "https://docs.google.com/spreadsheets/d/19Cda8WBUhtgCFXu8GdA6B-ovPNSZimOXp5CAGmsKQ40/edit?usp=sharing",
    }
    target_url = sheets_urls.get(current_admin_area, "https://docs.google.com/spreadsheets")
    return redirect(target_url)

@app.route("/admin/export/csv")
def export_csv():
    """【隱藏 API 接口】供 Google 試算表自動調用更新資料"""
    token = request.args.get("token", "")
    if token != "admin123":
        return "<h3>❌ 驗證失敗，無權限存取此資料！</h3>", 403

    target_area = request.args.get("area", "").strip()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if target_area:
            cursor.execute("""
                SELECT area, student_id, name, job, time1, time2, time3, note, COALESCE(status, '未檢查') 
                FROM records 
                WHERE area = %s
                ORDER BY student_id ASC
            """, (target_area,))
        else:
            cursor.execute("""
                SELECT area, student_id, name, job, time1, time2, time3, note, COALESCE(status, '未檢查') 
                FROM records 
                ORDER BY area ASC, student_id ASC
            """)
            
        records = cursor.fetchall()
        cursor.close()
        conn.close()

        si = StringIO()
        cw = csv.writer(si)
        cw.writerow(["管理樓層", "房號床位", "學生姓名", "負責工作", "優先時段1", "優先時段2", "優先時段3", "備註事項", "檢查進度"])
        
        for r in records:
            cw.writerow([
                r[0], r[1], r[2], r[3],
                f" {r[4]}" if r[4] else "",
                f" {r[5]}" if r[5] else "",
                f" {r[6]}" if r[6] else "",
                r[7], r[8]
            ])

        csv_data = "\ufeff" + si.getvalue()
        floor_digits = "".join([char for char in target_area if char.isdigit()])
        safe_filename = f"dorm_records_floor_{floor_digits}.csv" if floor_digits else "dorm_records_all.csv"
        
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={safe_filename}"}
        )
    except Exception as e:
        return f"匯出失敗: {str(e)}", 500

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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO slots (time_str, max_limit, area) VALUES (%s, %s, %s)
        """, (time_str, max_limit, current_admin_area))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": f"✅ 成功上架時段：【{time_str}】！"})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"status": "error", "message": "❌ 該時段已經存在，請勿重複新增！"})

@app.route("/admin/batch_add_slots", methods=["POST"])
def batch_add_slots():
    """後台功能：批量自動生成並新增開放時段範圍"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "權限不足！"})
        
    data = request.get_json()
    start_date_str = data.get("start_date", "").strip()
    start_time_str = data.get("start_time", "").strip()
    end_time_str = data.get("end_time", "").strip()
    interval_mins = int(data.get("interval", 30))
    max_limit = int(data.get("max_limit", 3))
    current_admin_area = session.get("admin_area")

    if not start_date_str or not start_time_str or not end_time_str:
        return jsonify({"status": "error", "message": "❌ 請完整填寫日期與時間範圍！"})

    try:
        start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{start_date_str} {end_time_str}", "%Y-%m-%d %H:%M")
        
        if start_dt >= end_dt:
            return jsonify({"status": "error", "message": "❌ 開始時間不能晚於或等於結束時間！"})

        conn = get_db_connection()
        cursor = conn.cursor()
        
        curr_dt = start_dt
        success_count = 0
        skip_count = 0

        while curr_dt <= end_dt:
            formatted_time = f"{curr_dt.month}/{curr_dt.day} {curr_dt.strftime('%H:%M')}"
            try:
                cursor.execute("""
                    INSERT INTO slots (time_str, max_limit, area) VALUES (%s, %s, %s)
                """, (formatted_time, max_limit, current_admin_area))
                success_count += 1
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                skip_count += 1
                
            curr_dt += timedelta(minutes=interval_mins)

        conn.commit()
        cursor.close()
        conn.close()

        msg = f"🎉 批量上架成功！共成功新增 {success_count} 個時段。"
        if skip_count > 0:
            msg += f"（有 {skip_count} 個重複時段已自動跳過）"
            
        return jsonify({"status": "success", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "message": f"系統錯誤: {str(e)}"})

@app.route("/admin/delete_slots_batch", methods=["POST"])
def delete_slots_batch():
    """後台功能：一鍵刪除勾選的多個時段"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "權限不足！"})
        
    data = request.get_json()
    times_to_delete = data.get("times", [])
    current_admin_area = session.get("admin_area")

    if not times_to_delete:
        return jsonify({"status": "error", "message": "❌ 沒有選擇任何時段！"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM slots 
            WHERE area = %s AND time_str = ANY(%s)
        """, (current_admin_area, times_to_delete))
        
        conn.commit()
        deleted_count = cursor.rowcount
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": f"🗑️ 成功批量刪除 {deleted_count} 個開放時段！"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"系統錯誤: {str(e)}"})

@app.route("/admin/delete_slot", methods=["POST"])
def delete_slot():
    """後台功能：單筆刪除開放時段"""
    if not session.get("admin_logged_in"):
        return jsonify({"status": "error", "message": "權限不足！"})
        
    data = request.get_json()
    time_str = data.get("time_str", "").strip()
    current_admin_area = session.get("admin_area")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM slots WHERE time_str = %s AND area = %s", (time_str, current_admin_area))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"status": "success", "message": f"🗑️ 已成功移除時段：【{time_str}】。"})

@app.route("/admin/delete_student", methods=["POST"])
def delete_student():
    """後台功能：刪除單一學生的預約紀錄"""
    if not session.get("admin_logged_in"): 
        return jsonify({"status": "error", "message": "權限不足，請重新登入！"})
        
    current_admin_area = session.get("admin_area")
    data = request.get_json()
    bed_no = data.get("student_id", "").strip()
    
    if not bed_no: 
        return jsonify({"status": "error", "message": "缺少必要的房號床位參數！"})
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM records WHERE area = %s AND student_id = %s", (current_admin_area, bed_no))
        conn.commit()
        cursor.close()
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
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM records WHERE area = %s", (current_admin_area,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"status": "success", "message": f"💥 已全數清空【{current_admin_area}】的所有學生登記紀錄！"})

@app.route("/admin/logout")
def admin_logout():
    """後台登出"""
    session.clear()
    return redirect(url_for("admin_login"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)