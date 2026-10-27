# -*- coding: utf-8 -*-
"""横火高级中学 模拟高考报名系统 - 主入口"""
import os, datetime, uuid, json, secrets, io
import sqlite3
from flask import (
    Flask, request, jsonify, send_file, send_from_directory, abort, session,
    render_template_string
)
from PIL import Image, ImageDraw, ImageFont
import db
import auth

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 自动加载 .env（生产环境）----------
_ENV_PATH = os.path.join(BASE_DIR, ".env")
if os.path.isfile(_ENV_PATH):
    try:
        with open(_ENV_PATH, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _k, _v = _line.split("=", 1)
                _k = _k.strip(); _v = _v.strip().strip('"').strip("'")
                os.environ.setdefault(_k, _v)
    except Exception:
        pass

DB_PATH = db.DB_PATH
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
TICKET_DIR = os.path.join(BASE_DIR, "tickets")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TPL_DIR = os.path.join(BASE_DIR, "templates")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TICKET_DIR, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_urlsafe(32)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# HTTPS 环境下 Nginx 会传 X-Forwarded-Proto=https，下面自动生效
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FORCE_HTTPS", "").lower() in ("1", "true", "yes")

# 蓝图
app.register_blueprint(auth.bp)


# ---------- 初始化 ----------
@app.before_request
def _init():
    if not hasattr(app, "_inited"):
        db.ensure_schema()
        db.seed_admin()
        app._inited = True
    # Nginx 反代 HTTPS 时自动启用 secure cookie
    if not app.config["SESSION_COOKIE_SECURE"]:
        proto = request.headers.get("X-Forwarded-Proto", "").lower()
        if proto == "https":
            app.config["SESSION_COOKIE_SECURE"] = True


# ---------- CORS ----------
@app.after_request
def _cors(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- 工具 ----------
def row_to_dict(row):
    return {k: row[k] for k in row.keys()}


# ================================================================
#  前端页面路由
# ================================================================
@app.route("/")
def index():
    """已登录直接进学校官网（档案系统），未登录跳登录页"""
    uid = session.get("uid")
    if uid:
        from flask import redirect, url_for
        return redirect("/archive")
    return send_file(os.path.join(TPL_DIR, "login.html"))


@app.route("/register")
def register_page():
    return send_file(os.path.join(TPL_DIR, "register.html"))


@app.route("/login")
def login_page():
    return send_file(os.path.join(TPL_DIR, "login.html"))


@app.route("/portal")
def portal_page():
    return send_file(os.path.join(TPL_DIR, "portal.html"))


@app.route("/gaokao")
def gaokao_page():
    return send_file(os.path.join(TPL_DIR, "gaokao.html"))


@app.route("/admin/login")
def admin_login_page():
    return send_file(os.path.join(TPL_DIR, "admin_login.html"))


@app.route("/admin")
def admin_page():
    return send_file(os.path.join(TPL_DIR, "admin.html"))


@app.route("/campus-card")
def campus_card_page():
    return send_file(os.path.join(TPL_DIR, "campus-card.html"))


@app.route("/archive")
def archive_page():
    """学生档案信息系统（原 Netlify 作品，已接入统一后端）"""
    resp = send_file(os.path.join(TPL_DIR, "archive.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/tickets/<path:filename>")
def ticket_file(filename):
    return send_from_directory(TICKET_DIR, filename)


# ================================================================
#  高考报名 API（改造版：关联 user_id）
# ================================================================
def _generate_exam_no(conn):
    year = datetime.datetime.now().strftime("%Y")
    while True:
        seq = str(uuid.uuid4().int % 1000000).zfill(6)
        no = f"HH{year}{seq}"
        if not conn.execute("SELECT 1 FROM registrations WHERE exam_no=?", (no,)).fetchone():
            return no


@app.route("/api/registration", methods=["POST"])
def create_registration():
    data = request.form.to_dict()
    photo = request.files.get("photo")
    required = ["name", "gender", "birth_date", "age", "grade_segment"]
    # 有 user_id 关联时可以不强制 id_card（后端仍保留可选）
    for f in required:
        if not data.get(f, "").strip():
            return jsonify({"success": False, "msg": f"必填项缺失：{f}"}), 400

    # 出生日期
    try:
        datetime.datetime.strptime(data["birth_date"], "%Y-%m-%d")
    except Exception:
        return jsonify({"success": False, "msg": "出生日期格式错误（应为 YYYY-MM-DD）"}), 400
    try:
        age = int(data["age"])
    except ValueError:
        return jsonify({"success": False, "msg": "年龄必须是整数"}), 400
    if not (16 <= age <= 18):
        return jsonify({"success": False, "msg": "年龄必须在 16-18 之间"}), 400

    # 关联登录用户
    uid = session.get("uid")
    user_id_val = uid if uid else None

    conn = db.get_conn()
    # 查询已有记录（按 user_id 优先，否则按 name+phone 近似）
    existed = None
    if user_id_val:
        existed = conn.execute(
            "SELECT id, exam_no FROM registrations WHERE user_id=?", (user_id_val,)
        ).fetchone()

    # 证件照
    photo_path = None
    if photo and photo.filename:
        if photo.content_length and photo.content_length > 5 * 1024 * 1024:
            conn.close()
            return jsonify({"success": False, "msg": "证件照超过 5MB"}), 400
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            conn.close()
            return jsonify({"success": False, "msg": "证件照格式不支持"}), 400
        fname = f"{uuid.uuid4().hex}{ext}"
        photo.save(os.path.join(UPLOAD_DIR, fname))
        photo_path = fname

    # 身份证号：必填，18 位校验
    id_card = data.get("id_card", "").strip()
    if not id_card:
        return jsonify({"success": False, "msg": "身份证号必填"}), 400
    if len(id_card) not in (15, 18):
        return jsonify({"success": False, "msg": "身份证号格式不正确（应为 15 或 18 位）"}), 400

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if existed:
        exam_no = existed["exam_no"]
        fields = [
            "name", "gender", "birth_date", "age", "grade_segment",
            "ethnicity", "political_status", "address", "candidate_type",
            "graduate_school", "class_name", "subject_category", "phone",
            "birth_country", "birth_province", "birth_city", "birth_county",
            "user_id",
        ]
        sets = ", ".join([f"{f}=?" for f in fields]) + ", id_card=?, updated_at=?, status=?"
        vals = (
            data.get("name", ""), data.get("gender", ""),
            data.get("birth_date", ""), age,
            data.get("grade_segment", "高三"),
            data.get("ethnicity", ""), data.get("political_status", ""),
            data.get("address", ""), data.get("candidate_type", ""),
            data.get("graduate_school", ""), data.get("class_name", ""),
            data.get("subject_category", ""), data.get("phone", ""),
            data.get("birth_country", ""), data.get("birth_province", ""),
            data.get("birth_city", ""), data.get("birth_county", ""),
            user_id_val, id_card, now, "已修改", existed["id"],
        )
        conn.execute(f"UPDATE registrations SET {sets} WHERE id=?", vals)
        if photo_path:
            conn.execute("UPDATE registrations SET photo_path=? WHERE id=?", (photo_path, existed["id"]))
        conn.commit()
        row = conn.execute("SELECT * FROM registrations WHERE id=?", (existed["id"],)).fetchone()
    else:
        exam_no = _generate_exam_no(conn)
        sql = """INSERT INTO registrations
        (exam_no, name, gender, birth_date, age, birth_country, birth_province,
         birth_city, birth_county, id_card, grade_segment, ethnicity, political_status,
         address, candidate_type, graduate_school, class_name, subject_category,
         phone, photo_path, status, created_at, updated_at, user_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        vals = (
            exam_no, data.get("name", ""), data.get("gender", ""),
            data.get("birth_date", ""), age,
            data.get("birth_country", ""), data.get("birth_province", ""),
            data.get("birth_city", ""), data.get("birth_county", ""),
            id_card, data.get("grade_segment", "高三"),
            data.get("ethnicity", ""), data.get("political_status", ""),
            data.get("address", ""), data.get("candidate_type", ""),
            data.get("graduate_school", ""), data.get("class_name", ""),
            data.get("subject_category", ""), data.get("phone", ""),
            photo_path, "已提交", now, now, user_id_val
        )
        conn.execute(sql, vals)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM registrations WHERE exam_no=?", (exam_no,)
        ).fetchone()

    conn.close()
    result = row_to_dict(row)
    result["photo_url"] = f"/uploads/{result['photo_path']}" if result.get("photo_path") else ""
    # 登录用户：把 user 关联信息也返回
    if user_id_val:
        result["linked_user"] = True
    return jsonify({"success": True, "data": result})


@app.route("/api/registration/query", methods=["GET"])
def query_registration():
    """登录用户默认查自己；未登录仍保留按身份证号查询"""
    uid = session.get("uid")
    conn = db.get_conn()
    if uid:
        row = conn.execute(
            "SELECT * FROM registrations WHERE user_id=?", (uid,)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "msg": "尚未提交报名信息"}), 404
    else:
        id_card = (request.args.get("id_card") or "").strip()
        if not id_card:
            conn.close()
            return jsonify({"success": False, "msg": "请输入身份证号"}), 400
        row = conn.execute(
            "SELECT * FROM registrations WHERE id_card=?", (id_card,)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "msg": "未查询到报名信息"}), 404
    conn.close()
    result = row_to_dict(row)
    result["photo_url"] = f"/uploads/{result['photo_path']}" if result.get("photo_path") else ""
    return jsonify({"success": True, "data": result})


# ---------- 准考证图片生成 ----------
def _find_font(size, bold=False):
    candidates = (
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simkai.ttf",
    ) if bold else (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simkai.ttf",
    )
    for p in candidates:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: continue
    return ImageFont.load_default()


def _build_birth_place(d):
    if d.get("birth_country") and d["birth_country"] not in ("中国", ""):
        return d["birth_country"]
    return " / ".join([x for x in
        (d.get("birth_province", ""), d.get("birth_city", ""), d.get("birth_county", ""))
        if x])


@app.route("/api/ticket/<exam_no>", methods=["GET"])
def generate_ticket(exam_no):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM registrations WHERE exam_no=?", (exam_no,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "msg": "未找到考生信息"}), 404
    d = row_to_dict(row)

    W, H = 720, 1080
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    draw.rectangle([(0, 0), (W, 120)], fill=(165, 28, 48))

    # 校徽贴图
    logo_path = os.path.join(STATIC_DIR, "校徽.png")
    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo_size = 80
            logo.thumbnail((logo_size, logo_size), Image.LANCZOS)
            lx, ly = 24, (120 - logo.height) // 2
            img.paste(logo, (lx, ly), logo)
        except Exception:
            pass

    title_font = _find_font(42, bold=True)
    sub_font = _find_font(22)
    draw.text((W // 2 + 20, 30), "横火高级中学", fill=(255, 255, 255),
              font=title_font, anchor="mt")
    draw.text((W // 2 + 20, 82), "模 拟 高 考 准 考 证", fill=(255, 230, 180),
              font=sub_font, anchor="mt")

    draw.rectangle([(20, 20), (W - 20, H - 20)], outline=(165, 28, 48), width=3)
    draw.line([(40, 145), (W - 40, 145)], fill=(165, 28, 48), width=2)
    draw.line([(40, 155), (W - 40, 155)], fill=(165, 28, 48), width=1)

    photo_y = 180
    photo_box = (W - 200, photo_y, W - 40, photo_y + 210)
    draw.rectangle(photo_box, outline=(120, 120, 120), width=1)
    if d.get("photo_path"):
        ppath = os.path.join(UPLOAD_DIR, d["photo_path"])
        if os.path.exists(ppath):
            try:
                p = Image.open(ppath).convert("RGB")
                p.thumbnail((photo_box[2] - photo_box[0], photo_box[3] - photo_box[1]))
                px = photo_box[0] + (photo_box[2] - photo_box[0] - p.width) // 2
                py = photo_box[1] + (photo_box[3] - photo_box[1] - p.height) // 2
                img.paste(p, (px, py))
            except Exception: pass

    label_font = _find_font(22)
    value_font = _find_font(24, bold=True)
    field_x = 50; value_x = 240
    start_y = 190; line_gap = 46

    fields = [
        ("考生号", d.get("exam_no", "")),
        ("姓　　名", d.get("name", "")),
        ("性　　别", d.get("gender", "")),
        ("出生日期", d.get("birth_date", "")),
        ("报考科类", d.get("subject_category", "")),
        ("级　　段", d.get("grade_segment", "")),
        ("考生类别", d.get("candidate_type", "") or "应届"),
        ("毕业学校", d.get("graduate_school", "")),
        ("班　　级", d.get("class_name", "")),
        ("出生地区", _build_birth_place(d)),
        ("身份证号", d.get("id_card", "")),
        ("报名状态", d.get("status", "")),
    ]
    for i, (label, val) in enumerate(fields):
        y = start_y + i * line_gap
        draw.text((field_x, y), label, fill=(80, 80, 80), font=label_font)
        draw.text((value_x, y), str(val or ""), fill=(30, 30, 30), font=value_font)

    footer_font = _find_font(18)
    draw.line([(40, H - 100), (W - 40, H - 100)], fill=(165, 28, 48), width=1)
    draw.text((W // 2, H - 80),
              "仅限横火企划模拟使用，非真实报名系统",
              fill=(165, 28, 48), font=footer_font, anchor="mm")
    draw.text((W // 2, H - 50),
              f"生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
              fill=(120, 120, 120), font=footer_font, anchor="mm")

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return send_file(out, mimetype="image/png",
                     download_name=f"准考证_{d.get('exam_no','')}.png",
                     as_attachment=True)


# ================================================================
#  学生档案 API（原 Netlify 档案系统后端对接）
# ================================================================
def _row_to_archive(row) -> dict:
    d = row_to_dict(row)
    # subjects JSON → list
    if d.get("subjects"):
        try: d["subjects"] = json.loads(d["subjects"])
        except: d["subjects"] = []
    else:
        d["subjects"] = []
    # photo 字段：优先返回 URL；前端 renderRecords 用 x.photo，后端给完整 URL
    if d.get("photo_path"):
        d["photo"] = f"/uploads/{d['photo_path']}"
    elif d.get("photo_dataurl"):
        d["photo"] = d["photo_dataurl"]
    else:
        d["photo"] = None
    d.pop("photo_path", None)
    d.pop("photo_dataurl", None)
    return d


@app.route("/api/archive/records", methods=["GET"])
def archive_list():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM archive_records ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    items = [_row_to_archive(r) for r in rows]
    return jsonify({"success": True, "data": items})


@app.route("/api/archive/records", methods=["POST"])
def archive_create():
    """接收前端档案提交（JSON，photo 是 dataURL）"""
    data = request.get_json(silent=True) or request.form.to_dict()
    if isinstance(data, str):
        try: data = json.loads(data)
        except: pass
    if not isinstance(data, dict):
        return jsonify({"success": False, "msg": "数据格式错误"}), 400

    user, err = auth.require_user()
    if err:
        return err
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "msg": "姓名必填"}), 400

    # 生成 / 复用 id
    rid = uuid.uuid4().hex  # 不接受客户端自选 ID，避免覆盖他人档案
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 登录用户关联
    uid = session.get("uid")
    username = session.get("username")
    student_no = None
    if uid:
        conn = db.get_conn()
        u = conn.execute("SELECT student_no FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        if u: student_no = u["student_no"]

    # 照片处理：前端传 base64 dataURL
    photo_path = None
    photo_dataurl = None
    raw_photo = data.get("photo") or data.get("photoData")
    if raw_photo and isinstance(raw_photo, str) and len(raw_photo) > 8_000_000:
        return jsonify({"success": False, "msg": "照片过大，请压缩后再上传"}), 413
    if raw_photo and isinstance(raw_photo, str) and raw_photo.startswith("data:image/"):
        photo_dataurl = raw_photo  # 先存原始 dataURL 回退用
        # 解码落盘
        try:
            header, b64 = raw_photo.split(",", 1)
            import base64 as _b64
            raw = _b64.b64decode(b64, validate=True)
            image = Image.open(io.BytesIO(raw))
            image.verify()
            # 猜扩展名
            ext = ".jpg"
            if "image/png" in header: ext = ".png"
            elif "image/webp" in header: ext = ".webp"
            fname = f"arc_{uuid.uuid4().hex}{ext}"
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as f: f.write(raw)
            photo_path = fname
        except Exception as e:
            photo_path = None

    rank_val = data.get("rank")
    try: rank_val = int(rank_val) if rank_val not in (None, "") else None
    except: rank_val = None

    subjects = data.get("subjects") or []
    if isinstance(subjects, str):
        try: subjects = json.loads(subjects)
        except: subjects = [s.strip() for s in subjects.split(",") if s.strip()]
    if not isinstance(subjects, list): subjects = []

    age_val = data.get("age")
    try: age_val = int(age_val) if age_val not in (None, "") else None
    except: age_val = None

    conn = db.get_conn()
    # 每个账号只创建一份档案，已有档案时更新本人记录
    existing = conn.execute("SELECT id FROM archive_records WHERE user_id=?", (uid,)).fetchone()
    if existing:
        rid = existing["id"]
        if photo_path:
            conn.execute("""UPDATE archive_records SET name=?, gender=?, age=?, rank=?, track=?,
                subjects=?, boarding=?, dorm=?, photo_path=?, photo_dataurl=NULL, updated_at=?
                WHERE id=? AND user_id=?""",
                (name, data.get("gender", ""), age_val, rank_val, data.get("track") or "",
                 json.dumps(subjects, ensure_ascii=False), data.get("boarding") or "",
                 data.get("dorm") or "", photo_path, now, rid, uid))
        else:
            conn.execute("""UPDATE archive_records SET name=?, gender=?, age=?, rank=?, track=?,
                subjects=?, boarding=?, dorm=?, updated_at=? WHERE id=? AND user_id=?""",
                (name, data.get("gender", ""), age_val, rank_val, data.get("track") or "",
                 json.dumps(subjects, ensure_ascii=False), data.get("boarding") or "",
                 data.get("dorm") or "", now, rid, uid))
    else:
        conn.execute(
            """INSERT INTO archive_records
            (id, user_id, username, student_no, name, gender, age, rank, track, subjects,
             boarding, dorm, photo_path, photo_dataurl, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, uid, username, student_no, name, data.get("gender",""), age_val, rank_val,
             data.get("track") or "", json.dumps(subjects, ensure_ascii=False),
             data.get("boarding") or "", data.get("dorm") or "", photo_path, None, now, now)
        )
    conn.commit()
    row = conn.execute("SELECT * FROM archive_records WHERE id=?", (rid,)).fetchone()
    conn.close()
    return jsonify({"success": True, "data": _row_to_archive(row)})


@app.route("/api/archive/me", methods=["GET"])
def archive_me():
    """返回当前登录用户的档案信息（供校园卡等功能使用）"""
    uid = session.get("uid")
    if not uid:
        return jsonify({"success": False, "msg": "未登录"}), 401
    conn = db.get_conn()
    # 优先查 archive_records
    row = conn.execute(
        "SELECT * FROM archive_records WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
        (uid,)
    ).fetchone()
    if row:
        conn.close()
        return jsonify({"success": True, "data": _row_to_archive(row)})
    # 兜底查 users 表
    u = conn.execute(
        "SELECT id, username, student_no, name, gender, phone, class_name, role FROM users WHERE id=?",
        (uid,)
    ).fetchone()
    conn.close()
    if not u:
        return jsonify({"success": False, "msg": "用户不存在"}), 404
    d = row_to_dict(u)
    d["photo"] = None
    d["balance"] = 0.0
    d["profile"] = {
        "name": d.get("name") or d.get("username") or "",
        "number": d.get("student_no") or "",
        "photo": None,
    }
    return jsonify({"success": True, "data": d})


# ================================================================
#  后台管理 API（脱敏）
# ================================================================
def _is_admin():
    return session.get("role") == "admin"


@app.route("/api/admin/list", methods=["GET"])
def admin_list():
    if not _is_admin():
        return jsonify({"success": False, "msg": "管理员未登录"}), 401
    page = int(request.args.get("page", 1))
    size = int(request.args.get("size", 20))
    keyword = (request.args.get("keyword") or "").strip()
    kind = request.args.get("kind", "registration")  # registration / users

    conn = db.get_conn()
    out = {"list": [], "total": 0}
    if kind == "users":
        if keyword:
            kw = f"%{keyword}%"
            rows = conn.execute(
                "SELECT id, username, student_no, name, gender, class_name, role, status, "
                "phone, email, created_at FROM users WHERE name LIKE ? OR student_no LIKE ? "
                "OR username LIKE ? OR phone LIKE ? OR class_name LIKE ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (kw, kw, kw, kw, kw, size, (page - 1) * size)
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM users WHERE name LIKE ? OR student_no LIKE ? "
                "OR username LIKE ? OR phone LIKE ? OR class_name LIKE ?",
                (kw, kw, kw, kw, kw)
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT id, username, student_no, name, gender, class_name, role, status, "
                "phone, email, created_at FROM users ORDER BY id DESC LIMIT ? OFFSET ?",
                (size, (page - 1) * size)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        items = []
        for r in rows:
            d = row_to_dict(r)
            d["phone"] = db.mask_phone(d.get("phone"))
            items.append(d)
        out["list"] = items; out["total"] = total
    else:
        if keyword:
            kw = f"%{keyword}%"
            rows = conn.execute(
                "SELECT * FROM registrations WHERE name LIKE ? OR id_card LIKE ? OR exam_no LIKE ? "
                "OR class_name LIKE ? OR phone LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (kw, kw, kw, kw, kw, size, (page - 1) * size)
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM registrations WHERE name LIKE ? OR id_card LIKE ? OR exam_no LIKE ? "
                "OR class_name LIKE ? OR phone LIKE ?",
                (kw, kw, kw, kw, kw)
            ).fetchone()[0]
        else:
            rows = conn.execute(
                "SELECT * FROM registrations ORDER BY id DESC LIMIT ? OFFSET ?",
                (size, (page - 1) * size)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
        items = []
        for r in rows:
            d = row_to_dict(r)
            d["photo_url"] = f"/uploads/{d['photo_path']}" if d.get("photo_path") else ""
            d["id_card"] = db.mask_id_card(d.get("id_card"))
            d["phone"] = db.mask_phone(d.get("phone"))
            items.append(d)
        out["list"] = items; out["total"] = total
    conn.close()
    return jsonify({"success": True, "data": out})


@app.route("/api/admin/detail/<int:rid>", methods=["GET"])
def admin_detail(rid):
    if not _is_admin():
        return jsonify({"success": False, "msg": "管理员未登录"}), 401
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM registrations WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "msg": "未找到"}), 404
    d = row_to_dict(row)
    d["photo_url"] = f"/uploads/{d['photo_path']}" if d.get("photo_path") else ""
    return jsonify({"success": True, "data": d})  # 详情页完整返回


@app.route("/api/admin/registration/<int:rid>", methods=["DELETE"])
def admin_delete_reg(rid):
    if not _is_admin():
        return jsonify({"success": False, "msg": "管理员未登录"}), 401
    conn = db.get_conn()
    conn.execute("DELETE FROM registrations WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/admin/user/<int:uid>/<action>", methods=["POST"])
def admin_user_action(uid, action):
    if not _is_admin():
        return jsonify({"success": False, "msg": "管理员未登录"}), 401
    if action == "freeze":
        conn = db.get_conn()
        conn.execute("UPDATE users SET status='frozen' WHERE id=?", (uid,))
        conn.commit(); conn.close()
        return jsonify({"success": True})
    elif action == "unfreeze":
        conn = db.get_conn()
        conn.execute("UPDATE users SET status='active' WHERE id=?", (uid,))
        conn.commit(); conn.close()
        return jsonify({"success": True})
    elif action == "reset_password":
        new_pw = request.form.get("new_password") or "HengHuo@123"
        ok, msg = auth._valid_password(new_pw)
        if not ok:
            return jsonify({"success": False, "msg": msg}), 400
        result = auth.admin_reset_password(uid, new_pw)
        return jsonify({"success": result, "msg": "重置成功，新密码：" + new_pw if result else "重置失败"})
    else:
        return jsonify({"success": False, "msg": "未知操作"}), 400


# ================================================================
#  启动
# ================================================================
if __name__ == "__main__":
    print()
    print(" 横火高级中学 · 模拟高考报名系统")
    print(" 本机:  http://127.0.0.1:5000/")
    print(" 管理员初始账号:  admin / admin123456  （首次登录请修改密码）")
    print()
    app.run(host="0.0.0.0", port=5000, debug=False)
