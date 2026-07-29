import sys, os, json, asyncio
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.main import app
from api.dependencies.database import init_db, close_db


async def test():
    await init_db()
    from httpx import AsyncClient
    async with AsyncClient(app=app, base_url='http://test') as c:
        r = await c.post('/api/v1/auth/register', json={'email':'llmtest@example.com','password':'password123'})
        if r.status_code == 201:
            token = r.json()['access_token']
        else:
            r = await c.post('/api/v1/auth/login', data={'username':'llmtest@example.com','password':'password123'})
            token = r.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}

        r1 = await c.post('/api/v1/playback/complete', headers=headers, json={
            'track_id':'1440800769','title':'Blinding Lights','artist':'The Weeknd',
            'completed':True,'skipped':False,'play_duration_sec':200,'track_duration_sec':200
        })
        print(f'Playback log: {r1.status_code}')

        r2 = await c.get('/api/v1/playback/stats', headers=headers)
        print(f'Stats: {r2.status_code} {r2.text[:200]}')

        r3 = await c.post('/api/v1/blueprint/generate', headers=headers)
        print(f'Blueprint: {r3.status_code}')
        data = r3.json()
        print(f'Strategy: {json.dumps(data.get("strategy",{}), indent=2)[:600]}')
        print(f'Seed tracks: {json.dumps(data.get("seed_tracks",[]))[:300]}')
        print(f'LLM tokens used: {data.get("llm_tokens_used", "N/A")}')

    await close_db()

asyncio.run(test())
