# -*- coding: utf-8 -*-
"""横火高中：公开举报公示栏。由 wsgi.py 安装。"""
import datetime
import os
import sqlite3
import threading
from flask import jsonify, render_template, request, session
import db

CATEGORIES = ('学生', '教师', '宿舍', '食堂', '其他')
_lock = threading.Lock()


def install(app):
    def ensure_table():
        with _lock:
            conn = db.get_conn()
            try:
                conn.execute('''CREATE TABLE IF NOT EXISTS campus_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    anonymous INTEGER NOT NULL DEFAULT 1,
                    category TEXT NOT NULL,
                    target TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )''')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_campus_reports_date ON campus_reports(id DESC)')
                conn.commit()
            finally:
                conn.close()

    ensure_table()

    @app.get('/reports')
    def campus_reports_page():
        return render_template('reports.html')

    @app.get('/api/campus-reports')
    def campus_reports_list():
        ensure_table()
        try:
            page = max(1, min(int(request.args.get('page', 1)), 10000))
        except (ValueError, TypeError):
            page = 1
        category = request.args.get('category', '').strip()
        conn = db.get_conn()
        try:
            where = 'WHERE category=?' if category in CATEGORIES else ''
            args = (category,) if where else ()
            rows = conn.execute(f'''SELECT id, anonymous, author_name, category, target,
                    title, content, created_at FROM campus_reports {where}
                    ORDER BY id DESC LIMIT 30 OFFSET ?''', args + ((page - 1) * 30,)).fetchall()
            count = conn.execute(f'SELECT COUNT(*) FROM campus_reports {where}', args).fetchone()[0]
            return jsonify(success=True, data=[{
                'id': r['id'], 'author': '匿名同学' if r['anonymous'] else r['author_name'],
                'anonymous': bool(r['anonymous']), 'category': r['category'],
                'target': r['target'], 'title': r['title'], 'content': r['content'],
                'created_at': r['created_at']
            } for r in rows], total=count, page=page)
        finally:
            conn.close()

    @app.post('/api/campus-reports')
    def campus_reports_create():
        import auth
        user, err = auth.require_user()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        category = str(data.get('category') or '').strip()
        target = str(data.get('target') or '').strip()
        title = str(data.get('title') or '').strip()
        content = str(data.get('content') or '').strip()
        anonymous = data.get('anonymous') is True
        if category not in CATEGORIES:
            return jsonify(success=False, msg='请选择举报类别'), 400
        if not (2 <= len(target) <= 80 and 4 <= len(title) <= 120 and 10 <= len(content) <= 3000):
            return jsonify(success=False, msg='请填写举报对象（2–80字）、标题（4–120字）和内容（10–3000字）'), 400
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ensure_table()
        conn = db.get_conn()
        try:
            # 限流：同一账号一分钟内只能提交一次
            last = conn.execute('SELECT created_at FROM campus_reports WHERE user_id=? ORDER BY id DESC LIMIT 1', (user['id'],)).fetchone()
            if last:
                try:
                    elapsed = (datetime.datetime.now() - datetime.datetime.strptime(last['created_at'], '%Y-%m-%d %H:%M:%S')).total_seconds()
                    if elapsed < 60:
                        return jsonify(success=False, msg='提交太频繁，请一分钟后再试'), 429
                except (ValueError, TypeError):
                    pass
            cursor = conn.execute('''INSERT INTO campus_reports
                (user_id, author_name, anonymous, category, target, title, content, created_at)
                VALUES (?,?,?,?,?,?,?,?)''',
                (user['id'], user['username'], int(anonymous), category, target, title, content, now))
            conn.commit()
            return jsonify(success=True, data={'id': cursor.lastrowid}), 201
        finally:
            conn.close()

    @app.delete('/api/campus-reports/<int:report_id>')
    def campus_reports_delete(report_id):
        import auth
        user, err = auth.require_user(role='admin')
        if err:
            return err
        conn = db.get_conn()
        try:
            result = conn.execute('DELETE FROM campus_reports WHERE id=?', (report_id,))
            conn.commit()
            if not result.rowcount:
                return jsonify(success=False, msg='该举报不存在'), 404
            return jsonify(success=True)
        finally:
            conn.close()

    # 不修改大型 archive.html 原文件，在门户中加入举报栏入口。
    @app.after_request
    def add_reports_entry(response):
        if request.path != '/archive' or response.status_code != 200 or not response.mimetype == 'text/html':
            return response
        try:
            html = response.get_data(as_text=True)
            snippet = '''<a href="/reports" id="reports-portal-link" style="position:fixed;right:16px;bottom:18px;z-index:9998;background:#a51c30;color:#fff;padding:12px 17px;border-radius:8px;text-decoration:none;box-shadow:0 3px 12px #0003;font-size:14px;font-weight:bold">📣 校园举报公示栏</a>'''
            if 'reports-portal-link' not in html:
                response.set_data(html.replace('</body>', snippet + '\n</body>'))
        except Exception:
            pass
        return response
