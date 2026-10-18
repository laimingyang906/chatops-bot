--------------------------------------------------ChatOps 智能运维机器人------------------------------------------

基于钉钉 Stream API 开发的轻量级 ChatOps 运维机器人。旨在将日常重复性的服务器运维操作（如状态巡检、日志查询、服务重启）接入团队聊天流，提升排障与协作效率。

---------------------架构设计----------------------------

[ 钉钉移动端/PC端 ] <--- (WebSocket 长连接) ---> [ 阿里云服务器 (Python程序) ]
                                                        |
                                          +-------------+-------------+
                                          |                           |
                                  [ SQLite 审计库 ]          [ Paramiko SSH 模块 ]
                                                                      |
                                                            [ 目标服务器集群 ]

 
---------------------核心功能与亮点-----------------------

1.多服务器集中管理：通过 YAML 配置化管理多台服务器，支持 SSH 免密安全连接。

2.指令安全与权限控制：

  杜绝命令注入：使用 shlex.split解析参数，严格限制白名单执行。
  RBAC 权限控制：基于钉钉用户 ID 识别管理员，非管理员只能执行只读命令。
  危险操作二次确认：/restart 等操作需管理员二次确认（/confirm）后才执行。

3.完整的审计日志：基于 SQLite 自动记录操作人、时间、指令及结果，支持 /history 追溯。

4.主动健康巡检与告警：内置后台守护线程，每 30 秒巡检服务器磁盘、SSH 连通性。异常时通过 Webhook 主动推送告警，并实现 10 分钟告警冷却防骚扰。

5.企业级部署：使用 Systemd 托管，实现开机自启、崩溃自动重启。

----------------------功能演示截图-----------------

![状态查询]

<img width="92" height="149" alt="690f7934cbd8dbc72d958ff975655f3" src="https://github.com/user-attachments/assets/5466f766-5edf-42ec-8f87-c9d5383b5ea7" />

![危险操作确认]

<img width="92" height="77" alt="389111f28fb901af38fd5eb10e8681e" src="https://github.com/user-attachments/assets/1e96b91a-15a4-4b62-8ec6-d7ddd33692b8" />

![主动告警]

<img width="97" height="34" alt="309b9631177972b5e035d654ca44520" src="https://github.com/user-attachments/assets/572281a3-95c5-4635-bd7a-dc082a67e8eb" />

![审计日志]

<img width="91" height="84" alt="8ee0dfdff5cc251853f9499a1de7765" src="https://github.com/user-attachments/assets/4744e377-0bcd-4c66-988b-ceec35b6628a" />


----------------------快速部署------------------
1. 环境准备
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
2. 配置信息
重命名并编辑 config/servers.yaml，填入目标服务器 IP 和密钥路径。
编辑 config/users.yaml，填入管理员的钉钉 ID。
修改 bot.py，填入你的钉钉 AppKey/Secret 及告警 Webhook。
3. 启动服务
使用 Systemd 托管
systemctl start chatops-bot
