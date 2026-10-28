# -*- coding: utf-8 -*-
"""横火食堂：管理员自定义菜品（SQLite + Flask Blueprint）。"""
import json
import os
from flask import Blueprint, jsonify, request, session, send_from_directory
import db

bp = Blueprint("canteen_management", __name__)
MEALS = ("breakfast", "lunch", "dinner")

def connect():
    conn = db.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS canteen_dishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            category TEXT NOT NULL,
            emoji TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            meals TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

def admin_only():
    return session.get("role") == "admin"

def data_row(row):
    return {
        "id": row["id"], "name": row["name"],
        "price": row["price_cents"] / 100,
        "category": row["category"], "emoji": row["emoji"],
        "description": row["description"],
        "meals": json.loads(row["meals"]),
        "active": bool(row["active"])
    }

def validate(data):
    name = str(data.get("name") or "").strip()
    category = str(data.get("category") or "").strip()
    emoji = str(data.get("emoji") or "🍽️").strip()
    description = str(data.get("description") or "").strip()
    meals = data.get("meals")
    if not (1 <= len(name) <= 60): raise ValueError("菜名应为1—60字")
    if not (1 <= len(category) <= 30): raise ValueError("分类应为1—30字")
    if len(emoji) > 16: raise ValueError("图标过长")
    if len(description) > 160: raise ValueError("描述不能超过160字")
    if not isinstance(meals, list) or not meals or len(meals) != len(set(meals)) or any(m not in MEALS for m in meals):
        raise ValueError("请至少选择一个餐次")
    try:
        cents = round(float(data.get("price")) * 100)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("价格格式错误")
    if cents < 0 or cents > 100000: raise ValueError("价格应在0—1000元之间")
    return name, cents, category, emoji or "🍽️", description, json.dumps(meals), int(bool(data.get("active", True)))

@bp.get("/admin/canteen")
def page():
    if not admin_only():
        from flask import redirect
        return redirect("/admin/login")
    return send_from_directory(os.path.join(os.path.dirname(__file__), "templates"), "admin_canteen.html")

@bp.get("/api/canteen/dishes")
def public_dishes():
    conn = connect()
    rows = conn.execute("SELECT * FROM canteen_dishes WHERE active=1 ORDER BY id").fetchall()
    conn.close()
    return jsonify(success=True, data=[data_row(r) for r in rows])

@bp.get("/api/admin/canteen/dishes")
def list_dishes():
    if not admin_only(): return jsonify(success=False,msg="管理员未登录"), 401
    conn = connect()
    rows = conn.execute("SELECT * FROM canteen_dishes ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify(success=True, data=[data_row(r) for r in rows])

@bp.post("/api/admin/canteen/dishes")
def add_dish():
    if not admin_only(): return jsonify(success=False,msg="管理员未登录"), 401
    try: values = validate(request.get_json(silent=True) or {})
    except ValueError as e: return jsonify(success=False,msg=str(e)), 400
    conn = connect()
    cur = conn.execute("""INSERT INTO canteen_dishes
        (name,price_cents,category,emoji,description,meals,active)
        VALUES (?,?,?,?,?,?,?)""", values)
    conn.commit()
    dish_id = cur.lastrowid
    conn.close()
    return jsonify(success=True,id=dish_id)

@bp.put("/api/admin/canteen/dishes/<int:dish_id>")
def edit_dish(dish_id):
    if not admin_only(): return jsonify(success=False,msg="管理员未登录"), 401
    try: values = validate(request.get_json(silent=True) or {})
    except ValueError as e: return jsonify(success=False,msg=str(e)), 400
    conn = connect()
    cur = conn.execute("""UPDATE canteen_dishes SET
        name=?,price_cents=?,category=?,emoji=?,description=?,meals=?,active=?
        WHERE id=?""", (*values,dish_id))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return jsonify(success=bool(changed),msg="已保存" if changed else "菜品不存在"), (200 if changed else 404)

@bp.delete("/api/admin/canteen/dishes/<int:dish_id>")
def delete_dish(dish_id):
    if not admin_only(): return jsonify(success=False,msg="管理员未登录"), 401
    conn = connect()
    cur = conn.execute("DELETE FROM canteen_dishes WHERE id=?", (dish_id,))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return jsonify(success=bool(changed),msg="已删除" if changed else "菜品不存在"), (200 if changed else 404)

def install(app):
    app.register_blueprint(bp)

    @app.after_request
    def inject_canteen_ui(response):
        if response.status_code != 200 or not response.mimetype == "text/html":
            return response
        path = request.path
        if path not in ("/campus-card", "/admin"):
            return response
        response.direct_passthrough = False
        html = response.get_data(as_text=True)
        if path == "/campus-card" and 'src="/static/canteen_extension.js"' not in html:
            html = html.replace("</body>", '<script src="/static/canteen_extension.js"></script></body>')
        if path == "/admin" and 'href="/admin/canteen"' not in html:
            html = html.replace('<div class="adm-tabs">', '<p style="margin:12px 0"><a class="btn btn-primary" href="/admin/canteen">进入食堂菜品管理 →</a></p><div class="adm-tabs">', 1)
        response.set_data(html)
        response.headers["Cache-Control"] = "no-store"
        return response
