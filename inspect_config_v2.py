import os
from streamrip.config import Config
from app_modules.streamrip import get_streamrip_config_path

def inspect_config_v2():
    try:
        p = get_streamrip_config_path()
        c = Config(p)
        print(f"DEBUG: Config Attributes: {dir(c)}")
        if hasattr(c, "session"):
            print(f"DEBUG: Config.session Attributes: {dir(c.session)}")
            if hasattr(c.session, "database"):
                print(f"DEBUG: Config.session.database Attributes: {dir(c.session.database)}")
                print(f"DEBUG: Config.session.database.downloads_path: {getattr(c.session.database, 'downloads_path', 'MISSING')}")
        print(f"DEBUG: Config.file Attributes: {dir(c.file)}")
    except Exception as e:
        print(f"DEBUG ERROR: {e}")

if __name__ == "__main__":
    inspect_config_v2()
