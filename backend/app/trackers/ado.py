"""Azure DevOps (Boards) connector. Auth = Personal Access Token (HTTP Basic,
empty username). Create one at https://dev.azure.com/{org}/_usersSettings/tokens
with at least Work Items (Read), and Read & Write to post comments."""
import base64

import httpx

from .textconv import html_to_text

TIMEOUT = 25.0
API = "7.0"
COMMENTS_API = "7.0-preview.3"


class AdoClient:
    def __init__(self, org: str, project: str, pat: str) -> None:
        self.org = org
        self.project = project
        self.base = f"https://dev.azure.com/{org}"
        auth = base64.b64encode(f":{pat}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    def _get(self, url: str, params: dict | None = None) -> dict:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get(url, headers=self.headers, params=params)
            r.raise_for_status()
            return r.json()

    def validate(self) -> dict:
        """Validation call — confirms the PAT can read the project."""
        return self._get(f"{self.base}/_apis/projects/{self.project}", {"api-version": API})

    def work_item(self, wid: str) -> dict:
        data = self._get(
            f"{self.base}/{self.project}/_apis/wit/workitems/{wid}",
            {"$expand": "all", "api-version": API},
        )
        f = data.get("fields", {}) or {}
        body = html_to_text(f.get("System.Description", ""))
        repro = html_to_text(f.get("Microsoft.VSTS.TCM.ReproSteps", ""))
        full = body + (f"\n\nRepro steps:\n{repro}" if repro else "")
        tags = f.get("System.Tags") or ""
        return {
            "source": "ado",
            "key": str(wid),
            "title": f.get("System.Title") or f"#{wid}",
            "body": full.strip(),
            "type": f.get("System.WorkItemType"),
            "status": f.get("System.State"),
            "labels": [t.strip() for t in tags.split(";") if t.strip()],
            "comments": self._comments(wid),
            "url": f"{self.base}/{self.project}/_workitems/edit/{wid}",
        }

    def _comments(self, wid: str) -> list[str]:
        try:
            data = self._get(
                f"{self.base}/{self.project}/_apis/wit/workItems/{wid}/comments",
                {"api-version": COMMENTS_API},
            )
        except httpx.HTTPStatusError:
            return []
        out = [html_to_text(c.get("text", "")) for c in (data.get("comments") or [])]
        return [c for c in out if c]

    def add_comment(self, wid: str, text: str) -> str:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(
                f"{self.base}/{self.project}/_apis/wit/workItems/{wid}/comments",
                headers={**self.headers, "Content-Type": "application/json"},
                params={"api-version": COMMENTS_API},
                json={"text": text},
            )
            r.raise_for_status()
        return f"{self.base}/{self.project}/_workitems/edit/{wid}"
