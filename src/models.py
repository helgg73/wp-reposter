from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    name: str
    url: str
    max_pages: int = 3


class FieldMapping(BaseModel):
    title: str = "title"
    content: str = "description"
    link: str = "link"
    published: str = "published"


class MaxChannelConfig(BaseModel):
    enabled: bool = True
    field_mapping: FieldMapping = Field(default_factory=FieldMapping)
    template: str = "{title}\n\n{content}\n\n{link}"


class ExportConfig(BaseModel):
    max_channel: MaxChannelConfig = Field(default_factory=MaxChannelConfig)


class Settings(BaseModel):
    check_interval: int = 300
    sources: list[SourceConfig]
    export: ExportConfig = Field(default_factory=ExportConfig)
