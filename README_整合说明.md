# 横火高中 · 同事后端整合版

以同事提供的 hengfu-deploy.zip 为主项目，不另建数据库或替换已有页面。保留其登录注册、档案、报名、管理员及部署代码。

## 这次整合
- 保留同事原有的 `templates/archive.html` 官网（含 V16 页面布局），补入独立校园卡详情页 `/campus-card`。
- 档案公开查询 `/api/archive/records`，新档案只允许登录用户提交；每个账号一份档案，重复提交仅修改本人档案。
- 初次启动自动建立空的 SQLite 数据表；没有任何预置学生记录，也没有打包现有 `data.db`。
- 管理员账号只在设置 `ADMIN_INITIAL_PASSWORD`（至少12位）时初始化，不再使用文档中的公开默认密码。
- 移除了全站通配 CORS 头；前端和后端建议使用同一域名。

## Windows 本地启动
1. 安装 Python 3.10+。
2. 在项目目录执行 `pip install -r requirements.txt`。
3. 复制 `.env.example` 为 `.env`，设置随机 `FLASK_SECRET_KEY` 和 `ADMIN_INITIAL_PASSWORD`（至少12位）。
4. 执行 `python app.py`，打开 `http://127.0.0.1:5000/`。
5. 注册普通账号，登录后填写学生档案；其他人可查看公开档案。

## 正式上线注意
- **不要直接拖到 Netlify Drop**：这是 Flask + SQLite 动态网站，需要支持 Python、持久磁盘的主机。
- 将 `data.db`、`uploads/`、`tickets/` 放在持久存储上并定期备份；部署更新不能覆盖它们。
- 目前校园卡详情沿用原独立 HTML，其余额等模拟功能不等于已接入数据库。
- 正式上线前仍需完成真实部署环境中的账号权限、上传、CSRF 与端到端测试；建议 HTTPS。
- 原部署文档中的默认管理员密码已不适用于此整合版。
