from mcp_server.constraints import API_BASE_URL
from mcp_server.models import GetListModel


CONTROLLER_NAME = "Products"
ENDPOINT_URL = f"{API_BASE_URL}/{CONTROLLER_NAME}/getproductlist"

class ProductGetListModel(GetListModel):
    businessId: str 
    


def product_get_list(token: str = None, params: ProductGetListModel=None) -> dict:
    import json
    import requests

    headers = {
        "Content-Type": "application/json",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        # Convert nested dict parameters to JSON strings for proper URL encoding
        query_params = params.copy() if params else {}
        if "filterParameters" in query_params and isinstance(query_params["filterParameters"], dict):
            query_params["filterParameters"] = json.dumps(query_params["filterParameters"])
        if "orderParameters" in query_params and isinstance(query_params["orderParameters"], list):
            query_params["orderParameters"] = json.dumps(query_params["orderParameters"])

        response = requests.get(ENDPOINT_URL, headers=headers, params=query_params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}