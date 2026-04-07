import os
import toml
from app_modules.streamrip import get_streamrip_config_path

def fix_config_manually(downloads_db_path, failed_downloads_path):
    p = get_streamrip_config_path()
    if not os.path.exists(p):
        print("Config not found")
        return False
        
    with open(p, "r", encoding="utf-8") as f:
        data = toml.load(f)
        
    if "session" not in data:
        data["session"] = {}
    if "database" not in data["session"]:
        data["session"]["database"] = {}
        
    data["session"]["database"]["downloads_enabled"] = True
    data["session"]["database"]["downloads_path"] = downloads_db_path
    data["session"]["database"]["failed_downloads_path"] = failed_downloads_path
    
    with open(p, "w", encoding="utf-8") as f:
        toml.dump(data, f)
    print("Config fixed manually via TOML")
    return True

if __name__ == "__main__":
    import sys
    fix_config_manually(sys.argv[1], sys.argv[2])
