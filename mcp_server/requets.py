
import requests
from mcp_server.constraints import API_BASE_URL

CONTROLLER_NAME = "DocumentTypes"
ENDPOINT_URL = f"{API_BASE_URL}/{CONTROLLER_NAME}/getall"


def send_request(token: str = None) -> dict:
    headers = {
        "Content-Type": "application/json",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(ENDPOINT_URL, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}




