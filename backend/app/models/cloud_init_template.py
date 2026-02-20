"""Cloud-init template model."""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, Text
from sqlalchemy.sql import func
from app.database import Base


class CloudInitTemplate(Base):
    """Stored cloud-init YAML template with variable placeholders."""

    __tablename__ = "cloud_init_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)  # YAML content with {{variable}} placeholders
    is_default = Column(Boolean, default=False)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<CloudInitTemplate(id={self.id}, name={self.name})>"
