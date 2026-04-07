import os
import toml
from app_modules.streamrip import get_streamrip_config_path

def read_toml():
    p = get_streamrip_config_path()
    if not os.path.exists(p):
        print("Not Found")
        return
    with open(p, "r", encoding="utf-8") as f:
        print(f.read())

if __name__ == "__main__":
    read_toml()
