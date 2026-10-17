import dingtalk_stream
import logging
import subprocess
import shlex
import paramiko
import yaml
import os
import sqlite3
import threading
import time
import requests
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime

logging.basicConfig(level=logging.INFO)

pending_actions = {}

# ================= 告警配置区（必须替换） =================
WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?access_token=6367f6b0acf8da0f29340c1e0b54e267685ef5a4534dd7cec394d7e219121363"
WEBHOOK_SECRET = "SECbaf4c528a4574262fd13548e310edcde165e2a35b220c0bdcfab3d5093d98bc7"
# ==========================================================

last_alert_time = 0

def load_servers():
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'servers.yaml')
    with open(config_path, 'r') as f:
        return yaml.safe_load(f).get('servers', {})

def load_admins():
    config_path = os.path.join(os.path.dirname(__file__), 'config', 'users.yaml')
    if not os.path.exists(config_path):
        return []
    with open(config_path, 'r') as f:
        return yaml.safe_load(f).get('admins', [])

def ssh_exec(server_info, command):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.load_system_host_keys()
        client.connect(
            hostname=server_info['host'],
            port=server_info.get('port', 22),
            username=server_info['user'],
            key_filename=server_info.get('key_path'),
            timeout=5
        )
        stdin, stdout, stderr = client.exec_command(command)
        out = stdout.read().decode()
        err = stderr.read().decode()
        client.close()
        if err:
            return f"执行报错：\n{err}"
        return out
    except Exception as e:
        return f"SSH连接失败：{e}"

# ================= 数据库相关函数 =================
def init_db():
    conn = sqlite3.connect('chatops.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  user_id TEXT,
                  command TEXT,
                  result TEXT)''')
    conn.commit()
    conn.close()

def log_action(user_id, command, result):
    conn = sqlite3.connect('chatops.db', check_same_thread=False)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO logs (timestamp, user_id, command, result) VALUES (?, ?, ?, ?)",
              (now, user_id, command, result))
    conn.commit()
    conn.close()

# ================= 新增：主动告警模块 =================
def send_alert(msg):
    global last_alert_time
    # 告警冷却：10分钟内只发一次（防止消息轰炸）
    if time.time() - last_alert_time < 600:
        return
    last_alert_time = time.time()

    if not WEBHOOK_URL or not WEBHOOK_SECRET:
        print(f"【模拟告警】未配置Webhook，终端打印：{msg}")
        return

    try:
        # 钉钉加签计算
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f'{timestamp}\n{WEBHOOK_SECRET}'
        hmac_code = hmac.new(WEBHOOK_SECRET.encode(), string_to_sign.encode(), digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        
        url = f"{WEBHOOK_URL}&timestamp={timestamp}&sign={sign}"
        requests.post(url, json={"msgtype": "text", "text": {"content": f"🚨 监控告警 🚨\n{msg}"}}, timeout=5)
        print(f"告警已发送至钉钉群：{msg}")
    except Exception as e:
        print(f"发送告警失败: {e}")

def health_checker():
    print("后台健康检查线程已启动...")
    while True:
        time.sleep(30) # 每30秒检查一次
        servers = load_servers()
        for name, srv in servers.items():
            # 检查磁盘使用率
            out = ssh_exec(srv, "df -h / | tail -1 | awk '{print $5}'")
            
            # 如果 SSH 连不上（比如服务器宕机了）
            if "SSH连接失败" in out or "执行报错" in out:
                send_alert(f"服务器 [{name}] 无法通过SSH连接！")
                continue
                
            try:
                usage = int(out.strip().replace('%', ''))
                if usage > 90:
                    send_alert(f"服务器 [{name}] 磁盘使用率过高：{usage}%！请及时清理。")
            except:
                pass
# ====================================================

class MyBot(dingtalk_stream.ChatbotHandler):
    async def process(self, callback: dingtalk_stream.CallbackMessage):
        incoming = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
        text = incoming.text.content.strip()
        sender_id = incoming.sender_staff_id

        try:
            parts = shlex.split(text)
        except ValueError:
            self.reply_text("命令格式错误", incoming)
            return dingtalk_stream.AckMessage.STATUS_OK, 'OK'

        if not parts:
            return dingtalk_stream.AckMessage.STATUS_OK, 'OK'

        command = parts[0].lower()
        servers = load_servers()
        admins = load_admins()
        is_admin = sender_id in admins

        if command == "/help":
            reply_content = (
                "可用命令：\n"
                "/help - 查看帮助\n"
                "/whoami - 查看我的钉钉用户ID\n"
                "/status [服务器名] - 查看远程服务器状态\n"
                "/history - 查看最近5条审计日志(仅管理员)\n"
                "/restart [服务器名] - 重启服务器(需二次确认)\n"
                f"当前可用的服务器：{', '.join(servers.keys())}\n"
                f"你的管理员权限：{'✅ 是' if is_admin else '❌ 否'}"
            )
            
        elif command == "/whoami":
            reply_content = f"你的钉钉用户ID是：{sender_id}"
            
        elif command == "/status":
            target = parts[1] if len(parts) > 1 else "local"
            if target not in servers:
                reply_content = f"找不到服务器：{target}"
            else:
                srv = servers[target]
                cmd = "df -h / && echo '---MEM---' && free -m && echo '---LOAD---' && uptime"
                output = ssh_exec(srv, cmd)
                reply_content = f"**{target} 服务器状态：**\n\n{output}"
                
        elif command == "/history":
            if not is_admin:
                reply_content = "⛔ 无权限！只有管理员才能查看历史记录。"
            else:
                conn = sqlite3.connect('chatops.db', check_same_thread=False)
                c = conn.cursor()
                c.execute("SELECT timestamp, command, result FROM logs ORDER BY id DESC LIMIT 5")
                rows = c.fetchall()
                conn.close()
                if not rows:
                    reply_content = "暂无历史记录。"
                else:
                    history_text = "\n\n".join([f"[{r[0]}] 命令: {r[1]}" for r in rows])
                    reply_content = f"**最近 5 条操作记录：**\n\n{history_text}"

        elif command in ["/restart", "/reboot"]:
            if not is_admin:
                reply_content = "⛔ 无权限！只有管理员才能执行重启操作。"
            else:
                target = parts[1] if len(parts) > 1 else "local"
                action_key = f"{sender_id}_{target}"
                pending_actions[action_key] = {"target": target, "action": command}
                reply_content = (
                    f"⚠️ **危险操作确认** ⚠️\n\n"
                    f"你正准备对服务器 **{target}** 执行 `{command}`。\n"
                    f"确认请回复：`/confirm`\n"
                    f"取消请回复：`/cancel`"
                )
                
        elif command == "/confirm":
            if not is_admin:
                reply_content = "⛔ 无权限！"
            else:
                found = False
                for key in list(pending_actions.keys()):
                    if key.startswith(sender_id):
                        action = pending_actions.pop(key)
                        reply_content = f"✅ 已确认！正在对 {action['target']} 执行 {action['action']}..."
                        found = True
                        break
                if not found:
                    reply_content = "没有待确认的操作。"
                    
        elif command == "/cancel":
            for key in list(pending_actions.keys()):
                if key.startswith(sender_id):
                    pending_actions.pop(key)
            reply_content = "已取消待确认的操作。"

        else:
            reply_content = f"未知命令：{command}。发送 /help 查看可用命令。"

        log_action(sender_id, text, reply_content)
        self.reply_text(reply_content, incoming)
        return dingtalk_stream.AckMessage.STATUS_OK, 'OK'

def main():
    init_db()
    
    # ================= 新增：启动后台监控线程 =================
    t = threading.Thread(target=health_checker, daemon=True)
    t.start()
    # ==========================================================

    CLIENT_ID = "ding5tlttjdrpoc9oejv"       # 记得替换
    CLIENT_SECRET = "6N9OtvQU0rpdbNR1BwfJ5R2jb3bFeM7Crdvd93gE6-7MXFFK_DAaZJzjqsXigdY8" # 记得替换

    credential = dingtalk_stream.Credential(CLIENT_ID, CLIENT_SECRET)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        MyBot()
    )
    print("机器人启动中，等待消息...")
    client.start_forever()

if __name__ == '__main__':
    main()
