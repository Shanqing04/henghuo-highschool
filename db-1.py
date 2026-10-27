# -*- coding: utf-8 -*-
"""数据库连接 / 表迁移 / 种子数据 / 密码哈希 工具"""
import os
import sqlite3
import hashlib
import secrets
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")


# ---------- 数据库连接 ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- 表结构（幂等迁移） ----------
USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    student_no TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    phone TEXT UNIQUE,
    email TEXT,
    name TEXT NOT NULL,
    gender TEXT NOT NULL DEFAULT '',
    birth_date TEXT NOT NULL DEFAULT '',
    age INTEGER,
    birth_country TEXT,
    birth_province TEXT,
    birth_city TEXT,
    birth_county TEXT,
    ethnicity TEXT,
    political_status TEXT,
    class_name TEXT,
    grade_segment TEXT NOT NULL DEFAULT '高三',
    graduate_school TEXT,
    photo_path TEXT,
    role TEXT NOT NULL DEFAULT 'student',          -- student / admin
    status TEXT NOT NULL DEFAULT 'active',         -- active / frozen / deleted
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_username  ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_student_no ON users(student_no);
CREATE INDEX IF NOT EXISTS idx_users_phone     ON users(phone);
CREATE INDEX IF NOT EXISTS idx_users_role      ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_status    ON users(status);
"""


def ensure_schema():
    conn = get_conn()
    conn.executescript(USERS_SCHEMA)

    # 新部署的空数据库必须先创建报名表，再进行旧库字段迁移。
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_no TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        gender TEXT,
        birth_date TEXT,
        age INTEGER,
        birth_country TEXT,
        birth_province TEXT,
        birth_city TEXT,
        birth_county TEXT,
        id_card TEXT,
        grade_segment TEXT,
        ethnicity TEXT,
        political_status TEXT,
        address TEXT,
        candidate_type TEXT,
        graduate_school TEXT,
        class_name TEXT,
        subject_category TEXT,
        phone TEXT,
        photo_path TEXT,
        status TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_reg_exam_no ON registrations(exam_no);
    """)

    # registrations 表补 user_id 外键（已有旧库没有此字段）
    cols = [c[1] for c in conn.execute("PRAGMA table_info(registrations)").fetchall()]
    if "user_id" not in cols:
        conn.execute("ALTER TABLE registrations ADD COLUMN user_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reg_user_id ON registrations(user_id)")

    # archive_records：学生档案信息（荣誉榜 / 年级排名 / 班级 / 住宿 / 科选 等）
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS archive_records (
        id TEXT PRIMARY KEY,                 -- uuid（原前端传）
        user_id INTEGER,                     -- 关联统一账号（可空）
        username TEXT,                       -- 冗余方便查询
        student_no TEXT,
        name TEXT NOT NULL,
        gender TEXT NOT NULL DEFAULT '',
        age INTEGER,
        rank INTEGER,                        -- 年级排名
        track TEXT,                          -- 文科 / 理科 / 未填
        subjects TEXT,                       -- JSON 数组 ["语文","数学","外语"]
        boarding TEXT,                       -- 是 / 否
        dorm TEXT,
        photo_path TEXT,                     -- 解码后保存到 uploads/
        photo_dataurl TEXT,                  -- 原始 dataURL（回退用，JSON 可存）
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_arc_user_id ON archive_records(user_id);
    CREATE INDEX IF NOT EXISTS idx_arc_track ON archive_records(track);
    CREATE INDEX IF NOT EXISTS idx_arc_rank ON archive_records(rank);
    """)

    conn.commit()
    conn.close()


# ---------- 密码哈希（PBKDF2-SHA256） ----------
ITERATIONS = 120_000
ALGO = "sha256"


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """返回 (hash_hex, salt_hex)"""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(ALGO, password.encode("utf-8"), salt, ITERATIONS)
    return dk.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    dk = hashlib.pbkdf2_hmac(ALGO, password.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS)
    return secrets.compare_digest(dk.hex(), hash_hex)


# ---------- 学号生成 ----------
def generate_student_no(conn) -> str:
    """规则：2位入学年份(2025→25) + 2位班级号 + 4位流水号。班级未填用 99。"""
    now = datetime.datetime.now()
    year = now.year % 100
    seq = 1
    while True:
        class_code = "00"  # 全局统一占位，班级细分可后续升级
        no = f"{year:02d}{class_code}{seq:04d}"
        exist = conn.execute("SELECT 1 FROM users WHERE student_no=?", (no,)).fetchone()
        if not exist:
            return no
        seq += 1
        if seq > 99999:
            class_code = str(int(class_code) + 1).zfill(2)
            seq = 1


# ---------- 种子数据（管理员） ----------
def seed_admin():
    conn = get_conn()
    exist = conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone()
    if exist:
        conn.close()
        return
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    initial_password = os.environ.get("ADMIN_INITIAL_PASSWORD")
    if not initial_password or len(initial_password) < 12:
        conn.close()
        print("[db] 未设置 ADMIN_INITIAL_PASSWORD（至少12位），跳过管理员初始化")
        return
    pw_hash, salt = hash_password(initial_password)
    student_no = "ADMIN00001"
    try:
        conn.execute(
            """INSERT INTO users
            (username, student_no, password_hash, salt, phone, name, gender,
             role, status, grade_segment, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("admin", student_no, pw_hash, salt, "", "系统管理员", "",
             "admin", "active", "-", now, now)
        )
        conn.commit()
        print(f"[db] 已初始化管理员账号 admin，学号 {student_no}；密码从环境变量读取")
    except sqlite3.IntegrityError:
        pass
    conn.close()


# ---------- 脱敏工具 ----------
def mask_id_card(id_card: str | None) -> str:
    if not id_card or len(id_card) < 8:
        return id_card or ""
    return id_card[:4] + "*" * (len(id_card) - 8) + id_card[-4:]


def mask_phone(phone: str | None) -> str:
    if not phone or len(phone) < 7:
        return phone or ""
    return phone[:3] + "****" + phone[-4:]
