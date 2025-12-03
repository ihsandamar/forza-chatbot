#https://forza.vegayazilim.com.tr:8805/api/Customers/getList?pageNumber=1&viewCount=10&search=&filterParameters={%22andOp%22:[{%22columnName%22:%22status%22,%22operator%22:%22=%22,%22value%22:[true],%22andOp%22:[],%22orOp%22:[]}],%22orOp%22:[]}&orderParameters=[{%22ColumnName%22:%22name%22,%22OrderType%22:%22Desc%22}]

from typing import TypedDict


class FilterParameterModel(TypedDict):
    columnName: str
    operator: str
    value: list
    andOp: list
    orOp: list

class OrderParameterModel(TypedDict):
    ColumnName: str
    OrderType: str

class GetListModel(TypedDict):
    pageNumber: int
    viewCount: int
    search: str
    filterParameters: FilterParameterModel
    orderParameters: list[OrderParameterModel]
