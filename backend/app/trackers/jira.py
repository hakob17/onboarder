"""Jira Cloud connector. Auth = account email + API token (HTTP Basic).
Create a token at https://id.atlassian.com/manage-profile/security/api-tokens."""
import base64

import httpx

from .textconv import adf_to_text, text_to_adf

TIMEOUT = 25.0


class JiraClient:
    def __init__(self, base_url: str, email: str, token: str) -> None:
        self.base = base_url.rstrip("/")
        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get(self.base + path, headers=self.headers, params=params)
            r.raise_for_status()
            return r.json()

    def whoami(self) -> dict:
        """Validation call — raises httpx.HTTPStatusError on bad creds."""
        return self._get("/rest/api/3/myself")

    def issue(self, key: str) -> dict:
        data = self._get(
            f"/rest/api/3/issue/{key}",
            {"fields": "summary,description,issuetype,status,labels,comment"},
        )
        f = data.get("fields", {}) or {}
        comments = [
            adf_to_text(c.get("body"))
            for c in ((f.get("comment") or {}).get("comments") or [])
        ]
        return {
            "source": "jira",
            "key": key,
            "title": f.get("summary") or key,
            "body": adf_to_text(f.get("description")).strip(),
            "type": (f.get("issuetype") or {}).get("name"),
            "status": (f.get("status") or {}).get("name"),
            "labels": f.get("labels") or [],
            "comments": [c.strip() for c in comments if c.strip()],
            "url": f"{self.base}/browse/{key}",
        }

    def add_comment(self, key: str, text: str) -> str:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(
                f"{self.base}/rest/api/3/issue/{key}/comment",
                headers={**self.headers, "Content-Type": "application/json"},
                json={"body": text_to_adf(text)},
            )
            r.raise_for_status()
        return f"{self.base}/browse/{key}"
