import sys
import os
from streamrip.config import Config
from app_modules.streamrip import get_streamrip_config_path

def inspect_config():
    p = get_streamrip_config_path()
    print(f"Config path: {p}")
    if not os.path.exists(p):
        print("Config not found")
        return
    c = Config(p)
    f = c.file
    print(f"File data attrs: {dir(f)}")
    if hasattr(f, "session"):
        print(f"Session attrs: {dir(f.session)}")
        if hasattr(f.session, "database"):
            print(f"Session Dataset attrs: {dir(f.session.database)}")
            print(f"Session Database downloads_path: {getattr(f.session.database, 'downloads_path', 'MISSING')}")
    if hasattr(f, "database"):
        print(f"Database attrs: {dir(f.database)}")
        print(f"Database downloads_path: {getattr(f.database, 'downloads_path', 'MISSING')}")

if __name__ == "__main__":
    inspect_config()
