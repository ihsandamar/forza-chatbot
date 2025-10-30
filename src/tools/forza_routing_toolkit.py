import requests
import json
import base64
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from langchain_core.tools import BaseTool
from typing import Type, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from src.models.models import State
from langchain_core.tools.base import BaseToolkit
from langchain_core.tools import BaseTool, tool
from typing import Optional, List, Union
from abc import ABC, abstractmethod


# ============================================================================
# STANDARD MODELS - Pydantic Models for Type Safety
# ============================================================================

class ToolItem(BaseModel):
    """Standard item model for all tool responses"""
    id: str = Field(description="Unique identifier (ID, GUID, etc.)")
    name: str = Field(description="Display name of the item")

    class Config:
        extra = "allow"  # Allow additional fields for flexibility


class ToolResponseData(BaseModel):
    """Standard data structure for tool responses"""
    items: List[ToolItem] = Field(description="List of items")
    totalCount: int = Field(description="Total number of items")

    class Config:
        extra = "allow"


class ToolResponse(BaseModel):
    """Standard response model for all tools"""
    status: str = Field(description="Status: 'success' or 'error'")
    data: Optional[ToolResponseData] = Field(default=None, description="Response data when successful")
    error: Optional[str] = Field(default=None, description="Error message when status is 'error'")


# ============================================================================
# BASE TOOL CLASS - Standardized Response Format
# ============================================================================

class BaseForzaTool(ABC):
    """
    Abstract base class for all Forza routing tools.
    Ensures standardized response format across all tools.

    Standard Response Format (using Pydantic models):
    {
        "status": "success" | "error",
        "data": {
            "items": [{"id": "...", "name": "..."}, ...],
            "totalCount": <int>
        },
        "error": "<error_message>"  # Only present when status is "error"
    }
    """

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the tool with given parameters.

        Returns:
            Dict[str, Any]: Standardized response following ToolResponse model
        """
        pass


# ============================================================================
# Requests

def get_customers_list(base_url: str, token: str, name: str, business_id: str = "") -> Dict[str, Any]:
    """Müşteri listesi getirme endpoint'i. Tüm müşterileri getirir."""

    endpoint = f"{base_url}/api/Customers/getlist"

    # No filters - get all customers
    params = {
        "pageNumber": 1,
        "viewCount": 10,
        "search": "",
        "filterParameters": '{"andOp":[],"orOp":[]}',
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

# Tools 

@tool
def get_customer_id_names(token: str, base_url: str, name: str) -> Dict[str, Any]:
    """Müşteri ID ve isimlerini getirir. Name parametresi ile arama yapar."""

    result = get_customers_list(base_url, token, name)

    if result["status"] != "success":
        return result

    try:
        customers_data = result["data"]
        if "customerList" in customers_data:
            customer_id_names = []
            for customer in customers_data["customerList"]:
                customer_info = {
                    "customerId": customer.get("customerId"),
                    "name": customer.get("name")
                }
                customer_id_names.append(customer_info)

            return {
                "status": "success",
                "data": {
                    "customers": customer_id_names,
                    "totalCount": len(customer_id_names)
                }
            }
        else:
            return {
                "status": "success",
                "data": {
                    "customers": [],
                    "totalCount": 0
                }
            }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Error processing customer data: {str(e)}"
        }

@tool
def get_template_groups(token: str, base_url: str) -> Dict[str, Any]:
    """Template gruplarını listeler. Tüm template'lerin groupName bilgilerini unique olarak döner."""

    # İlk olarak tüm template'leri getir
    result = get_templates_all(base_url, token)

    if result["status"] != "success":
        return result

    try:
        templates = result["data"]
        group_names = set()

        for template in templates:
            group_name = template.get("groupName")
            if group_name:
                group_names.add(group_name)

        # Alfabetik sırala
        sorted_groups = sorted(list(group_names))

        return {
            "status": "success",
            "data": {
                "groups": sorted_groups,
                "totalCount": len(sorted_groups)
            }
        }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Error processing template groups: {str(e)}"
        }


@tool
def get_template_list(token: str, base_url: str, group_name: Optional[str] = None) -> Dict[str, Any]:
    """Template listesini getirir. Label ve id bilgilerini döner. İsteğe bağlı olarak group_name ile filtrelenebilir."""

    # İlk olarak tüm template'leri getir
    result = get_templates_all(base_url, token)

    if result["status"] != "success":
        return result

    try:
        templates = result["data"]
        template_list = []

        for template in templates:
            # Group filter uygula (eğer belirtilmişse)
            if group_name and template.get("groupName") != group_name:
                continue

            template_info = {
                "id": template.get("id"),
                "label": template.get("label"),
                "groupName": template.get("groupName")
            }
            template_list.append(template_info)

        # Label'a göre alfabetik sırala
        template_list.sort(key=lambda x: x.get("label", ""))

        return {
            "status": "success",
            "data": {
                "templates": template_list,
                "totalCount": len(template_list),
                "filteredBy": group_name if group_name else "all"
            }
        }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Error processing template list: {str(e)}"
        }

@tool
def get_products(token: str, base_url: str, search: str) -> Dict[str, Any]:
    """Ürün listesi getirir. Search parametresi ile arama yapar ve temel ürün bilgilerini döner."""

    result = get_products_list(base_url, token, search)

    if result["status"] != "success":
        return result

    try:
        products_data = result["data"]
        if "productList" in products_data:
            product_summaries = []
            for product in products_data["productList"]:
                product_info = {
                    "productId": product.get("productId"),
                    "name": product.get("name")
                }
                product_summaries.append(product_info)

            return {
                "status": "success",
                "data": {
                    "products": product_summaries,
                    "totalCount": len(product_summaries)
                }
            }
        else:
            return {
                "status": "success",
                "data": {
                    "products": [],
                    "totalCount": 0
                }
            }

    except Exception as e:
        return {
            "status": "error",
            "error": f"Error processing product data: {str(e)}"
        }

# ============================================================================
# TOOL IMPLEMENTATIONS - Inherit from BaseForzaTool
# ============================================================================

class CustomerIdNamesTool(BaseForzaTool):
    """Tool to get customer IDs and names with search functionality"""

    def execute(self, name: str) -> Dict[str, Any]:
        """
        Get customer IDs and names by name search.

        Args:
            name: Customer name to search for

        Returns:
            Standardized response with customer list (ToolResponse format)
        """
        result = get_customers_list(self.base_url, self.token, name)

        if result["status"] != "success":
            return ToolResponse(
                status="error",
                error=result.get("error", "Unknown error")
            ).model_dump()

        try:
            customers_data = result["data"]
            items = []

            if "customerList" in customers_data:
                for customer in customers_data["customerList"]:
                    items.append(ToolItem(
                        id=str(customer.get("customerId", "")),
                        name=customer.get("name", "")
                    ))

            return ToolResponse(
                status="success",
                data=ToolResponseData(
                    items=items,
                    totalCount=len(items)
                )
            ).model_dump()

        except Exception as e:
            return ToolResponse(
                status="error",
                error=f"Error processing customer data: {str(e)}"
            ).model_dump()


class ProductsTool(BaseForzaTool):
    """Tool to get product list with search functionality"""

    def execute(self, search: str) -> Dict[str, Any]:
        """
        Get product list by search term.

        Args:
            search: Product name to search for

        Returns:
            Standardized response with product list (ToolResponse format)
        """
        result = get_products_list(self.base_url, self.token, search)

        if result["status"] != "success":
            return ToolResponse(
                status="error",
                error=result.get("error", "Unknown error")
            ).model_dump()

        try:
            products_data = result["data"]
            items = []

            if "productList" in products_data:
                for product in products_data["productList"]:
                    items.append(ToolItem(
                        id=str(product.get("productId", "")),
                        name=product.get("name", "")
                    ))

            return ToolResponse(
                status="success",
                data=ToolResponseData(
                    items=items,
                    totalCount=len(items)
                )
            ).model_dump()

        except Exception as e:
            return ToolResponse(
                status="error",
                error=f"Error processing product data: {str(e)}"
            ).model_dump()


# ============================================================================
# Create Tools Functions

def _create_customer_id_names_tool(token: str, base_url: str):
    """Token ve base_url ile hazırlanmış müşteri ID ve isimleri getirme tool'u"""
    @tool
    def get_customer_id_names(name: str) -> Dict[str, Any]:
        """Müşteri ID ve isimlerini getirir. Tüm müşterileri getir."""
        result = get_customers_list(base_url, token, name)

        if result["status"] != "success":
            return result

        try:
            customers_data = result["data"]
            if "customerList" in customers_data:
                customer_id_names = []
                for customer in customers_data["customerList"]:
                    customer_info = {
                        "customerId": customer.get("customerId"),
                        "name": customer.get("name")
                    }
                    customer_id_names.append(customer_info)

                return {
                    "status": "success",
                    "data": {
                        "customers": customer_id_names,
                        "totalCount": len(customer_id_names)
                    }
                }
            else:
                return {
                    "status": "success",
                    "data": {
                        "customers": [],
                        "totalCount": 0
                    }
                }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Error processing customer data: {str(e)}"
            }

    return get_customer_id_names


def _create_get_templates_all_tool(token: str, base_url: str):
    """Token ve base_url ile hazırlanmış template listesi getirme tool'u"""
    @tool
    def get_templates_all_tool() -> Dict[str, Any]:
        """Tüm template'leri getirme endpoint'i. Rapor şablonlarının listesini döner."""
        return get_templates_all(base_url, token)

    return get_templates_all_tool


def _create_get_template_groups_tool(token: str, base_url: str):
    """Token ve base_url ile hazırlanmış template grupları getirme tool'u"""
    @tool
    def get_template_groups_tool() -> Dict[str, Any]:
        """Dinamik raporlar gruplarını listeler. Tüm dinamik raporlar'lerin groupName bilgilerini unique olarak döner."""
        result = get_templates_all(base_url, token)

        if result["status"] != "success":
            return result

        try:
            templates = result["data"]
            group_names = set()

            for template in templates:
                group_name = template.get("groupName")
                if group_name:
                    group_names.add(group_name)

            # Alfabetik sırala
            sorted_groups = sorted(list(group_names))

            return {
                "status": "success",
                "data": {
                    "groups": sorted_groups,
                    "totalCount": len(sorted_groups)
                }
            }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Error processing template groups: {str(e)}"
            }

    return get_template_groups_tool


def _create_get_template_list_tool(token: str, base_url: str):
    """Token ve base_url ile hazırlanmış template listesi (label ve id) getirme tool'u"""
    @tool
    def get_template_list_tool(group_name: Optional[str] = None) -> Dict[str, Any]:
        """Dinamik raporlar listesini döner. Sadece rapor adı ve id(guid) döner."""
        result = get_templates_all(base_url, token)

        if result["status"] != "success":
            return result

        try:
            templates = result["data"]
            template_list = []

            for template in templates:
                # Group filter uygula (eğer belirtilmişse)
                if group_name and template.get("groupName") != group_name:
                    continue

                template_info = {
                    "id": template.get("id"),
                    "label": template.get("label"),
                    "groupName": template.get("groupName")
                }
                template_list.append(template_info)

            # Label'a göre alfabetik sırala
            template_list.sort(key=lambda x: x.get("label", ""))

            return {
                "status": "success",
                "data": {
                    "templates": template_list,
                    "totalCount": len(template_list),
                    "filteredBy": group_name if group_name else "all"
                }
            }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Error processing template list: {str(e)}"
            }

    return get_template_list_tool

def _create_get_products_tool(token: str, base_url: str):
    """Token ve base_url ile hazırlanmış ürün listesi getirme tool'u"""
    @tool
    def get_products_tool(search: str) -> Dict[str, Any]:
        """Ürün listesi getirir. Search parametresi ile arama yapar ve temel ürün bilgilerini döner."""
        result = get_products_list(base_url, token, search)

        if result["status"] != "success":
            return result

        try:
            products_data = result["data"]
            if "productList" in products_data:
                product_summaries = []
                for product in products_data["productList"]:
                    product_info = {
                        "productId": product.get("productId"),
                        "name": product.get("name")
                    }
                    product_summaries.append(product_info)

                return {
                    "status": "success",
                    "data": {
                        "products": product_summaries,
                        "totalCount": len(product_summaries)
                    }
                }
            else:
                return {
                    "status": "success",
                    "data": {
                        "products": [],
                        "totalCount": 0
                    }
                }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Error processing product data: {str(e)}"
            }

    return get_products_tool

class ForzaRoutingToolkit(BaseToolkit):
    """Simplified toolkit for Forza ERP mapping operations. Provides customer and template information for mapping purposes."""

    base_url: str = Field(description="Base URL for Forza API")
    token: str = Field(description="Authentication token for Forza API")

    def __init__(self, base_url: str, token: str):
        # Ensure base_url has protocol (http:// or https://)
        if not base_url.startswith(('http://', 'https://')):
            print(f"[WARNING] base_url missing protocol, adding 'http://': {base_url}")
            base_url = f"http://{base_url}"

        super().__init__(
            name="ForzaMappingToolkit",
            description="Simplified Forza ERP toolkit specifically for customer and template mapping operations.",
            base_url=base_url,
            token=token
        )

    def get_tools(self) -> list[BaseTool]:
        """Get the tools available in this toolkit."""
        return [
            _create_customer_id_names_tool(self.token, self.base_url),
            _create_get_template_groups_tool(self.token, self.base_url),
            _create_get_template_list_tool(self.token, self.base_url),
            _create_get_products_tool(self.token, self.base_url)
        ]

