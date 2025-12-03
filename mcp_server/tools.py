from mcp.server.fastmcp import FastMCP
from mcp_server.models import GetListModel
from mcp_server.requests.document_type import document_types_get_all
from mcp_server.requests.product import ProductGetListModel


mcp = FastMCP("Demo", json_response=True)

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1laWRlbnRpZmllciI6IjE2MzY3MGMzLTU2MDQtNDFkNy0yNWVlLTA4ZDlkMWI4YzFmMCIsImVtYWlsIjoiQWRtaW4iLCJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1lIjoiVkVHQSIsImh0dHA6Ly9zY2hlbWFzLm1pY3Jvc29mdC5jb20vd3MvMjAwOC8wNi9pZGVudGl0eS9jbGFpbXMvcm9sZSI6IkFkbWluIiwibmJmIjoxNzY0NzQ1MjM3LCJleHAiOjE3NjQ4MzE2MzcsImlzcyI6Imh0dHBzOi8vd3d3LnZlZ2F5YXppbGltLmNvbS50ci8iLCJhdWQiOiJodHRwczovL3d3dy52ZWdheWF6aWxpbS5jb20udHIvIn0.9GQYwx0a6JakEPycZY7H26e2Y7OXupWRZla4mdbYmOE"

@mcp.tool()
def get_document_types() -> dict:
    """Belge türlerini alır."""
    return document_types_get_all(token=token)


@mcp.tool()
def customer_get_list(params: GetListModel) -> dict:
    """Müşteri/cari listesini alır."""
    from mcp_server.requests.customer import customer_get_list
    return customer_get_list(token=token, params=params)


@mcp.tool()
def branch_get_all() -> dict:
    """Şube listesini alır."""
    from mcp_server.requests.branch import branch_get_all
    return branch_get_all(token=token)

@mcp.tool()
def product_get_list(params: ProductGetListModel) -> dict:
    """Ürün listesini alır."""
    from mcp_server.requests.product import product_get_list
    return product_get_list(token=token, params=params)

