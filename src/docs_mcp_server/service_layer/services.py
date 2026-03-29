"""Service layer - Use case orchestration.

Following Cosmic Python Chapter 4: Service Layer
- Orchestrates business use cases
- Works with domain model through repositories
- Uses Unit of Work for transaction management
"""

import logging

from docs_mcp_server.domain.model import Document
from docs_mcp_server.service_layer.filesystem_unit_of_work import AbstractUnitOfWork


logger = logging.getLogger(__name__)


async def store_document(
    url: str,
    title: str,
    markdown: str,
    text: str,
    excerpt: str | None,
    uow: AbstractUnitOfWork,
) -> Document:
    """Store or update a document.

    Service layer use case:
    1. Get existing document or create new
    2. Update content
    3. Mark as successfully fetched
    4. Commit transaction

    Args:
        url: Document URL
        title: Document title
        markdown: Markdown content
        text: Plain text content
        excerpt: Optional excerpt
        uow: Unit of Work for transaction management

    Returns:
        Stored Document
    """
    async with uow:
        # Try to get existing document
        document = await uow.documents.get(url)

        if document:
            # Update existing document
            document.update_content(markdown=markdown, text=text, excerpt=excerpt or "")
            document.title = title
        else:
            # Create new document
            document = Document.create(
                url=url,
                title=title,
                markdown=markdown,
                text=text,
                excerpt=excerpt or "",
            )

        # Mark as successfully fetched
        document.metadata.mark_success()

        # Store in repository
        await uow.documents.add(document)

        # Commit transaction
        await uow.commit()

        return document


async def mark_document_failed(
    url: str,
    uow: AbstractUnitOfWork,
) -> None:
    """Mark a document fetch as failed.

    Service layer use case:
    1. Get document
    2. Mark as failed (increments retry count)
    3. Commit transaction

    Args:
        url: Document URL
        uow: Unit of Work for transaction management
    """
    async with uow:
        document = await uow.documents.get(url)

        if document:
            document.mark_fetch_failed()
            await uow.documents.add(document)
            await uow.commit()
