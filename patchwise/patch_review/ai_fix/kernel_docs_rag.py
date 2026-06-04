# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""
RAG (Retrieval-Augmented Generation) for Linux Kernel Documentation.

This module provides runtime indexing and retrieval of Linux kernel documentation
from Documentation/ directory to ensure 100% upstream compliance.
"""

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import chromadb
    from chromadb.config import Settings

    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

try:
    import litellm

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False


class KernelDocRAG:
    """
    Runtime RAG system for Linux kernel documentation.

    Creates a temporary vector database from Documentation/ directory,
    retrieves relevant sections for checkpatch/sparse issues, and
    destroys the database after use.
    """

    # Key documentation files for patch submission
    PRIORITY_DOCS = [
        "process/coding-style.rst",
        "process/submitting-patches.rst",
        "process/submit-checklist.rst",
        "dev-tools/checkpatch.rst",
        "dev-tools/sparse.rst",
        "process/deprecated.rst",
        "process/kernel-docs.rst",
    ]

    def __init__(self, repo_path: str, logger: Optional[logging.Logger] = None):
        """
        Initialize RAG system.

        Args:
            repo_path: Path to Linux kernel repository
            logger: Optional logger instance
        """
        self.repo_path = Path(repo_path)
        self.doc_path = self.repo_path / "Documentation"
        self.logger = logger or logging.getLogger(__name__)

        # Temporary directory for ChromaDB
        self.temp_dir = None
        self.collection = None
        self.client = None

        # Check dependencies
        if not CHROMADB_AVAILABLE:
            self.logger.warning("ChromaDB not available. RAG will be disabled.")
        if not LITELLM_AVAILABLE:
            self.logger.warning("litellm not available. RAG will be disabled.")

    def __enter__(self):
        """Context manager entry - initialize RAG."""
        if CHROMADB_AVAILABLE and LITELLM_AVAILABLE:
            self._initialize_rag()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup RAG."""
        self._cleanup_rag()

    def _initialize_rag(self):
        """Initialize RAG system with temporary ChromaDB."""
        try:
            self.logger.info("Initializing Kernel Documentation RAG...")

            # Create temporary directory for ChromaDB
            self.temp_dir = tempfile.mkdtemp(prefix="kernel_doc_rag_")
            self.logger.debug(f"Created temp RAG directory: {self.temp_dir}")

            # Initialize ChromaDB client (new API)
            self.client = chromadb.PersistentClient(
                path=self.temp_dir,
                settings=Settings(
                    anonymized_telemetry=False,
                )
            )

            # Create collection
            self.collection = self.client.create_collection(
                name="kernel_docs",
                metadata={"description": "Linux kernel documentation"},
            )

            # Index documentation
            self._index_documentation()

            self.logger.info("RAG initialization complete")

        except Exception as e:
            self.logger.error(f"Failed to initialize RAG: {e}")
            self._cleanup_rag()

    def _cleanup_rag(self):
        """Cleanup RAG resources."""
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                self.logger.debug(f"Cleaned up RAG directory: {self.temp_dir}")
        except Exception as e:
            self.logger.warning(f"Failed to cleanup RAG: {e}")

    def _index_documentation(self):
        """Index kernel documentation into vector database."""
        if not self.doc_path.exists():
            self.logger.warning(f"Documentation path not found: {self.doc_path}")
            return

        self.logger.info("Indexing kernel documentation...")

        # Index priority docs first
        indexed_count = 0
        for doc_pattern in self.PRIORITY_DOCS:
            doc_file = self.doc_path / doc_pattern
            if doc_file.exists():
                indexed_count += self._index_file(doc_file, priority=True)

        self.logger.info(f"Indexed {indexed_count} documentation chunks")

    def _index_file(self, file_path: Path, priority: bool = False) -> int:
        """
        Index a single documentation file.

        Args:
            file_path: Path to documentation file
            priority: Whether this is a priority document

        Returns:
            Number of chunks indexed
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Split into chunks (by sections)
            chunks = self._split_into_chunks(content, file_path.name)

            if not chunks:
                return 0

            # Prepare for indexing
            ids = []
            documents = []
            metadatas = []
            embeddings = []

            for i, (chunk_text, chunk_meta) in enumerate(chunks):
                chunk_id = f"{file_path.stem}_{i}"
                ids.append(chunk_id)
                documents.append(chunk_text)

                metadata = {
                    "file": str(file_path.relative_to(self.doc_path)),
                    "priority": priority,
                    **chunk_meta,
                }
                metadatas.append(metadata)

                # Generate embedding using litellm
                try:
                    response = litellm.embedding(
                        model="text-embedding-ada-002",  # Can be configured
                        input=[chunk_text],
                    )
                    embedding = response.data[0]["embedding"]
                    embeddings.append(embedding)
                except Exception as e:
                    self.logger.warning(f"Failed to generate embedding: {e}")
                    continue

            # Add to collection
            if embeddings:  # Only add if we have embeddings
                self.collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                    embeddings=embeddings,
                )

            return len(embeddings)

        except Exception as e:
            self.logger.warning(f"Failed to index {file_path}: {e}")
            return 0

    def _split_into_chunks(
        self, content: str, filename: str
    ) -> List[Tuple[str, Dict]]:
        """
        Split documentation into semantic chunks.

        Args:
            content: File content
            filename: Name of the file

        Returns:
            List of (chunk_text, metadata) tuples
        """
        chunks = []

        # For RST files, split by sections
        if filename.endswith(".rst"):
            # Split by section headers (lines with === or --- underlines)
            sections = re.split(r"\n([^\n]+)\n([=\-~^\"]+)\n", content)

            for i in range(0, len(sections), 3):
                if i == 0:
                    # Preamble
                    if sections[0].strip():
                        chunks.append(
                            (
                                sections[0].strip(),
                                {"section": "preamble", "title": filename},
                            )
                        )
                else:
                    # Section with title
                    if i + 1 < len(sections):
                        title = sections[i].strip()
                        content_part = (
                            sections[i + 2] if i + 2 < len(sections) else ""
                        )

                        if content_part.strip():
                            chunks.append(
                                (
                                    f"{title}\n\n{content_part.strip()}",
                                    {"section": title.lower(), "title": title},
                                )
                            )
        else:
            # For other files, split by paragraphs
            paragraphs = content.split("\n\n")
            for para in paragraphs:
                if len(para.strip()) > 100:  # Minimum chunk size
                    chunks.append(
                        (para.strip(), {"section": "paragraph", "title": filename})
                    )

        return chunks

    def retrieve_relevant_docs(
        self, query: str, issue_type: Optional[str] = None, top_k: int = 5
    ) -> List[Dict[str, str]]:
        """
        Retrieve relevant documentation for a query.

        Args:
            query: Search query (e.g., checkpatch error message)
            issue_type: Type of issue (e.g., "TRAILING_WHITESPACE")
            top_k: Number of results to return

        Returns:
            List of relevant documentation chunks with metadata
        """
        if not self.collection:
            self.logger.warning("RAG not initialized, returning empty results")
            return []

        try:
            # Enhance query with issue type
            enhanced_query = query
            if issue_type:
                enhanced_query = f"{issue_type}: {query}"

            # Generate query embedding using litellm
            try:
                response = litellm.embedding(
                    model="text-embedding-ada-002", input=[enhanced_query]
                )
                query_embedding = response.data[0]["embedding"]
            except Exception as e:
                self.logger.error(f"Failed to generate query embedding: {e}")
                return []

            # Query collection
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )

            # Format results
            docs = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    metadata = (
                        results["metadatas"][0][i] if results["metadatas"] else {}
                    )
                    distance = (
                        results["distances"][0][i] if results["distances"] else 1.0
                    )

                    docs.append(
                        {
                            "content": doc,
                            "file": metadata.get("file", "unknown"),
                            "section": metadata.get("section", ""),
                            "title": metadata.get("title", ""),
                            "relevance": 1.0 - distance,  # Convert distance to relevance
                            "priority": metadata.get("priority", False),
                        }
                    )

            return docs

        except Exception as e:
            self.logger.error(f"Failed to retrieve docs: {e}")
            return []

    def get_coding_style_guidelines(self) -> str:
        """Get general coding style guidelines."""
        docs = self.retrieve_relevant_docs(
            "coding style guidelines indentation braces formatting", top_k=3
        )
        return self._format_docs_for_prompt(docs)

    def get_checkpatch_guidelines(self, issue_types: List[str]) -> str:
        """
        Get guidelines for specific checkpatch issues.

        Args:
            issue_types: List of checkpatch issue types

        Returns:
            Formatted guidelines string
        """
        all_docs = []

        for issue_type in issue_types[:5]:  # Limit to 5 issue types
            docs = self.retrieve_relevant_docs(
                f"checkpatch {issue_type}", issue_type=issue_type, top_k=2
            )
            all_docs.extend(docs)

        # Deduplicate by file+section
        seen = set()
        unique_docs = []
        for doc in all_docs:
            key = (doc["file"], doc["section"])
            if key not in seen:
                seen.add(key)
                unique_docs.append(doc)

        return self._format_docs_for_prompt(unique_docs[:5])

    def get_sparse_guidelines(self, issue_types: List[str]) -> str:
        """
        Get guidelines for specific sparse issues.

        Args:
            issue_types: List of sparse issue types

        Returns:
            Formatted guidelines string
        """
        all_docs = []

        for issue_type in issue_types[:5]:  # Limit to 5 issue types
            docs = self.retrieve_relevant_docs(
                f"sparse {issue_type}", issue_type=issue_type, top_k=2
            )
            all_docs.extend(docs)

        # Deduplicate by file+section
        seen = set()
        unique_docs = []
        for doc in all_docs:
            key = (doc["file"], doc["section"])
            if key not in seen:
                seen.add(key)
                unique_docs.append(doc)

        return self._format_docs_for_prompt(unique_docs[:5])

    def _format_docs_for_prompt(self, docs: List[Dict[str, str]]) -> str:
        """Format retrieved docs for inclusion in LLM prompt."""
        if not docs:
            return ""

        formatted = "═══ LINUX KERNEL DOCUMENTATION REFERENCE ═══\n\n"

        for i, doc in enumerate(docs, 1):
            formatted += f"[{i}] {doc['file']}"
            if doc["title"]:
                formatted += f" - {doc['title']}"
            formatted += "\n"
            formatted += f"Relevance: {doc['relevance']:.2f}\n"
            formatted += f"{'-' * 60}\n"
            formatted += f"{doc['content']}\n"
            formatted += f"{'=' * 60}\n\n"

        return formatted

    def is_available(self) -> bool:
        """Check if RAG is available and initialized."""
        return (
            CHROMADB_AVAILABLE and LITELLM_AVAILABLE and self.collection is not None
        )