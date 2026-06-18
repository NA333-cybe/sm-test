"""
S/M 测试问卷后端服务
- SQLite 存储结果，IP 作为用户标识
- 可选邮件发送（需配置 SMTP 授权码）
启动：python server.py
端口：8765
"""
import json
import sqlite3
import smtplib
from email.mime.text import MIMEText
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import os

# ========== 配置 ==========
DB_PATH = os.path.join(os.path.dirname(__file__), "sm_results.db")
LISTEN_PORT = int(os.environ.get("PORT", 8765))

# 邮件配置（可选，留空则不启用邮件发送）
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SMTP_SENDER = "1354820524@qq.com"
SMTP_PASSWORD = ""  # 填写 QQ 邮箱 SMTP 授权码后启用邮件发送
# ==========================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            s_percent INTEGER NOT NULL,
            m_percent INTEGER NOT NULL,
            label TEXT NOT NULL,
            description TEXT NOT NULL,
            answers_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def save_result(ip, data):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO results (ip_address, s_percent, m_percent, label, description, answers_json, created_at) VALUES (?,?,?,?,?,?,?)",
        (ip, data["sPercent"], data["mPercent"], data["label"],
         data["desc"], json.dumps(data.get("answers", []), ensure_ascii=False),
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def get_all_results():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT * FROM results ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(zip(["id","ip_address","s_percent","m_percent","label","description","answers_json","created_at"], r)) for r in rows]

def send_email(to, subject, body):
    if not SMTP_PASSWORD:
        return False, "SMTP 未配置（未填写授权码）"
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_SENDER
        msg["To"] = to
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_SENDER, SMTP_PASSWORD)
            server.sendmail(SMTP_SENDER, [to], msg.as_string())
        return True, "邮件已发送"
    except Exception as e:
        return False, str(e)

def get_client_ip(handler):
    xff = handler.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    xri = handler.headers.get("X-Real-IP", "")
    if xri:
        return xri.strip()
    return handler.client_address[0]

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._cors()
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/results":
            rows = get_all_results()
            self._cors()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(rows, ensure_ascii=False).encode())
        elif path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/admin":
            self._serve_admin_page()
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length)) if length > 0 else {}

        if path == "/api/save":
            ip = data.get("ip") or get_client_ip(self)
            try:
                save_result(ip, data)
                self._json_resp(200, {"ok": True, "msg": "结果已保存"})
                print(f"[DB] 保存结果 - IP: {ip}  S:{data.get('sPercent')}%  M:{data.get('mPercent')}%  {data.get('label')}")
            except Exception as e:
                self._json_resp(500, {"ok": False, "msg": str(e)})

        elif path == "/api/send-email":
            to = data.get("to", "")
            subject = data.get("subject", "S/M 属性测试结果")
            body = data.get("body", "")
            ok, msg = send_email(to, subject, body)
            self._json_resp(200 if ok else 500, {"ok": ok, "msg": msg})

        elif path == "/api/my-result":
            ip = data.get("ip") or get_client_ip(self)
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute(
                "SELECT * FROM results WHERE ip_address=? ORDER BY created_at DESC LIMIT 1", (ip,)
            ).fetchone()
            conn.close()
            if row:
                result = dict(zip(["id","ip_address","s_percent","m_percent","label","description","answers_json","created_at"], row))
                self._json_resp(200, {"ok": True, "result": result})
            else:
                self._json_resp(200, {"ok": True, "result": None, "msg": "该IP暂无测试记录"})
        else:
            self.send_error(404)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_resp(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _serve_html(self):
        html_path = os.path.join(os.path.dirname(__file__), "sm-test.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        except FileNotFoundError:
            self.send_error(404, "HTML file not found")

    def _serve_admin_page(self):
        rows = get_all_results()
        rows_html = ""
        for r in rows:
            answers = json.loads(r["answers_json"]) if isinstance(r["answers_json"], str) else r["answers_json"]
            answered = sum(1 for a in answers if a is not None)
            rows_html += f"""
            <tr>
                <td>{r['id']}</td>
                <td>{r['ip_address']}</td>
                <td style="color:#ff6b6b;font-weight:700">{r['s_percent']}%</td>
                <td style="color:#4da6ff;font-weight:700">{r['m_percent']}%</td>
                <td>{r['label']}</td>
                <td>{r['created_at']}</td>
            </tr>"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>S/M 测试 - 管理面板</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#0d1117;color:#c9d1d9;padding:40px}}
h1{{color:#ffd93d;margin-bottom:8px}} .sub{{color:#666;margin-bottom:24px;font-size:0.9rem}}
table{{width:100%;border-collapse:collapse;background:rgba(255,255,255,0.03);border-radius:12px;overflow:hidden}}
th{{background:rgba(255,255,255,0.06);padding:12px 16px;text-align:left;font-size:0.85rem;color:#888}}
td{{padding:10px 16px;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.9rem}}
tr:hover{{background:rgba(255,255,255,0.04)}}
.stats{{display:flex;gap:24px;margin-bottom:24px}}
.stat{{background:rgba(255,255,255,0.04);border-radius:10px;padding:16px 24px;text-align:center}}
.stat-num{{font-size:2rem;font-weight:700}}
</style></head>
<body>
<h1>S/M 属性测试 - 数据面板</h1>
<p class="sub">所有测试结果 · 共 {len(rows)} 条记录</p>
<div class="stats">
    <div class="stat"><div class="stat-num" style="color:#ff6b6b">{len(rows)}</div><div style="color:#888;font-size:0.8rem">总测试数</div></div>
</div>
<table><thead><tr><th>ID</th><th>IP 地址</th><th>S</th><th>M</th><th>类型</th><th>时间</th></tr></thead><tbody>{rows_html}</tbody></table>
</body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    init_db()
    print(f"服务启动 → http://127.0.0.1:{LISTEN_PORT}")
    print(f"管理面板 → http://127.0.0.1:{LISTEN_PORT}/admin")
    print(f"数据库文件 → {DB_PATH}")
    if SMTP_PASSWORD:
        print(f"邮件发送 → 已启用 ({SMTP_SENDER})")
    else:
        print(f"邮件发送 → 未配置（编辑脚本填写授权码启用）")
    HTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
