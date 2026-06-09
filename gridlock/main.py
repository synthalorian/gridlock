from fastapi import FastAPI

app = FastAPI(title="Gridlock", description="Distributed task queue")

@app.get("/health")
async def health():
    return {"status": "ok"}
