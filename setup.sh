#!/bin/bash
# ============================================================
# 横火高级中学模拟系统 · 一键部署脚本（Linux 服务器）
# ============================================================
# 使用方法：
#   1. 把整个项目目录上传到服务器的 /opt/hengfu（或你指定的位置）
#   2. 修改下面的 YOUR_DOMAIN 为你真实的域名
#   3. 以 root 执行：bash deploy/setup.sh
#
# 脚本会自动：
#   - 安装系统依赖（Python3、Nginx、certbot）
#   - 创建虚拟环境 + 安装 pip 依赖
#   - 初始化数据库 + 创建 .env
#   - 配置 Nginx + 申请 Let's Encrypt HTTPS 证书
#   - 注册 systemd 服务 + 开机自启
# ============================================================

set -e

# ====== 必填项：改成你的域名 ======
YOUR_DOMAIN="your.domain.com"
DEPLOY_DIR="/opt/hengfu"
# ==================================

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${RED}[WARN]${NC}  $*"; }

# 必须 root
if [ "$EUID" -ne 0 ]; then
    echo "请用 root 或 sudo 运行：sudo bash $0"; exit 1
fi

# 域名占位符检查
if [ "$YOUR_DOMAIN" = "your.domain.com" ]; then
    warn "请先编辑本脚本，把 YOUR_DOMAIN 改成你的真实域名"; exit 1
fi

echo
echo "========================================="
echo "  横火高级中学模拟系统 · 一键部署脚本"
echo "  目标域名: $YOUR_DOMAIN"
echo "========================================="
echo

# ---------- 1. 系统依赖 ----------
info "安装系统依赖（Python 3.10+ / Nginx / Certbot）..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv python3-dev \
                   nginx certbot python3-certbot-nginx \
                   build-essential
ok "系统依赖安装完毕"

# ---------- 2. 项目目录 ----------
if [ ! -f "$DEPLOY_DIR/app.py" ]; then
    warn "找不到 $DEPLOY_DIR/app.py"
    echo "请先把项目文件上传到 $DEPLOY_DIR"
    exit 1
fi
cd "$DEPLOY_DIR"

# ---------- 3. Python 虚拟环境 ----------
if [ ! -d "venv" ]; then
    info "创建 Python 虚拟环境..."
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
ok "Python 依赖安装完毕"

# ---------- 4. 环境变量 ----------
if [ ! -f ".env" ]; then
    info "生成 .env（SECRET_KEY）..."
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    cat > .env <<EOF
# 自动生成于 $(date)
FLASK_SECRET_KEY=$SECRET
EOF
    ok ".env 已生成（请妥善保管）"
else
    info ".env 已存在，跳过生成"
fi
chmod 600 .env

# ---------- 5. 目录初始化 ----------
mkdir -p uploads tickets logs
touch logs/access.log logs/error.log
ok "运行目录就绪"

# ---------- 6. 初始化数据库 ----------
info "初始化数据库..."
python3 -c "import db; db.ensure_schema(); db.seed_admin()"
ok "数据库就绪（data.db 已生成，默认管理员 admin/admin123456）"

# ---------- 7. 配置 Nginx ----------
info "配置 Nginx..."
sed "s/your.domain.com/$YOUR_DOMAIN/g" deploy/nginx.conf \
    > /etc/nginx/sites-available/hengfu

# 如果有旧的默认站点，先停掉避免 80 端口冲突
if [ -f /etc/nginx/sites-enabled/default ]; then
    rm -f /etc/nginx/sites-enabled/default
fi

ln -sf /etc/nginx/sites-available/hengfu /etc/nginx/sites-enabled/hengfu

# 创建 certbot 验证目录
mkdir -p /var/www/certbot

nginx -t 2>/dev/null || { warn "Nginx 配置有问题，检查 /etc/nginx/sites-available/hengfu"; exit 1; }
nginx -s reload 2>/dev/null || systemctl restart nginx
ok "Nginx 已配置并重载"

# ---------- 8. 申请 HTTPS ----------
info "申请 Let's Encrypt HTTPS 证书..."
info "（需要域名 DNS 已解析到本服务器 IP）"
certbot --nginx -d "$YOUR_DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || {
    warn "HTTPS 证书申请失败"
    warn "可能原因：域名 DNS 还没解析到本服务器，或防火墙没开 80/443"
    warn "请手动执行：certbot --nginx -d $YOUR_DOMAIN"
}
ok "HTTPS 配置完成"

# ---------- 9. 启动 Flask（临时，先让数据库 OK）----------
info "临时启动 Flask 检查数据库..."
source venv/bin/activate
timeout 5 python3 app.py &>/dev/null &
sleep 2
pkill -f "python3 app.py" 2>/dev/null || true

# ---------- 10. 注册 systemd 服务 ----------
info "注册 systemd 服务..."
cp deploy/hengfu.service /etc/systemd/system/hengfu.service
# 替换 WorkingDirectory 如果不是默认
sed -i "s|WorkingDirectory=/opt/hengfu|WorkingDirectory=$DEPLOY_DIR|" /etc/systemd/system/hengfu.service
sed -i "s|ExecStart=/opt/hengfu|ExecStart=$DEPLOY_DIR|" /etc/systemd/system/hengfu.service

systemctl daemon-reload
systemctl enable hengfu
systemctl restart hengfu
sleep 2

# ---------- 11. 打印结果 ----------
echo
echo "========================================="
if systemctl is-active --quiet hengfu; then
    ok "✓ 服务已启动并设置开机自启"
else
    warn "✗ 服务启动失败，查看日志：journalctl -u hengfu -f"
fi
echo
echo -e "  ${CYAN}访问地址${NC}: https://$YOUR_DOMAIN/"
echo -e "  ${CYAN}管理员${NC}: https://$YOUR_DOMAIN/admin/login"
echo -e "  ${CYAN}默认管理员账号${NC}: admin / admin123456"
echo
echo -e "  ${RED}⚠  上线后立即到 admin/login 修改默认密码！${NC}"
echo
echo "  常用命令："
echo "    systemctl status hengfu      查看运行状态"
echo "    systemctl restart hengfu     重启服务"
echo "    journalctl -u hengfu -f      实时日志"
echo "    tail -f $DEPLOY_DIR/logs/error.log  错误日志"
echo "========================================="
echo
