from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests


class GrobidClient:
    def __init__(self, base_url: str, timeout: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def healthcheck(self) -> None:
        url = f"{self.base_url}/api/isalive"
        resp = requests.get(url, timeout=self.timeout)
        if resp.status_code != 200 or "true" not in resp.text.lower():
            raise RuntimeError(f"GROBID healthcheck failed: {resp.status_code} {resp.text[:120]}")

    def process_fulltext(self, pdf_path: Path) -> dict:
        url = f"{self.base_url}/api/processFulltextDocument"
        with pdf_path.open("rb") as f:
            files = {"input": (pdf_path.name, f, "application/pdf")}
            data = {"consolidateCitations": "1", "includeRawCitations": "1"}
            resp = requests.post(url, files=files, data=data, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"GROBID process failed: {resp.status_code} {resp.text[:300]}")
        return self._parse_tei(resp.text)

    def _parse_tei(self, tei_xml: str) -> dict:
        root = ET.fromstring(tei_xml)
        ns = {"tei": "http://www.tei-c.org/ns/1.0"}
        sections: list[dict] = []
        for div in root.findall(".//tei:text/tei:body/tei:div", ns):
            head = div.find("tei:head", ns)
            title = "".join(head.itertext()).strip() if head is not None else ""
            content = " ".join(t.strip() for t in div.itertext() if t and t.strip())
            if content:
                sections.append({"title": title, "text": re.sub(r"\s+", " ", content)})

        bibliography: list[dict] = []
        for bibl in root.findall(".//tei:listBibl/tei:biblStruct", ns):
            rid = bibl.attrib.get("{http://www.w3.org/XML/1998/namespace}id") or bibl.attrib.get("id")
            title_node = bibl.find(".//tei:title", ns)
            title = "".join(title_node.itertext()).strip() if title_node is not None else None
            date_node = bibl.find(".//tei:imprint/tei:date", ns)
            year = None
            if date_node is not None:
                when = date_node.attrib.get("when") or "".join(date_node.itertext())
                m = re.search(r"(19|20)\d{2}", when or "")
                if m:
                    year = int(m.group(0))
            raw = " ".join(t.strip() for t in bibl.itertext() if t and t.strip())
            bibliography.append({"id": rid, "title": title, "year": year, "raw": re.sub(r"\s+", " ", raw)})
        return {"sections": sections, "bibliography": bibliography}
