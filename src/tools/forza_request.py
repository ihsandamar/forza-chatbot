
from typing import Dict, Any
import requests




def get_customers_list(base_url: str, token: str, name: str) -> Dict[str, Any]:
    """Müşteri listesi getirme endpoint'i. Name parametresi ile arama yapar ve temel müşteri bilgilerini döner."""

    endpoint = f"{base_url}/api/Customers/getlist"

    # Fixed parameters as requested
    params = {
        "pageNumber": 1,
        "viewCount": 10,
        "search": "",
        "filterParameters": f'{{"andOp":[{{"columnName":"name","operator":"like","value":["{name}"],"andOp":[],"orOp":[]}}],"orOp":[]}}',
        "orderParameters": '[{"ColumnName":"name", "OrderType":"Desc"}]'
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=headers,
            timeout=30,
            verify=False
        )

        response.raise_for_status()
        response_data = response.json()

        # Filter response to only include basic customer information
        if "customerList" in response_data and isinstance(response_data["customerList"], list):
            filtered_customers = []
            for customer in response_data["customerList"]:
                filtered_customer = {
                    "customerId": customer.get("id"),
                    "customerNumber": customer.get("customerNumber"),
                    "name": customer.get("name"),
                    "shortName": customer.get("shortName")
                }
                filtered_customers.append(filtered_customer)

            # Keep original structure but with filtered data
            filtered_response = {
                "customerList": filtered_customers,
                "totalCount": response_data.get("totalCount", len(filtered_customers))
            }
        else:
            filtered_response = response_data

        return {
            "status": "success",
            "status_code": response.status_code,
            "data": filtered_response
        }

    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "error": str(e),
            "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        }

def get_templates_all(base_url: str, token: str) -> Dict[str, Any]:
    """Tüm template'leri getirme endpoint'i. Rapor şablonlarının listesini döner."""

    endpoint = f"{base_url}/api/templates/getall"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get(
            endpoint,
            headers=headers,
            timeout=30,
            verify=False
        )

        response.raise_for_status()
        return {
            "status": "success",
            "status_code": response.status_code,
            "data": response.json()
        }

    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "error": str(e),
            "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        }

def get_products_list(base_url: str, token: str, search: str) -> Dict[str, Any]:
    """Ürün listesi getirme endpoint'i. Search parametresi ile arama yapar ve temel ürün bilgilerini döner."""

    endpoint = f"{base_url}/api/products/getlist"

    params = {
        "pageNumber": 1,
        "viewCount": 10,
        "search": search,
        "filterParameters": f'{{"andOp":[],"orOp":[]}}',
        "orderParameters": '[{"ColumnName":"name", "OrderType":"Desc"}]'
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=headers,
            timeout=30,
            verify=False
        )

        response.raise_for_status()
        response_data = response.json()

        # Filter response to only include basic product information
        if "productList" in response_data and isinstance(response_data["productList"], list):
            filtered_products = []
            for product in response_data["productList"]:
                filtered_product = {
                    "productId": product.get("id"),
                    "name": product.get("name")
                }
                filtered_products.append(filtered_product)

            # Keep original structure but with filtered data
            filtered_response = {
                "productList": filtered_products,
                "totalCount": response_data.get("totalCount", len(filtered_products))
            }
        else:
            filtered_response = response_data

        return {
            "status": "success",
            "status_code": response.status_code,
            "data": filtered_response
        }

    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "error": str(e),
            "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        }
