"""Paper database, search, download, and wiki ingest helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .io import append_jsonl, ensure_dir, read_jsonl, slugify, utc_now, write_json, write_text
from .paths import VibePaths
from .timeline import record_event


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  authors TEXT,
  year TEXT,
  venue TEXT,
  arxiv_id TEXT,
  doi TEXT,
  source_url TEXT,
  pdf_url TEXT,
  local_pdf_path TEXT,
  sha256 TEXT,
  downloaded_at TEXT,
  ingested_at TEXT,
  status TEXT,
  confidence TEXT,
  tags TEXT,
  related_cycle_ids TEXT,
  related_run_ids TEXT,
  related_deep_request_ids TEXT,
  repo_urls TEXT,
  weight_urls TEXT,
  dataset_names TEXT,
  notes TEXT
);
"""


def db_path(paths: VibePaths) -> Path:
    return paths.research / "papers.sqlite"


def connect(paths: VibePaths) -> sqlite3.Connection:
    ensure_dir(paths.research)
    conn = sqlite3.connect(db_path(paths))
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def paper_search(paths: VibePaths, query: str, *, source: str = "arxiv", limit: int = 10, offline: bool = False, add_candidates: bool = False) -> list[dict[str, Any]]:
    if offline:
        results: list[dict[str, Any]] = []
    elif source == "arxiv":
        results = search_arxiv(query, limit=limit)
    elif source == "semantic_scholar":
        results = search_semantic_scholar(query, limit=limit)
    elif source == "openalex":
        results = search_openalex(query, limit=limit)
    elif source == "pubmed":
        results = search_pubmed(query, limit=limit)
    elif source == "github":
        results = search_github_repos(query, limit=limit)
    else:
        results = []
    append_jsonl(paths.research / "sources.jsonl", {"created_at": utc_now(), "source": source, "query": query, "results": results})
    if add_candidates:
        for row in results:
            if not row.get("error") and row.get("title"):
                add_paper(paths, {**row, "status": "candidate", "notes": f"candidate from {source} query: {query}"})
    record_event(paths, "paper_found", f"{len(results)} papers for {query}", status="searched", payload={"source": source, "query": query})
    return results


def search_arxiv(query: str, *, limit: int) -> list[dict[str, Any]]:
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": f"all:{query}", "start": 0, "max_results": limit})
    try:
        text = urllib.request.urlopen(url, timeout=20).read().decode("utf-8", errors="replace")
    except Exception as exc:
        return [{"error": str(exc), "query": query}]
    entries = text.split("<entry>")[1:]
    results = []
    for entry in entries[:limit]:
        title = between(entry, "<title>", "</title>").replace("\n", " ").strip()
        source_url = between(entry, "<id>", "</id>").strip()
        year = between(entry, "<published>", "</published>")[:4]
        pdf_url = source_url.replace("/abs/", "/pdf/") if "/abs/" in source_url else ""
        results.append({"title": title, "year": year, "source_url": source_url, "pdf_url": pdf_url, "source": "arxiv"})
    return results


def search_semantic_scholar(query: str, *, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"query": query, "limit": limit, "fields": "title,year,authors,url,openAccessPdf"})
    try:
        data = json.loads(urllib.request.urlopen(f"https://api.semanticscholar.org/graph/v1/paper/search?{params}", timeout=20).read())
    except Exception as exc:
        return [{"error": str(exc), "query": query}]
    results = []
    for row in data.get("data", [])[:limit]:
        pdf = row.get("openAccessPdf") or {}
        results.append(
            {
                "title": row.get("title", ""),
                "year": row.get("year", ""),
                "authors": ", ".join(author.get("name", "") for author in row.get("authors", [])),
                "source_url": row.get("url", ""),
                "pdf_url": pdf.get("url", ""),
                "source": "semantic_scholar",
            }
        )
    return results


def search_openalex(query: str, *, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"search": query, "per-page": limit})
    try:
        data = json.loads(urllib.request.urlopen(f"https://api.openalex.org/works?{params}", timeout=20).read())
    except Exception as exc:
        return [{"error": str(exc), "query": query}]
    results = []
    for row in data.get("results", [])[:limit]:
        loc = row.get("primary_location") or {}
        source = loc.get("source") or {}
        results.append(
            {
                "title": row.get("title", ""),
                "year": row.get("publication_year", ""),
                "venue": source.get("display_name", ""),
                "source_url": row.get("id", ""),
                "pdf_url": (loc.get("pdf_url") or ""),
                "doi": (row.get("doi") or ""),
                "source": "openalex",
            }
        )
    return results


def search_pubmed(query: str, *, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"db": "pubmed", "term": query, "retmode": "json", "retmax": limit})
    try:
        search = json.loads(urllib.request.urlopen(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}", timeout=20).read())
    except Exception as exc:
        return [{"error": str(exc), "query": query}]
    ids = search.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    summary_params = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    try:
        summary = json.loads(urllib.request.urlopen(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{summary_params}", timeout=20).read())
    except Exception as exc:
        return [{"error": str(exc), "query": query}]
    results = []
    for pmid in ids:
        row = summary.get("result", {}).get(pmid, {})
        results.append({"title": row.get("title", ""), "year": str(row.get("pubdate", ""))[:4], "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "source": "pubmed"})
    return results


def search_github_repos(query: str, *, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "per_page": limit})
    try:
        data = json.loads(urllib.request.urlopen(f"https://api.github.com/search/repositories?{params}", timeout=20).read())
    except Exception as exc:
        return [{"error": str(exc), "query": query}]
    results = []
    for row in data.get("items", [])[:limit]:
        results.append({"title": row.get("full_name", ""), "source_url": row.get("html_url", ""), "notes": row.get("description", ""), "source": "github"})
    return results


def add_paper(paths: VibePaths, metadata: dict[str, Any]) -> str:
    title = metadata.get("title") or "untitled"
    paper_id = metadata.get("paper_id") or "p_" + slugify(title, 48)
    values = {
        "paper_id": paper_id,
        "title": title,
        "authors": metadata.get("authors", ""),
        "year": str(metadata.get("year", "")),
        "venue": metadata.get("venue", ""),
        "arxiv_id": metadata.get("arxiv_id", ""),
        "doi": metadata.get("doi", ""),
        "source_url": metadata.get("source_url", ""),
        "pdf_url": metadata.get("pdf_url", ""),
        "local_pdf_path": metadata.get("local_pdf_path", ""),
        "sha256": metadata.get("sha256", ""),
        "downloaded_at": metadata.get("downloaded_at", ""),
        "ingested_at": metadata.get("ingested_at", ""),
        "status": metadata.get("status", "candidate"),
        "confidence": metadata.get("confidence", ""),
        "tags": json.dumps(metadata.get("tags", [])),
        "related_cycle_ids": json.dumps(metadata.get("related_cycle_ids", [])),
        "related_run_ids": json.dumps(metadata.get("related_run_ids", [])),
        "related_deep_request_ids": json.dumps(metadata.get("related_deep_request_ids", [])),
        "repo_urls": json.dumps(metadata.get("repo_urls", [])),
        "weight_urls": json.dumps(metadata.get("weight_urls", [])),
        "dataset_names": json.dumps(metadata.get("dataset_names", [])),
        "notes": metadata.get("notes", ""),
    }
    conn = connect(paths)
    placeholders = ",".join("?" for _ in values)
    columns = ",".join(values)
    updates = ",".join(f"{key}=excluded.{key}" for key in values if key != "paper_id")
    conn.execute(f"INSERT INTO papers ({columns}) VALUES ({placeholders}) ON CONFLICT(paper_id) DO UPDATE SET {updates}", list(values.values()))
    conn.commit()
    conn.close()
    return paper_id


def download_paper(paths: VibePaths, paper_id: str, url: str) -> dict[str, Any]:
    target = paths.research / "raw" / "papers_pdf" / f"{paper_id}.pdf"
    ensure_dir(target.parent)
    data = urllib.request.urlopen(url, timeout=60).read()
    target.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    metadata = {"paper_id": paper_id, "title": paper_id, "pdf_url": url, "local_pdf_path": str(target), "sha256": sha, "downloaded_at": utc_now(), "status": "downloaded"}
    add_paper(paths, metadata)
    record_event(paths, "paper_downloaded", paper_id, status="downloaded", payload={"sha256": sha, "path": str(target)})
    return metadata


def pdf_to_markdown(paths: VibePaths, paper_id: str) -> Path:
    pdf = paths.research / "raw" / "papers_pdf" / f"{paper_id}.pdf"
    md = paths.research / "raw" / "papers_md" / f"{paper_id}.md"
    ensure_dir(md.parent)
    text = ""
    method = "stub"
    if pdf.exists() and shutil.which("pdftotext"):
        result = subprocess.run(["pdftotext", str(pdf), "-"], text=True, capture_output=True, check=False, timeout=60)
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout
            method = "pdftotext"
    if not text:
        text = "PDF text extraction unavailable. Use the local PDF path and source metadata for agent ingest."
    write_text(md, f"# Paper Markdown: {paper_id}\n\nExtraction method: {method}\nSource PDF: {pdf}\n\n{text[:200000]}\n")
    record_event(paths, "paper_markdown_created", paper_id, status=method, payload={"path": str(md), "method": method})
    return md


def wiki_ingest_paper(paths: VibePaths, paper_id: str, notes: str = "") -> Path:
    conn = connect(paths)
    row = conn.execute("SELECT title, authors, year, source_url, pdf_url, local_pdf_path, sha256, status FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
    conn.execute("UPDATE papers SET ingested_at=?, status=? WHERE paper_id=?", (utc_now(), "ingested", paper_id))
    conn.commit()
    conn.close()
    if row:
        title, authors, year, source_url, pdf_url, local_pdf_path, sha, _status = row
        status = "ingested"
    else:
        title, authors, year, source_url, pdf_url, local_pdf_path, sha, status = paper_id, "", "", "", "", "", "", "ingested"
        add_paper(paths, {"paper_id": paper_id, "title": title, "status": "ingested", "ingested_at": utc_now()})
    md = paths.research / "raw" / "papers_md" / f"{paper_id}.md"
    if local_pdf_path and not md.exists():
        pdf_to_markdown(paths, paper_id)
    note = paths.research / "wiki" / "papers" / f"{paper_id}.md"
    write_text(
        note,
        f"""# {title}

Paper ID: `{paper_id}`
Authors: {authors}
Year: {year}
Source: {source_url}
PDF: {pdf_url}
Local PDF: {local_pdf_path}
SHA256: {sha}
Status: {status}
Markdown: {md if md.exists() else ''}

## Summary
{notes or 'Pending agent ingest.'}

## Implications
Pending synthesis update.
""",
    )
    append_wiki_page(paths.research / "wiki" / "concepts" / "paper-methods.md", paper_id, title)
    append_wiki_page(paths.research / "wiki" / "gaps" / "questions.md", paper_id, "Questions and gaps pending extraction.")
    append_wiki_page(paths.research / "wiki" / "synthesis" / "field-map.md", paper_id, title)
    with (paths.research / "wiki" / "index.md").open("a") as handle:
        handle.write(f"- [{paper_id}](papers/{paper_id}.md): {title}\n")
    with (paths.research / "wiki" / "log.md").open("a") as handle:
        handle.write(f"- {utc_now()} ingested paper {paper_id}\n")
    record_event(paths, "paper_ingested", paper_id, status="ingested", payload={"note": str(note)})
    return note


def list_papers(paths: VibePaths) -> list[dict[str, Any]]:
    conn = connect(paths)
    rows = conn.execute("SELECT paper_id,title,year,status,sha256 FROM papers ORDER BY paper_id").fetchall()
    conn.close()
    return [{"paper_id": row[0], "title": row[1], "year": row[2], "status": row[3], "sha256": row[4]} for row in rows]


def between(text: str, start: str, end: str) -> str:
    if start not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0]


def append_wiki_page(path: Path, key: str, text: str) -> None:
    ensure_dir(path.parent)
    if not path.exists():
        write_text(path, f"# {path.stem.replace('-', ' ').title()}\n\n")
    with path.open("a") as handle:
        handle.write(f"- `{key}`: {text}\n")
