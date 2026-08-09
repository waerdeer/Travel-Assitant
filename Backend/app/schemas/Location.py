"""
=====================================================================
模块名称: Location.py
功能描述: 数据实体：定义地理位置和坐标相关的结构化数据类型。
=====================================================================
"""

from pydantic import BaseModel, Field

class Location(BaseModel):
    longitude: float = Field(..., description="经度", ge=-180, le=180)
    latitude: float = Field(..., description="纬度", ge=-90, le=90)