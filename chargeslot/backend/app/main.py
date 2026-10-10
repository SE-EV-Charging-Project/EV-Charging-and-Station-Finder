from fastapi import FastAPI

app = FastAPI(title="ChargeSlot API")


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "chargeslot-api"
    }