import asyncio, aiohttp, json, os, sys
os.environ["https_proxy"] = "http://127.0.0.1:7890"
os.environ["http_proxy"] = "http://127.0.0.1:7890"

async def test():
    proxy = os.environ.get("https_proxy")
    print(f"proxy={proxy}")
    
    url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume&ascending=false&limit=5"
    conn = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=conn, trust_env=True) as s:
        async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json()
            print(f"Got {len(data)} markets")
            
            for item in data[:3]:
                cid = item.get("conditionId", "") or item.get("condition_id", "")
                clob_ids = item.get("clobTokenIds", [])
                outcomes = item.get("outcomes", [])
                vol = item.get("volumeNum", item.get("volume", 0))
                q = item.get("question", "")[:50]
                
                print(f"\nCID: {cid[:30]}...")
                print(f"  clobTokenIds type: {type(clob_ids).__name__}")
                if isinstance(clob_ids, list):
                    print(f"  clobTokenIds len: {len(clob_ids)}")
                    print(f"  clobTokenIds[0]: {str(clob_ids[0])[:40]}...")
                    if len(clob_ids) > 1:
                        print(f"  clobTokenIds[1]: {str(clob_ids[1])[:40]}...")
                else:
                    print(f"  clobTokenIds: {str(clob_ids)[:80]}")
                print(f"  outcomes: {outcomes}")
                print(f"  volumeNum: {vol}")
                print(f"  question: {q}")
                
                # Parse
                yes_token = ""
                no_token = ""
                if isinstance(clob_ids, list) and len(clob_ids) >= 2:
                    if isinstance(outcomes, list) and len(outcomes) >= 2:
                        for i, tid in enumerate(clob_ids):
                            if i < len(outcomes):
                                outcome = str(outcomes[i]).upper()
                                if outcome == "YES":
                                    yes_token = tid
                                elif outcome == "NO":
                                    no_token = tid
                    if not yes_token or not no_token:
                        yes_token = clob_ids[0]
                        no_token = clob_ids[1]
                print(f"  PARSED: yes_token_found={bool(yes_token)}, no_token_found={bool(no_token)}")

asyncio.run(test())