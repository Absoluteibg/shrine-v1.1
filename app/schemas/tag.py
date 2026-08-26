from pydantic import BaseModel, ConfigDict, Field


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
