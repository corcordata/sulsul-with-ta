"""python -m sulsul_server        开服务
python -m sulsul_server info   印出要抄进 SulSulBridge.cfg 和 AI 连接器的那几段"""
import sys

from . import VERSION
from .config import Config


def main() -> None:
    cfg = Config()
    if sys.argv[1:2] == ["info"]:
        print(cfg.info())
        return
    import uvicorn

    from .app import create_app

    print(f"Sul Sul 服务器 {VERSION}，端口 {cfg.port}，数据在 {cfg.data}", flush=True)
    print("钥匙和要抄的配置：python -m sulsul_server info", flush=True)
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
