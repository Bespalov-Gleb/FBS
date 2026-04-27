"""
Ошибки парсинга КИЗ из PDF.
"""
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class KizParserError(BaseModel):
    __tablename__ = "kiz_parser_errors"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("kiz_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    source_filename = Column(String(255), nullable=True)
    source_page = Column(Integer, nullable=True)
    error_message = Column(String(500), nullable=False)

    user = relationship("User")
    group = relationship("KizGroup")
