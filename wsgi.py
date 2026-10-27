# -*- coding: utf-8 -*-
"""生产环境入口：gunicorn 启动用 wsgi:app"""
from app import app

if __name__ == "__main__":
    app.run()
