nohup python3 server.py > server.log 2>&1 &
echo "Server started. PID: $!"
echo "访问 http://你的服务器IP:8765"
echo "管理面板 http://你的服务器IP:8765/admin"
