import requests
import json
import base64
from langchain_core.tools import BaseTool
from typing import Type, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from src.models.models import State
from langchain_core.tools.base import BaseToolkit
from langchain_core.tools import BaseTool, tool
from typing import Optional, List, Union


class MasterReportCommonFilterInputModel(BaseModel):
    """Master Report için ortak filtre parametreleri modeli"""
    
    start_date: Optional[str] = Field(None, description="Başlangıç tarihi (YYYY-MM-DD formatında)")
    end_date: Optional[str] = Field(None, description="Bitiş tarihi (YYYY-MM-DD formatında)")
    business_id: str = Field(..., description="İşletme ID'si (zorunlu)")
    start_daily_time_range: Optional[str] = Field(None, description="Günlük başlangıç saati (HH:mm:ss formatında)")
    end_daily_time_range: Optional[str] = Field(None, description="Günlük bitiş saati (HH:mm:ss formatında)")
    branch_ids: Optional[List[str]] = Field(None, description="Şube ID'leri listesi")
    product_ids: Optional[List[str]] = Field(None, description="Ürün ID'leri listesi")
    category_ids: Optional[List[str]] = Field(None, description="Kategori ID'leri listesi")
    dates: Optional[List[str]] = Field(None, description="Özel tarihler listesi")
    day_of_week: Optional[List[int]] = Field(None, description="Haftanın günleri (1-7 arası)")
    platforms: Optional[List[str]] = Field(None, description="Platform listesi")
    payment_type_ids: Optional[List[int]] = Field(None, description="Ödeme tipi ID'leri")
    bank_card_type_ids: Optional[List[str]] = Field(None, description="Banka kartı tipi ID'leri")
    amount_range_first_value: Optional[float] = Field(None, description="Tutar aralığı başlangıç değeri")
    amount_range_second_value: Optional[float] = Field(None, description="Tutar aralığı bitiş değeri")
    quantity_range_first_value: Optional[float] = Field(None, description="Miktar aralığı başlangıç değeri")
    quantity_range_second_value: Optional[float] = Field(None, description="Miktar aralığı bitiş değeri")
    discount_range_first_value: Optional[float] = Field(None, description="İndirim aralığı başlangıç değeri")
    discount_range_second_value: Optional[float] = Field(None, description="İndirim aralığı bitiş değeri")
    currency_unit_ids: Optional[List[str]] = Field(None, description="Para birimi ID'leri")
    payment_user_ids: Optional[List[str]] = Field(None, description="Ödeme kullanıcısı ID'leri")
    documents_kind_ids: Optional[List[str]] = Field(None, description="Doküman türü ID'leri")
    document_type_ids: Optional[List[str]] = Field(None, description="Doküman tipi ID'leri")
    cashier_ids: Optional[List[str]] = Field(None, description="Kasiyer ID'leri")
    customer_ids: Optional[List[str]] = Field(None, description="Müşteri ID'leri")
    methods: Optional[List[str]] = Field(None, description="Metodlar listesi")
    luncheon_voucher_types: Optional[List[str]] = Field(None, description="Yemek çeki türleri")
    table_numbers: Optional[List[str]] = Field(None, description="Masa numaraları")
    search_string: Optional[str] = Field(None, description="Arama metni")
    is_include_opened_table: Optional[bool] = Field(None, description="Açık masaları dahil et")
    is_include_online: Optional[bool] = Field(None, description="Online siparişleri dahil et")
    is_include_food_delivery: Optional[bool] = Field(None, description="Yemek teslimatını dahil et")
    is_income_expense_calculated: Optional[bool] = Field(None, description="Gelir-gider hesaplaması dahil")
    branch_cities: Optional[List[str]] = Field(None, description="Şube şehirleri")
    branch_towns: Optional[List[str]] = Field(None, description="Şube ilçeleri")
    branch_group_names: Optional[List[str]] = Field(None, description="Şube grup isimleri")
    business_types: Optional[List[str]] = Field(None, description="İşletme türleri")
    document_ids: Optional[List[str]] = Field(None, description="Doküman ID'leri")
    is_only_online_delivery: Optional[bool] = Field(None, description="Sadece online teslimat")
    is_include_points_to_total_amount: Optional[bool] = Field(True, description="Puanları toplam tutara dahil et (varsayılan: True)")
    is_only_food_delivery: Optional[bool] = Field(False, description="Sadece yemek teslimatı (varsayılan: False)")


class OrderParameter(BaseModel):
    """Sıralama parametresi modeli"""
    column_name: str = Field(..., description="Sıralanacak kolon adı")
    order_type: str = Field(..., description="Sıralama tipi (Asc/Desc)")


class FilterObject(BaseModel):
    """Filtre nesnesi modeli"""
    column_name: str = Field(..., description="Filtrelenecek kolon adı")
    operator: str = Field(..., description="Operatör (=, !=, like, vb.)")
    value: List[str] = Field(..., description="Filtre değerleri")
    and_op: Optional[List['FilterObject']] = Field(None, description="AND operatörü ile bağlanan filtreler")
    or_op: Optional[List['FilterObject']] = Field(None, description="OR operatörü ile bağlanan filtreler")


class FilterParameter(BaseModel):
    """Filtre parametresi modeli"""
    and_op: Optional[List[FilterObject]] = Field(None, description="AND operatörü ile bağlanan filtreler")
    or_op: Optional[List[FilterObject]] = Field(None, description="OR operatörü ile bağlanan filtreler")


# Forward reference için gerekli
FilterObject.model_rebuild()


def decode_jwt_token(token: str) -> Dict[str, Any]:
    """JWT token'ı decode eder ve payload'u döner"""
    try:
        # JWT token format: header.payload.signature
        # Base64 decode için padding ekle
        parts = token.split('.')
        if len(parts) != 3:
            return {"error": "Invalid JWT token format"}
        
        payload = parts[1]
        # Base64 padding ekle
        payload += '=' * (4 - len(payload) % 4)
        
        # Base64 decode
        decoded_bytes = base64.b64decode(payload)
        decoded_payload = json.loads(decoded_bytes.decode('utf-8'))
        
        return decoded_payload
        
    except Exception as e:
        return {"error": f"Token decode error: {str(e)}"}


def _create_login_tool(base_url: str):
    @tool
    def login(email: str, password: str) -> Dict[str, Any]:
        """FORZA ERP kullanıcı girişi için endpoint"""
        
        login_url = f"{base_url}/api/auth/login"
        
        payload = {
            "email": email,
            "password": password
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(
                login_url,
                data=json.dumps(payload),
                headers=headers,
                timeout=30,
                verify=False
            )
            
            response.raise_for_status()
            response_data = response.json()
            
            # Token'ı decode et ve userId'yi ekle
            if "token" in response_data:
                decoded_token = decode_jwt_token(response_data["token"])
                if "error" not in decoded_token:
                    # JWT'den userId'yi al
                    user_id_key = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"
                    if user_id_key in decoded_token:
                        response_data["userId"] = decoded_token[user_id_key]
                        response_data["decoded_token"] = decoded_token
            
            return {
                "status": "success",
                "status_code": response.status_code,
                "data": response_data
            }
            
        except requests.exceptions.RequestException as e:
            return {
                "status": "error",
                "error": str(e),
                "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            }
    
    return login


def _create_get_businesses_tool(base_url: str):
    @tool
    def get_businesses_by_user_id(user_id: str, token: str) -> Dict[str, Any]:
        """Kullanıcı ID'sine göre işletmeleri getir"""
        
        endpoint = f"{base_url}/api/Businesses/getlistbyuserid"
        
        params = {
            "userId": user_id
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
    
    return get_businesses_by_user_id


def _create_get_branches_tool(base_url: str):
    @tool
    def get_branches_by_business_id(business_id: str, token: str) -> Dict[str, Any]:
        """İşletme ID'sine göre şubeleri getir"""
        
        endpoint = f"{base_url}/api/branches/getlistbybusinessid"
        
        params = {
            "businessId": business_id
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
    
    return get_branches_by_business_id


def _create_get_user_branches_tool(base_url: str):
    @tool
    def get_user_branches(email: str, password: str) -> Dict[str, Any]:
        """Kullanıcının tüm şubelerini getir (login -> businesses -> branches chain)"""
        
        # Step 1: Login
        login_tool = _create_login_tool(base_url)
        login_result = login_tool.invoke({"email": email, "password": password})
        
        if login_result["status"] != "success":
            return {
                "status": "error",
                "error": "Login failed",
                "details": login_result
            }
        
        # Extract user_id and token from login response
        try:
            user_id = login_result["data"]["userId"]
            token = login_result["data"]["token"]
        except KeyError as e:
            return {
                "status": "error", 
                "error": f"Missing field in login response: {str(e)}",
                "details": login_result
            }
        
        # Step 2: Get businesses
        businesses_tool = _create_get_businesses_tool(base_url)
        businesses_result = businesses_tool.invoke({"user_id": user_id, "token": token})
        
        if businesses_result["status"] != "success":
            return {
                "status": "error",
                "error": "Failed to get businesses",
                "details": businesses_result
            }
        
        # Step 3: Get branches for all businesses
        branches_tool = _create_get_branches_tool(base_url)
        all_branches = []
        
        try:
            businesses = businesses_result["data"]
            for business in businesses:
                business_id = business["id"]
                branches_result = branches_tool.invoke({"business_id": business_id, "token": token})
                
                if branches_result["status"] == "success":
                    branches_data = {
                        "business_id": business_id,
                        "business_name": business.get("name", "Unknown"),
                        "branches": branches_result["data"]
                    }
                    all_branches.append(branches_data)
                    
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to process branches: {str(e)}",
                "partial_data": all_branches
            }
        
        return {
            "status": "success",
            "data": {
                "user_id": user_id,
                "businesses_count": len(businesses_result["data"]),
                "branches": all_branches
            }
        }
    
    return get_user_branches


def _create_generic_get_list_tool(base_url: str, endpoint_path: str, tool_name: str, description: str, default_order_field: str = "id"):
    """Generic get list tool factory. Creates reusable get list tools for different endpoints."""
    
    @tool
    def generic_get_list(
        token: str,
        page_number: int = 1,
        view_count: int = 10,
        search: Optional[str] = None,
        filter_parameters: Optional[str] = None,
        order_parameters: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generic get list endpoint with filtering, sorting and pagination support."""
        
        endpoint = f"{base_url}{endpoint_path}"
        
        params = {
            "pageNumber": page_number,
            "viewCount": view_count
        }
        
        # Set default empty search if None
        params["search"] = search if search is not None else ""
        
        # Set default empty filter if None or empty
        if filter_parameters:
            params["filterParameters"] = filter_parameters
        else:
            params["filterParameters"] = '{"AndOp": [],"OrOp": []}'
        
        # Set default order if None or empty
        if order_parameters:
            params["orderParameters"] = order_parameters
        else:
            params["orderParameters"] = f'[{{"ColumnName":"{default_order_field}", "OrderType":"Desc"}}]'
        
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
    
    # Set custom name and description
    tool_instance = generic_get_list
    tool_instance.name = tool_name
    tool_instance.description = description
    
    return tool_instance


def _create_get_boms_list_tool(base_url: str):
    """BOM listesi getirme tool'u oluşturur"""
    return _create_generic_get_list_tool(
        base_url=base_url,
        endpoint_path="/api/Boms/getlist",
        tool_name="get_boms_list",
        description="BOM (Reçete) listesi getirme endpoint'i. Filtereleme, sıralama ve sayfalama destekler.",
        default_order_field="bomCode"
    )


def _create_get_products_list_tool(base_url: str):
    """Ürün listesi getirme tool'u oluşturur"""
    return _create_generic_get_list_tool(
        base_url=base_url,
        endpoint_path="/api/products/getlist",
        tool_name="get_products_list",
        description="Ürün listesi getirme endpoint'i. Şube filtresi, sıralama ve sayfalama destekler.",
        default_order_field="name"
    )


def _create_get_customers_list_tool(base_url: str):
    """Müşteri listesi getirme tool'u oluşturur"""

    @tool
    def get_customers_list(token: str, name: str) -> Dict[str, Any]:
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

    return get_customers_list


def _create_get_templates_all_tool(base_url: str):
    """Template listesi getirme tool'u oluşturur"""

    @tool
    def get_templates_all(token: str) -> Dict[str, Any]:
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

    return get_templates_all


def _create_get_template_groups_tool(base_url: str):
    """Template gruplarını getirme tool'u oluşturur"""

    @tool
    def get_template_groups(token: str) -> Dict[str, Any]:
        """Template gruplarını listeler. Tüm template'lerin groupName bilgilerini unique olarak döner."""

        # İlk olarak tüm template'leri getir
        get_all_tool = _create_get_templates_all_tool(base_url)
        result = get_all_tool.invoke({"token": token})

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

    return get_template_groups


def _create_get_template_list_tool(base_url: str):
    """Template listesi (label ve id) getirme tool'u oluşturur"""

    @tool
    def get_template_list(token: str, group_name: Optional[str] = None) -> Dict[str, Any]:
        """Template listesini getirir. Label ve id bilgilerini döner. İsteğe bağlı olarak group_name ile filtrelenebilir."""

        # İlk olarak tüm template'leri getir
        get_all_tool = _create_get_templates_all_tool(base_url)
        result = get_all_tool.invoke({"token": token})

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

    return get_template_list






class ForzaAPIToolkit(BaseToolkit):
    """Toolkit for Forza ERP API operations. Provides comprehensive ERP functionality including user authentication, business management, and branch operations. Can chain multiple API calls automatically."""
    
    base_url: str = Field(description="Base URL for Forza API")
    
    def __init__(self, base_url: str):
        super().__init__(
            name="ForzaAPIToolkit", 
            description="Comprehensive Forza ERP toolkit for authentication, business and branch management with automatic chaining capabilities.",
            base_url=base_url
        )

    def get_tools(self) -> list[BaseTool]:
        """Get the tools available in this toolkit."""
        return [
            _create_login_tool(self.base_url),
            _create_get_businesses_tool(self.base_url),
            _create_get_branches_tool(self.base_url),
            _create_get_user_branches_tool(self.base_url),
            _create_get_boms_list_tool(self.base_url),
            _create_get_products_list_tool(self.base_url),
            _create_get_customers_list_tool(self.base_url),
            _create_get_templates_all_tool(self.base_url),
            _create_get_template_groups_tool(self.base_url),
            _create_get_template_list_tool(self.base_url)
        ]