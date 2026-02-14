"""
Reference document tagging and content extraction for meetings.

Tag PDFs, text files, Google Doc content, or notes to specific meeting
categories so the AI can use them when generating prep briefs. No fluff —
only relevant info gets injected, in the order you specify. Redundancy
can be detected and removed.

Examples:
    - Tag "networking_tips.pdf" to all NETWORKING meetings
    - Tag "interview_prep.txt" to all INTERVIEW meetings
    - Add pasted Google Doc content with add_inline_doc(category, content, label)
    - Reorder docs with set_category_order() so the right info appears first

Storage:
    reference_docs.json - maps doc paths/inline IDs to meeting categories/IDs.
    Each doc has an optional "order" (int; lower = first). Inline docs store
    content in the JSON.

Supported formats:
    - .txt, .md  -> read directly
    - .pdf       -> extract text via PyPDF2
    - Google Docs -> paste as .txt file or use add_inline_doc()
"""

import json
import logging
import re
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

DEFAULT_DOCS_PATH = "./reference_docs.json"
INLINE_PREFIX = "inline:"


class ReferenceDocsStore:
    """
    Manages reference documents tagged to meeting categories or specific meetings.

    Documents are tagged by category (interview, networking, etc.) or by
    specific meeting ID. When generating a brief, relevant docs are pulled
    and their content is injected into the AI prompt.
    """

    def __init__(self, store_path: str = DEFAULT_DOCS_PATH):
        self.store_path = Path(store_path)
        self._ensure_store_exists()

    def _ensure_store_exists(self) -> None:
        if not self.store_path.exists():
            self.store_path.write_text(json.dumps({"by_category": {}, "by_meeting": {}}, indent=2))

    def _load(self) -> dict:
        try:
            data = json.loads(self.store_path.read_text())
            if "by_category" not in data:
                data["by_category"] = {}
            if "by_meeting" not in data:
                data["by_meeting"] = {}
            return data
        except (json.JSONDecodeError, IOError):
            return {"by_category": {}, "by_meeting": {}}

    def _save(self, data: dict) -> None:
        self.store_path.write_text(json.dumps(data, indent=2))

    def tag_to_category(self, file_path: str, category: str, label: Optional[str] = None) -> bool:
        """
        Tag a document to a meeting category.

        Args:
            file_path: Path to the document (PDF, txt, md)
            category: Meeting category (interview, networking, client, etc.)
            label: Optional short label describing what this doc is about

        Returns:
            True if tagged successfully
        """
        path = Path(file_path)
        if not path.exists():
            logger.error("File not found: %s", file_path)
            return False

        data = self._load()
        category = category.lower()

        if category not in data["by_category"]:
            data["by_category"][category] = []

        # Don't duplicate
        resolved = str(path.resolve())
        existing_paths = [d["path"] for d in data["by_category"][category]]
        if resolved in existing_paths:
            logger.info("Doc already tagged to %s: %s", category, file_path)
            return True

        next_order = self._next_order_for_category(data, category)
        data["by_category"][category].append({
            "path": resolved,
            "label": label or path.stem.replace("_", " ").replace("-", " "),
            "filename": path.name,
            "order": next_order,
        })
        self._save(data)
        logger.info("Tagged %s -> %s", path.name, category)
        return True

    def tag_to_meeting(self, file_path: str, meeting_id: str, label: Optional[str] = None) -> bool:
        """Tag a document to a specific meeting by ID."""
        path = Path(file_path)
        if not path.exists():
            logger.error("File not found: %s", file_path)
            return False

        data = self._load()
        if meeting_id not in data["by_meeting"]:
            data["by_meeting"][meeting_id] = []

        existing_paths = [d["path"] for d in data["by_meeting"][meeting_id]]
        if str(path.resolve()) in existing_paths:
            return True

        next_order = self._next_order_for_meeting(data, meeting_id)
        data["by_meeting"][meeting_id].append({
            "path": str(path.resolve()),
            "label": label or path.stem.replace("_", " ").replace("-", " "),
            "filename": path.name,
            "order": next_order,
        })
        self._save(data)
        return True

    def _next_order_for_category(self, data: dict, category: str) -> int:
        docs = data["by_category"].get(category, [])
        if not docs:
            return 0
        orders = [d.get("order", i) for i, d in enumerate(docs)]
        return max(orders) + 1

    def _next_order_for_meeting(self, data: dict, meeting_id: str) -> int:
        docs = data["by_meeting"].get(meeting_id, [])
        if not docs:
            return 0
        orders = [d.get("order", i) for i, d in enumerate(docs)]
        return max(orders) + 1

    def add_inline_doc(
        self,
        category: str,
        content: str,
        label: Optional[str] = None,
    ) -> str:
        """
        Add pasted content (e.g. from a Google Doc) as a reference doc.
        No file path; content is stored in JSON. Returns the doc id (inline:xxx).
        """
        data = self._load()
        category = category.lower()
        if category not in data["by_category"]:
            data["by_category"][category] = []

        doc_id = f"{INLINE_PREFIX}{uuid.uuid4().hex[:12]}"
        next_order = self._next_order_for_category(data, category)
        # Normalize: strip fluff, collapse whitespace
        clean_content = re.sub(r"\s+", " ", content.strip())[:50000]
        data["by_category"][category].append({
            "path": doc_id,
            "label": label or "Pasted notes",
            "filename": f"{label or 'inline'}.txt",
            "order": next_order,
            "content": clean_content,
        })
        self._save(data)
        logger.info("Added inline doc -> %s", category)
        return doc_id

    def get_docs_for_category(self, category: str) -> List[Dict[str, Any]]:
        """Get all docs tagged to a category, sorted by order (no fluff order)."""
        data = self._load()
        docs = data["by_category"].get(category.lower(), [])
        # Normalize order if missing (legacy entries)
        for i, d in enumerate(docs):
            if "order" not in d:
                d["order"] = i
        return sorted(docs, key=lambda d: d.get("order", 0))

    def get_docs_for_meeting(self, meeting_id: str) -> List[Dict[str, Any]]:
        """Get all docs tagged to a specific meeting (with order normalized)."""
        data = self._load()
        docs = data["by_meeting"].get(meeting_id, [])
        for i, d in enumerate(docs):
            if "order" not in d:
                d["order"] = i
        return sorted(docs, key=lambda d: d.get("order", 0))

    def get_relevant_docs(self, category: str, meeting_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all relevant docs for a meeting (by category + by specific ID),
        in the right order. Deduplicates by path/id. Category docs first (sorted
        by order), then meeting-specific docs.
        """
        docs = []
        seen = set()

        for doc in self.get_docs_for_category(category):
            if doc["path"] not in seen:
                docs.append(doc)
                seen.add(doc["path"])

        if meeting_id:
            meeting_docs = self.get_docs_for_meeting(meeting_id)
            for i, d in enumerate(meeting_docs):
                if "order" not in d:
                    d["order"] = i
            for doc in sorted(meeting_docs, key=lambda d: d.get("order", 0)):
                if doc["path"] not in seen:
                    docs.append(doc)
                    seen.add(doc["path"])

        return docs

    def extract_content(self, doc: Dict[str, Any], max_chars: int = 2000) -> str:
        """
        Extract text content from a document (file or inline).
        No fluff: truncates to max_chars and cuts at sentence boundary.
        """
        path_val = doc.get("path", "")

        # Inline doc: content stored in the doc
        if path_val.startswith(INLINE_PREFIX) and doc.get("content"):
            content = doc["content"]
            if len(content) > max_chars:
                content = content[:max_chars]
                last_period = content.rfind(".")
                if last_period > max_chars * 0.7:
                    content = content[:last_period + 1]
                content += "\n[...truncated]"
            return content.strip()

        path = Path(path_val)
        if not path.exists():
            return f"[Document not found: {doc.get('filename', path_val)}]"

        try:
            suffix = path.suffix.lower()
            if suffix in (".txt", ".md"):
                content = path.read_text(encoding="utf-8")
            elif suffix == ".pdf":
                content = self._extract_pdf_text(path)
            else:
                content = path.read_text(encoding="utf-8")

            if len(content) > max_chars:
                content = content[:max_chars]
                last_period = content.rfind(".")
                if last_period > max_chars * 0.7:
                    content = content[:last_period + 1]
                content += "\n[...truncated]"
            return content.strip()
        except Exception as e:
            logger.warning("Failed to extract content from %s: %s", doc.get("filename", path_val), e)
            return f"[Could not read: {doc.get('filename', path_val)}]"

    @staticmethod
    def _extract_pdf_text(path: Path) -> str:
        """
        Extract text from a PDF file.

        Uses a simple approach - tries PyPDF2 if available, otherwise
        returns a note that the user should convert to txt.
        """
        try:
            import PyPDF2
            text_parts = []
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages[:10]:  # max 10 pages
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n".join(text_parts)
        except ImportError:
            # PyPDF2 not installed - try basic extraction or ask user
            return f"[PDF file: {path.name} - install PyPDF2 to extract text, or save as .txt]"
        except Exception as e:
            return f"[Could not read PDF: {e}]"

    def set_category_order(self, category: str, ordered_paths_or_ids: List[str]) -> bool:
        """
        Set the order of docs in a category. Pass paths or inline ids in the
        order you want (first = highest priority, no fluff order).
        """
        data = self._load()
        cat = category.lower()
        if cat not in data["by_category"]:
            return False
        docs = data["by_category"][cat]
        # Resolve paths to canonical form for matching
        path_to_doc = {}
        for d in docs:
            key = d["path"]
            if key.startswith(INLINE_PREFIX):
                path_to_doc[key] = d
            else:
                path_to_doc[str(Path(key).resolve())] = d
        ordered_docs = []
        for i, path_or_id in enumerate(ordered_paths_or_ids):
            resolved = path_or_id if path_or_id.startswith(INLINE_PREFIX) else str(Path(path_or_id).resolve())
            if resolved in path_to_doc:
                path_to_doc[resolved]["order"] = i
                ordered_docs.append(path_to_doc[resolved])
        # Any not in the list get order at end
        for d in docs:
            if d not in ordered_docs:
                d["order"] = len(ordered_docs)
                ordered_docs.append(d)
        data["by_category"][cat] = sorted(ordered_docs, key=lambda x: x.get("order", 0))
        self._save(data)
        return True

    def detect_redundancy(
        self,
        category: Optional[str] = None,
        similarity_threshold: float = 0.6,
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any], float]]:
        """
        Find pairs of docs in a category (or all categories) that have
        similar content so you can remove redundancy. Returns list of
        (doc1, doc2, similarity 0-1). Purely heuristic (word overlap).
        """
        def _normalize(t: str) -> str:
            return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", t.lower()))

        def _word_set(t: str) -> set:
            return set(_normalize(t).split())

        def _similarity(a: str, b: str) -> float:
            if not a or not b:
                return 0.0
            wa, wb = _word_set(a), _word_set(b)
            if not wa or not wb:
                return 0.0
            return len(wa & wb) / min(len(wa), len(wb))

        data = self._load()
        categories = [category.lower()] if category else list(data["by_category"].keys())
        pairs = []

        for cat in categories:
            docs = self.get_docs_for_category(cat)
            contents = []
            for d in docs:
                c = self.extract_content(d, max_chars=3000)
                if c and not c.startswith("["):
                    contents.append((d, c))
            for i in range(len(contents)):
                for j in range(i + 1, len(contents)):
                    d1, c1 = contents[i]
                    d2, c2 = contents[j]
                    sim = _similarity(c1, c2)
                    if sim >= similarity_threshold:
                        pairs.append((d1, d2, sim))
        return pairs

    def list_all(self) -> Dict[str, Any]:
        """List all tagged documents (with order)."""
        return self._load()

    def remove_doc(self, file_path_or_id: str) -> bool:
        """Remove a document from all tags. Accepts file path or inline id (e.g. inline:abc123)."""
        if file_path_or_id.startswith(INLINE_PREFIX):
            resolved = file_path_or_id
        else:
            resolved = str(Path(file_path_or_id).resolve())
        data = self._load()
        found = False

        for cat in list(data["by_category"].keys()):
            before = len(data["by_category"][cat])
            data["by_category"][cat] = [
                d for d in data["by_category"][cat] if d["path"] != resolved
            ]
            if len(data["by_category"][cat]) < before:
                found = True

        for meeting_id in data["by_meeting"]:
            before = len(data["by_meeting"][meeting_id])
            data["by_meeting"][meeting_id] = [
                d for d in data["by_meeting"][meeting_id] if d["path"] != resolved
            ]
            if len(data["by_meeting"][meeting_id]) < before:
                found = True

        if found:
            self._save(data)
        return found
