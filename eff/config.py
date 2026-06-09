import json
from .database import get_config_path

DEFAULT_CONFIG = {
    "pomodoro_duration": 25,
    "short_break_duration": 5,
    "long_break_duration": 15,
    "daily_pomodoro_goal": 8,
    "default_priority": 1,
    "theme": "dark",
    "date_format": "%Y-%m-%d",
    "time_format": "%H:%M",
    "export_dir": "~/eff_exports",
    "current_profile": "default"
}

PROFILES_DIR = "profiles"


def load_config():
    config_path = get_config_path()
    if not config_path.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    merged = DEFAULT_CONFIG.copy()
    merged.update(config)
    return merged


def save_config(config):
    config_path = get_config_path()
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_config_value(key):
    config = load_config()
    return config.get(key, DEFAULT_CONFIG.get(key))


def set_config_value(key, value):
    config = load_config()
    config[key] = value
    save_config(config)


def get_profiles():
    import os
    config_dir = get_config_path().parent
    profiles_dir = config_dir / PROFILES_DIR
    profiles_dir.mkdir(parents=True, exist_ok=True)
    
    profiles = ["default"]
    for f in profiles_dir.glob("*.json"):
        profiles.append(f.stem)
    
    return profiles


def load_profile(profile_name):
    if profile_name == "default":
        config = DEFAULT_CONFIG.copy()
        config["current_profile"] = "default"
        save_config(config)
        return
    
    config_dir = get_config_path().parent
    profile_path = config_dir / PROFILES_DIR / f"{profile_name}.json"
    
    if not profile_path.exists():
        raise ValueError(f"Profile '{profile_name}' does not exist")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    config["current_profile"] = profile_name
    save_config(config)


def save_profile(profile_name):
    config_dir = get_config_path().parent
    profiles_dir = config_dir / PROFILES_DIR
    profiles_dir.mkdir(parents=True, exist_ok=True)
    
    current_config = load_config()
    current_config.pop("current_profile", None)
    
    profile_path = profiles_dir / f"{profile_name}.json"
    with open(profile_path, 'w', encoding='utf-8') as f:
        json.dump(current_config, f, indent=2, ensure_ascii=False)


def delete_profile(profile_name):
    if profile_name == "default":
        raise ValueError("Cannot delete default profile")
    
    config_dir = get_config_path().parent
    profile_path = config_dir / PROFILES_DIR / f"{profile_name}.json"
    
    if not profile_path.exists():
        raise ValueError(f"Profile '{profile_name}' does not exist")
    
    profile_path.unlink()
    
    current_config = load_config()
    if current_config.get("current_profile") == profile_name:
        load_profile("default")
