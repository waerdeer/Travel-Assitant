from pydantic import BaseModel,Field
from typing import Optional
from app.schemas.Location import Location
class Attraction(BaseModel):
    name: str = Field(..., description="景点名称")
    location: Location = Field(..., description="景点位置")
    address: str = Field(...,description="地址")
    visit_duration: int = Field(...,description="建议游览时间(分钟)",gt=0)
    description: str = Field(...,description="景点描述")
    category: Optional[str] = Field(default="景点",description="景点类别")
    rating: Optional[float] = Field(default=None,ge=0,le=5,description="评分")
    image_url: Optional[str] = Field(default=None,description="图片URL")
    ticket_price: int = Field(default=0,ge=0,description="门票价格(元)")