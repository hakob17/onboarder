"""Issue-tracker integration: fetch a Jira/ADO ticket as a normalized dict, and
post a comment back. Credentials live in the same settings table as the API key.

A normalized ticket is a plain dict:
    {source, key, title, body, type, status, labels[], comments[], url}
"""
from ..db import delete_setting, get_setting, set_setting
from .ado import AdoClient
from .jira import JiraClient

# settings keys
JIRA_BASE = "jira_base_url"
JIRA_EMAIL = "jira_email"
JIRA_TOKEN = "jira_api_token"
ADO_ORG = "ado_org"
ADO_PROJECT = "ado_project"
ADO_PAT = "ado_pat"


def jira_client() -> JiraClient | None:
    base, email, token = get_setting(JIRA_BASE), get_setting(JIRA_EMAIL), get_setting(JIRA_TOKEN)
    if base and email and token:
        return JiraClient(base, email, token)
    return None


def ado_client() -> AdoClient | None:
    org, project, pat = get_setting(ADO_ORG), get_setting(ADO_PROJECT), get_setting(ADO_PAT)
    if org and project and pat:
        return AdoClient(org, project, pat)
    return None


def save_jira(base_url: str, email: str, token: str) -> None:
    set_setting(JIRA_BASE, base_url.rstrip("/"))
    set_setting(JIRA_EMAIL, email)
    set_setting(JIRA_TOKEN, token)


def save_ado(org: str, project: str, pat: str) -> None:
    set_setting(ADO_ORG, org)
    set_setting(ADO_PROJECT, project)
    set_setting(ADO_PAT, pat)


def clear_jira() -> None:
    for k in (JIRA_BASE, JIRA_EMAIL, JIRA_TOKEN):
        delete_setting(k)


def clear_ado() -> None:
    for k in (ADO_ORG, ADO_PROJECT, ADO_PAT):
        delete_setting(k)


def status() -> dict:
    return {
        "jira": {
            "configured": jira_client() is not None,
            "base_url": get_setting(JIRA_BASE),
            "email": get_setting(JIRA_EMAIL),
        },
        "ado": {
            "configured": ado_client() is not None,
            "org": get_setting(ADO_ORG),
            "project": get_setting(ADO_PROJECT),
        },
    }


def get_ticket(source: str, key: str) -> dict:
    """Fetch and normalize a ticket. Raises LookupError if the tracker isn't configured."""
    if source == "jira":
        client = jira_client()
        if client is None:
            raise LookupError("Jira is not configured")
        return client.issue(key)
    if source == "ado":
        client = ado_client()
        if client is None:
            raise LookupError("Azure DevOps is not configured")
        return client.work_item(key)
    raise ValueError(f"unknown tracker source: {source}")


def post_comment(source: str, key: str, text: str) -> str:
    """Post a comment back to the ticket; returns the ticket URL."""
    if source == "jira":
        client = jira_client()
        if client is None:
            raise LookupError("Jira is not configured")
        return client.add_comment(key, text)
    if source == "ado":
        client = ado_client()
        if client is None:
            raise LookupError("Azure DevOps is not configured")
        return client.add_comment(key, text)
    raise ValueError(f"unknown tracker source: {source}")


def ticket_to_prompt(ticket: dict) -> str:
    """Render a normalized ticket as the seed message for the fix agent."""
    lines = [
        f"TICKET {ticket.get('source', '').upper()} {ticket.get('key', '')}: {ticket.get('title', '')}",
    ]
    meta = [x for x in (ticket.get("type"), ticket.get("status")) if x]
    if meta:
        lines.append("(" + " · ".join(meta) + ")")
    if ticket.get("labels"):
        lines.append("Labels: " + ", ".join(ticket["labels"]))
    lines.append("\nDescription:\n" + (ticket.get("body") or "(no description)"))
    comments = ticket.get("comments") or []
    if comments:
        lines.append("\nComments:")
        for i, c in enumerate(comments[:10], 1):
            lines.append(f"[{i}] {c}")
    return "\n".join(lines)
