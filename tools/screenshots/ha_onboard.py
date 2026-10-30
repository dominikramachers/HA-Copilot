import asyncio, json, sys
import aiohttp
BASE = "http://127.0.0.1:8123"
CID = BASE + "/"
async def main():
    async with aiohttp.ClientSession() as s:
        r = await s.post(f"{BASE}/api/onboarding/users", json={"client_id": CID, "name": "Demo Nutzer", "username": "demo", "password": "demo-passwort-1", "language": "de"})
        d = await r.json(); print("user", r.status)
        code = d["auth_code"]
        r = await s.post(f"{BASE}/auth/token", data={"grant_type": "authorization_code", "code": code, "client_id": CID})
        tok = await r.json(); print("token", r.status)
        h = {"Authorization": "Bearer " + tok["access_token"]}
        for step, body in (("core_config", {}), ("analytics", {}), ("integration", {"client_id": CID, "redirect_uri": CID + "?auth_callback=1"})):
            r = await s.post(f"{BASE}/api/onboarding/{step}", json=body, headers=h); print(step, r.status)
        json.dump(tok, open(sys.argv[1], "w"))
asyncio.run(main())
