# -*- coding: utf-8 -*-
"""Render / gunicorn 生产入口：gunicorn wsgi:app"""
from app import app
from canteen_admin import install as install_canteen
from campus_reports import install as install_reports
install_canteen(app)
install_reports(app)

if __name__ == '__main__':
    app.run()
