import sys
import os
import webbrowser
import threading
import time

# 将当前目录加入搜索路径（打包后需要）
if getattr(sys, 'frozen', False):
    os.chdir(sys._MEIPASS)

import streamlit.web.cli as stcli

def open_browser():
    time.sleep(2)  # 等待服务器启动
    webbrowser.open("http://localhost:8501")

if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    sys.argv = ["streamlit", "run", "cell_app.py", "--server.headless", "true"]
    sys.exit(stcli.main())