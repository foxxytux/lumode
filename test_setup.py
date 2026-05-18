#!/usr/bin/env python3
"""Test Lumo CLI setup and connectivity."""

import sys
import os
import configparser
import platform
from pathlib import Path

def get_firefox_dir() -> Path:
    """Return the Firefox profile root for the current OS."""
    system = platform.system().lower()
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "Firefox"
    if system == "linux":
        return Path.home() / ".mozilla" / "firefox"
    raise RuntimeError(f"Unsupported OS for Firefox profile lookup: {platform.system()}")

def find_firefox_profiles(firefox_dir: Path | None = None) -> list[Path]:
    """Find Firefox profiles, preferring profiles.ini default entries."""
    firefox_dir = firefox_dir or get_firefox_dir()
    profiles_ini = firefox_dir / "profiles.ini"
    profiles: list[Path] = []

    if profiles_ini.exists():
        config = configparser.ConfigParser()
        config.read(profiles_ini)
        sections = [section for section in config.sections() if section.startswith("Profile")]
        sections.sort(key=lambda section: config.get(section, "Default", fallback="0") != "1")

        for section in sections:
            path_value = config.get(section, "Path", fallback=None)
            if not path_value:
                continue

            is_relative = config.get(section, "IsRelative", fallback="1") == "1"
            profile_path = firefox_dir / path_value if is_relative else Path(path_value)
            if profile_path.exists():
                profiles.append(profile_path)

    if profiles:
        return profiles

    return [path for path in firefox_dir.iterdir() if path.is_dir() and (path / "cookies.sqlite").exists()]

def test_python_version():
    """Check Python version."""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print(f"✓ Python {version.major}.{version.minor} (OK)")
        return True
    else:
        print(f"✗ Python {version.major}.{version.minor} (need 3.8+)")
        return False

def test_dependencies():
    """Check required dependencies."""
    deps = ['requests', 'urllib3']
    all_ok = True

    for dep in deps:
        try:
            __import__(dep)
            print(f"✓ {dep} installed")
        except ImportError:
            print(f"✗ {dep} NOT installed")
            all_ok = False

    return all_ok

def test_firefox_profiles():
    """Check Firefox profile exists."""
    firefox_dir = get_firefox_dir()

    if not firefox_dir.exists():
        print(f"✗ Firefox profile directory not found at {firefox_dir}")
        return False

    profiles = find_firefox_profiles(firefox_dir)
    if not profiles:
        print(f"✗ No Firefox profiles found in {firefox_dir}")
        return False

    print(f"✓ Firefox profiles found for {platform.system()}: {len(profiles)}")
    for p in profiles:
        print(f"  - {p.name}")
    return True

def test_cookies_db():
    """Check cookies database."""
    firefox_dir = get_firefox_dir()
    if not firefox_dir.exists():
        return False

    profiles = find_firefox_profiles(firefox_dir)

    if not profiles:
        return False

    cookies_db = profiles[-1] / "cookies.sqlite"
    if not cookies_db.exists():
        print(f"✗ Cookies database not found at {cookies_db}")
        return False

    print(f"✓ Cookies database found")
    return True

def test_firefox_session():
    """Check for Lumo session in Firefox."""
    import sqlite3
    import tempfile
    import shutil

    firefox_dir = get_firefox_dir()
    if not firefox_dir.exists():
        print(f"✗ Firefox profile directory not found at {firefox_dir}")
        return False

    profiles = find_firefox_profiles(firefox_dir)

    if not profiles:
        print("✗ No Firefox profiles found")
        return False

    cookies_db = profiles[-1] / "cookies.sqlite"
    if not cookies_db.exists():
        print("✗ Cookies database not found")
        return False

    # Copy DB
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite").name
    try:
        shutil.copy(str(cookies_db), temp_db)
        conn = sqlite3.connect(temp_db)
        cur = conn.cursor()

        # Check for Lumo cookies
        cur.execute(
            "SELECT COUNT(*) FROM moz_cookies WHERE host LIKE '%lumo%' AND name LIKE 'AUTH-%'"
        )
        count = cur.fetchone()[0]
        conn.close()

        if count > 0:
            print(f"✓ Lumo AUTH cookie found in Firefox")
            return True
        else:
            print("✗ No Lumo AUTH cookie found")
            print("  → Visit https://lumo.proton.me and log in")
            return False
    except Exception as e:
        print(f"✗ Error checking cookies: {e}")
        return False
    finally:
        if os.path.exists(temp_db):
            os.unlink(temp_db)

def test_cli_scripts():
    """Check CLI scripts exist and are executable."""
    scripts = [
        'lumo_cli.py',
        'lumo_advanced.py',
    ]

    cwd = Path.cwd()
    all_ok = True

    for script in scripts:
        path = cwd / script
        if not path.exists():
            print(f"✗ {script} not found")
            all_ok = False
        elif not os.access(path, os.X_OK):
            print(f"⚠ {script} exists but not executable")
            print(f"  → Run: chmod +x {script}")
            all_ok = False
        else:
            print(f"✓ {script} found and executable")

    return all_ok

def main():
    print("🔍 Lumo CLI Setup Test")
    print("=" * 50)
    print()

    tests = [
        ("Python Version", test_python_version),
        ("Dependencies", test_dependencies),
        ("Firefox Profiles", test_firefox_profiles),
        ("Cookies Database", test_cookies_db),
        ("Lumo Firefox Session", test_firefox_session),
        ("CLI Scripts", test_cli_scripts),
    ]

    results = []
    for name, test_func in tests:
        print(f"{name}:")
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"✗ Error: {e}")
            results.append((name, False))
        print()

    # Summary
    print("=" * 50)
    passed = sum(1 for _, r in results if r)
    total = len(results)

    if passed == total:
        print(f"✅ All checks passed! ({passed}/{total})")
        print()
        print("You're ready to use Lumo CLI!")
        print()
        print("Quick start:")
        print("  ./lumo_cli.py -c \"Your question here\"")
        print()
        return 0
    else:
        print(f"⚠️  Some checks failed ({passed}/{total} passed)")
        print()

        # Provide guidance
        if not any(r for name, r in results if "Firefox Session" in name):
            print("Main issue: Lumo session not found in Firefox")
            print("Solution: Visit https://lumo.proton.me and log in")
            print()

        if not any(r for name, r in results if "Dependencies" in name):
            print("Missing dependencies. Install with:")
            print("  pip install requests urllib3")
            print()

        return 1

if __name__ == "__main__":
    sys.exit(main())
