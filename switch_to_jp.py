#!/usr/bin/env python3
"""Add Japan proxy nodes to mihomo and create Polymarket proxy group via API"""
import json, subprocess, time, os

# Step 1: Switch Proxies group to JP-01 via mihomo API (port 9090)
print("=== Switching Proxies to 🇯🇵 日本01 ===")
r = subprocess.run(
    ["curl", "-s", "-X", "PUT",
     "http://127.0.0.1:9090/proxies/Proxies",
     "-H", "Content-Type: application/json",
     "-d", json.dumps({"name": "🇯🇵 日本01"})],
    capture_output=True, text=True, timeout=10)
print(f"Switch result: {r.stdout[:200]}")
time.sleep(2)

# Step 2: Verify current selection
r = subprocess.run(
    ["curl", "-s", "http://127.0.0.1:9090/proxies/Proxies"],
    capture_output=True, text=True, timeout=10)
try:
    d = json.loads(r.stdout)
    print(f"Current selection: {d.get('now', 'unknown')}")
except:
    print(f"Failed to read proxy status")

# Step 3: Test exit IP through proxy
print("\n=== Testing exit IP ===")
r = subprocess.run(
    ["curl", "-s", "-x", "http://127.0.0.1:7890", "https://httpbin.org/ip"],
    capture_output=True, text=True, timeout=15)
print(f"Exit IP: {r.stdout.strip()[:200]}")

# Step 4: Test Polymarket geoblock
print("\n=== Testing Polymarket geoblock ===")
r = subprocess.run(
    ["curl", "-s", "-x", "http://127.0.0.1:7890", "https://polymarket.com/api/geoblock"],
    capture_output=True, text=True, timeout=15)
try:
    d = json.loads(r.stdout)
    print(f"blocked: {d.get('blocked')}, country: {d.get('country')}, region: {d.get('region')}")
except:
    print(f"Raw response: {r.stdout[:300]}")

# Step 5: Test CLOB order API
print("\n=== Testing CLOB order API ===")
r = subprocess.run(
    ["curl", "-s", "-x", "http://127.0.0.1:7890",
     "-X", "POST", "https://clob.polymarket.com/order",
     "-H", "Content-Type: application/json",
     "-d", "{}"],
    capture_output=True, text=True, timeout=15)
print(f"Order API: {r.stdout[:300]}")

# Step 6: Test Polymarket time
print("\n=== CLOB time API ===")
r = subprocess.run(
    ["curl", "-s", "-x", "http://127.0.0.1:7890", "https://clob.polymarket.com/time"],
    capture_output=True, text=True, timeout=15)
print(f"CLOB time: {r.stdout.strip()[:100]}")