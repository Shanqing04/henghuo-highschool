# -*- coding: utf-8 -*-
"""鉴权蓝图：注册 / 登录 / 登出 / 改密 / me / 重置密码（管理员）"""
import re
import datetime
from flask import Blueprint, request, jsonify, session, redirect, url_for
import db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# ---------- 常量 ----------
MAX_FAIL = 5
LOCK_MINUTES = 15


# ---------- 校验辅助 ----------
def _valid_username(u: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]{6,20}", u))


def _valid_phone(p: str) -> bool:
    return bool(re.fullmatch(r"1[3-9]\d{9}", p or ""))


def _valid_email(e: str) -> bool:
    if not e:
        return True
    return bool(re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+", e))


def _valid_password(p: str) -> tuple[bool, str]:
    if not p or len(p) < 8:
        return False, "密码至少 8 位"
    if not re.search(r"[A-Za-z]", p):
        return False, "密码必须包含字母"
    if not re.search(r"\d", p):
        return False, "密码必须包含数字"
    return True, ""


def _valid_birth_date(b: str) -> bool:
    try:
        datetime.datetime.strptime(b, "%Y-%m-%d")
        return True
    except Exception:
        return False


# ---------- 登录态辅助 ----------
def login_user_row(row, remember: bool = False):
    session.permanent = remember
    session["uid"] = row["id"]
    session["username"] = row["username"]
    session["role"] = row["role"]


def logout_user():
    session.pop("uid", None)
    session.pop("username", None)
    session.pop("role", None)


def current_user_id() -> int | None:
    return session.get("uid")


def require_user(role: str | None = None):
    """装饰器形式调用：在函数开头 require_user() 直接触发 401/403"""
    uid = session.get("uid")
    if not uid:
        return None, (jsonify({"success": False, "msg": "未登录"}), 401)
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not row or row["status"] in ("frozen", "deleted"):
        logout_user()
        return None, (jsonify({"success": False, "msg": "账号不可用"}), 403)
    if role and row["role"] != role:
        return None, (jsonify({"success": False, "msg": "权限不足"}), 403)
    return row, None


# ---------- POST /register ----------
@bp.post("/register")
def register():
    data = request.form.to_dict()
    # 必填项
    required = ["username", "password", "confirm_password", "phone",
                "name", "gender", "birth_date", "age"]
    for f in required:
        if not data.get(f, "").strip():
            return jsonify({"success": False, "msg": f"必填项缺失：{f}"}), 400

    username = data["username"].strip()
    password = data["password"]
    confirm  = data["confirm_password"]
    phone    = data["phone"].strip()

    # 账号名校验
    if not _valid_username(username):
        return jsonify({"success": False, "msg": "账号名须为 6-20 位字母/数字/下划线"}), 400
    # 密码
    ok, msg = _valid_password(password)
    if not ok:
        return jsonify({"success": False, "msg": msg}), 400
    if password != confirm:
        return jsonify({"success": False, "msg": "确认密码不匹配"}), 400
    # 手机号
    if not _valid_phone(phone):
        return jsonify({"success": False, "msg": "手机号格式错误"}), 400
    # 邮箱
    if data.get("email") and not _valid_email(data["email"]):
        return jsonify({"success": False, "msg": "邮箱格式错误"}), 400
    # 出生日期
    if not _valid_birth_date(data["birth_date"]):
        return jsonify({"success": False, "msg": "出生日期格式错误（应为 YYYY-MM-DD）"}), 400
    # 年龄
    try:
        age = int(data["age"])
    except ValueError:
        return jsonify({"success": False, "msg": "年龄必须是整数"}), 400
    if not (16 <= age <= 18):
        return jsonify({"success": False, "msg": "年龄必须在 16-18 之间"}), 400

    # 唯一性校验
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        conn.close()
        return jsonify({"success": False, "msg": "该账号已被注册"}), 400
    if conn.execute("SELECT 1 FROM users WHERE phone=?", (phone,)).fetchone():
        conn.close()
        return jsonify({"success": False, "msg": "该手机号已注册"}), 400

    # 生成学号 + 哈希密码
    student_no = db.generate_student_no(conn)
    pw_hash, salt = db.hash_password(password)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fields = (
        username, student_no, pw_hash, salt,
        phone, (data.get("email") or ""),
        data["name"].strip(), data["gender"].strip(),
        data["birth_date"], age,
        data.get("birth_country", ""), data.get("birth_province", ""),
        data.get("birth_city", ""), data.get("birth_county", ""),
        (data.get("ethnicity") or ""), (data.get("political_status") or ""),
        (data.get("class_name") or ""),
        (data.get("grade_segment") or "高三"),
        (data.get("graduate_school") or "横火高级中学"),
        None,  # photo_path
        "student", "active", 0, None, now, now
    )
    sql = """INSERT INTO users
    (username, student_no, password_hash, salt, phone, email,
     name, gender, birth_date, age,
     birth_country, birth_province, birth_city, birth_county,
     ethnicity, political_status, class_name, grade_segment, graduate_school,
     photo_path, role, status, failed_login_count, locked_until,
     created_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""

    try:
        conn.execute(sql, fields)
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "msg": f"注册失败：{e}"}), 500

    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    login_user_row(row)
    return jsonify({"success": True, "data": _public_user(row)})


# ---------- POST /login ----------
@bp.post("/login")
def login():
    identifier = (request.form.get("identifier") or "").strip()
    password   = request.form.get("password") or ""
    remember   = request.form.get("remember") == "true"

    if not identifier or not password:
        return jsonify({"success": False, "msg": "账号或密码错误"}), 400

    conn = db.get_conn()
    # 判断身份类型
    if identifier.isdigit() and _valid_phone(identifier):
        row = conn.execute("SELECT * FROM users WHERE phone=?", (identifier,)).fetchone()
    elif re.fullmatch(r"\d{6,}", identifier):
        row = conn.execute("SELECT * FROM users WHERE student_no=?", (identifier,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM users WHERE username=?", (identifier,)).fetchone()

    if not row or row["status"] in ("frozen", "deleted"):
        conn.close()
        return jsonify({"success": False, "msg": "账号或密码错误"}), 401

    # 检查锁定
    if row["locked_until"]:
        try:
            locked = datetime.datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            locked = None
        now = datetime.datetime.now()
        if locked and now < locked:
            conn.close()
            remain = int((locked - now).total_seconds() // 60) + 1
            return jsonify({"success": False, "msg": f"账号已锁定，请 {remain} 分钟后重试"}), 429

    ok = db.verify_password(password, row["password_hash"], row["salt"])
    if not ok:
        new_count = row["failed_login_count"] + 1
        if new_count >= MAX_FAIL:
            lock_until = (datetime.datetime.now() + datetime.timedelta(minutes=LOCK_MINUTES))
            conn.execute(
                "UPDATE users SET failed_login_count=?, locked_until=? WHERE id=?",
                (new_count, lock_until.strftime("%Y-%m-%d %H:%M:%S"), row["id"])
            )
        else:
            conn.execute(
                "UPDATE users SET failed_login_count=? WHERE id=?", (new_count, row["id"])
            )
        conn.commit()
        conn.close()
        return jsonify({"success": False, "msg": "账号或密码错误"}), 401

    # 登录成功：清零
    conn.execute(
        "UPDATE users SET failed_login_count=0, locked_until=NULL WHERE id=?", (row["id"],)
    )
    conn.commit()
    conn.close()
    login_user_row(row, remember=remember)
    return jsonify({"success": True, "data": _public_user(row)})


# ---------- GET /me ----------
@bp.get("/me")
def me():
    uid = session.get("uid")
    if not uid:
        return jsonify({"success": False, "msg": "未登录"}), 401
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not row or row["status"] in ("frozen", "deleted"):
        logout_user()
        return jsonify({"success": False, "msg": "账号不可用"}), 403
    return jsonify({"success": True, "data": _public_user(row, full=True)})


# ---------- POST /logout ----------
@bp.post("/logout")
def logout():
    logout_user()
    return jsonify({"success": True})


# ---------- POST /change-password ----------
@bp.post("/change-password")
def change_password():
    row, err = require_user()
    if err:
        return err
    old = request.form.get("old_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    if not db.verify_password(old, row["password_hash"], row["salt"]):
        return jsonify({"success": False, "msg": "旧密码错误"}), 400
    ok, msg = _valid_password(new)
    if not ok:
        return jsonify({"success": False, "msg": msg}), 400
    if new != confirm:
        return jsonify({"success": False, "msg": "两次密码不一致"}), 400

    new_hash, new_salt = db.hash_password(new)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_conn()
    conn.execute(
        "UPDATE users SET password_hash=?, salt=?, updated_at=? WHERE id=?",
        (new_hash, new_salt, now, row["id"])
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ---------- 重置密码（管理员调用，带 session 鉴权） ----------
def admin_reset_password(user_id: int, new_password: str) -> bool:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return False
    pw_hash, salt = db.hash_password(new_password)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE users SET password_hash=?, salt=?, failed_login_count=0, locked_until=NULL, updated_at=? WHERE id=?",
        (pw_hash, salt, now, user_id)
    )
    conn.commit()
    conn.close()
    return True


# ---------- 用户对外信息（脱敏） ----------
def _public_user(row, full=False) -> dict:
    # sqlite3.Row 没有 .get()，先转 dict
    d = {k: row[k] for k in row.keys()} if hasattr(row, "keys") else dict(row)
    out = {
        "id": d["id"],
        "username": d["username"],
        "student_no": d["student_no"],
        "role": d["role"],
        "name": d["name"],
        "gender": d["gender"],
        "grade_segment": d["grade_segment"],
        "class_name": d.get("class_name") or "",
        "graduate_school": d.get("graduate_school") or "",
        "photo_url": f"/uploads/{d['photo_path']}" if d.get("photo_path") else "",
        "status": d["status"],
        "created_at": d["created_at"],
    }
    if full:
        # 对本人完整返回
        out.update({
            "phone": d.get("phone") or "",
            "email": d.get("email") or "",
            "birth_date": d.get("birth_date") or "",
            "age": d.get("age"),
            "birth_country": d.get("birth_country") or "",
            "birth_province": d.get("birth_province") or "",
            "birth_city": d.get("birth_city") or "",
            "birth_county": d.get("birth_county") or "",
            "ethnicity": d.get("ethnicity") or "",
            "political_status": d.get("political_status") or "",
        })
    return out
