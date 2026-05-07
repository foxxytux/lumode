#!/usr/bin/env python3
"""Test Lumo CLI setup and connectivity."""

import sys
import os
from pathlib import Path

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
    firefox_dir = Path.home() / ".mozilla" / "firefox"

    if not firefox_dir.exists():
        print(f"✗ Firefox profile directory not found")
        return False

    profiles = list(firefox_dir.glob("*.default*"))
    if not profiles:
        print(f"✗ No Firefox profiles found")
        return False

    print(f"✓ Firefox profiles found: {len(profiles)}")
    for p in profiles:
        print(f"  - {p.name}")
    return True

def test_cookies_db():
    """Check cookies database."""
    firefox_dir = Path.home() / ".mozilla" / "firefox"
    profiles = list(firefox_dir.glob("*.default*"))

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

    firefox_dir = Path.home() / ".mozilla" / "firefox"
    profiles = list(firefox_dir.glob("*.default*"))

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
