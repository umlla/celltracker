"""允许使用 `python -m backend` 启动服务。"""

from .serve import main

if __name__ == "__main__":
    raise SystemExit(main())
