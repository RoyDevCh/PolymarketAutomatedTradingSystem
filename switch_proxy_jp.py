#!/usr/bin/env python3
"""Switch Polymarket proxy to JP-01 and test API access."""
import json, time, subprocess, os

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() + result.stderr.strip()

# Step 1: Switch Polymarket group to JP-01
print("=== Switching Polymarket group to JP-01 ===")
result = run('curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H "Content-Type: application/json" -d \'{"name": "JP-01"}\'')
print(f"Switch result: {result[:200]}")

time.sleep(2)

# Verify
result = run('curl -s http://127.0.0.1:9090/proxies/Polymarket')
try:
    data = json.loads(result)
    print(f"Current selection: {data.get('now', 'unknown')}")
except:
    print(f"Current proxy info: {result[:300]}")

# Step 2: Test Polymarket CLOB API
print("\n=== Testing Polymarket CLOB API ===")
result = run('curl -s -x http://127.0.0.1:7890 https://clob.polymarket.com/time')
print(f"CLOB time API: {result[:200]}")

# Step 3: Test geoblock endpoint (CRITICAL!)
print("\n=== Testing Geoblock Check ===")
geo_result = run('curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock')
print(f"Geoblock result: {geo_result[:300]}")

try:
    geo_data = json.loads(geo_result)
    blocked = geo_data.get('blocked', 'unknown')
    country = geo_data.get('country', 'unknown')
    region = geo_data.get('region', 'unknown')
    print(f"\n{'='*50}")
    print(f"  GEOBLOCK CHECK:")
    print(f"  blocked = {blocked}")
    print(f"  country = {country}")  
    print(f"  region  = {region}")
    print(f"{'='*50}")
    if blocked:
        print("  *** BLOCKED! Need different node! ***")
    else:
        print("  *** NOT BLOCKED! Node works! ***")
except:
    pass

# Step 4: Test CLOB POST request  
print("\n=== Testing CLOB POST Request ===")
result = run('curl -s -x http://127.0.0.1:7890 -X POST https://clob.polymarket.com/order -H "Content-Type: application/json" -d \'{}\'')
print(f"CLOB POST response: {result[:200]}")

# Step 5: Check exit IP
print("\n=== Checking Exit IP ===")
result = run('curl -s -x http://127.0.0.1:7890 https://httpbin.org/ip')
print(f"Exit IP: {result[:200]}")

# Now try HK-01 (need to find its name in the config)
# Also test other non-blocked nodes
print("\n=== Testing other nodes ===")

# Try switching to CA-01 if available
for node_name in ['CA-01', 'CA-01-CloudFront', 'CA_01', 'Canada-01']:
    result = run(f'curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H "Content-Type: application/json" -d \'{{"name": "{node_name}"}}\'')
    if '"message"' not in result and result.strip() == '':
        time.sleep(1)
        geo = run('curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock')
        try:
            gd = json.loads(geo)
            if not gd.get('blocked', True):
                print(f"  {node_name}: NOT BLOCKED! country={gd.get('country')}")
                break
            else:
                print(f"  {node_name}: BLOCKED ({gd.get('country')})")
        except:
            print(f"  {node_name}: error - {geo[:100]}")
    else:
        print(f"  {node_name}: not available ({result[:50]})")