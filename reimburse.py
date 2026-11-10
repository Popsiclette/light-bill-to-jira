import base64
import html
import io
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pikepdf
import requests

TIMEZONE = ZoneInfo("America/Sao_Paulo")
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
BILL_SENDER = "faturaporemail@riodejaneiro.enel.com"
AMOUNT_PATTERN = re.compile(r"R\$\s*([\d.]+,\d{2})")
DUE_DATE_PATTERN = re.compile(r"vencimento\W*(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)


@dataclass
class Bill:
    amount: str
    due_date: date
    pdf: bytes


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing environment variable {name}")
    return value


def previous_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def parse_bill_text(text: str) -> tuple[str, date] | None:
    amount = AMOUNT_PATTERN.search(text)
    due = DUE_DATE_PATTERN.search(text)
    if not amount or not due:
        return None
    day, month, year = (int(group) for group in due.groups())
    return amount.group(1), date(year, month, day)


def unlock_pdf(pdf: bytes, password: str) -> bytes:
    output = io.BytesIO()
    with pikepdf.open(io.BytesIO(pdf), password=password) as document:
        document.save(output)
    return output.getvalue()


class Gmail:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

    def _get(self, path: str, **params) -> dict:
        response = self.session.get(f"{GMAIL_API}/{path}", params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def find_bill(self, due_year: int, due_month: int) -> Bill | None:
        query = f"from:{BILL_SENDER} has:attachment newer_than:120d"
        for reference in self._get("messages", q=query).get("messages", []):
            message = self._get(f"messages/{reference['id']}", format="full")
            parsed = parse_bill_text(self._body_text(message["payload"]))
            if not parsed:
                continue
            amount, due_date = parsed
            if (due_date.year, due_date.month) != (due_year, due_month):
                continue
            attachment_id = self._pdf_attachment_id(message["payload"])
            if not attachment_id:
                continue
            attachment = self._get(f"messages/{reference['id']}/attachments/{attachment_id}")
            return Bill(amount, due_date, base64.urlsafe_b64decode(attachment["data"]))
        return None

    def _parts(self, payload: dict):
        yield payload
        for part in payload.get("parts", []):
            yield from self._parts(part)

    def _body_text(self, payload: dict) -> str:
        bodies = {}
        for part in self._parts(payload):
            data = part.get("body", {}).get("data")
            if data and part.get("mimeType") in ("text/plain", "text/html"):
                bodies.setdefault(part["mimeType"], base64.urlsafe_b64decode(data).decode("utf-8", "replace"))
        if "text/plain" in bodies:
            return bodies["text/plain"]
        return html.unescape(re.sub(r"<[^>]+>", " ", bodies.get("text/html", "")))

    def _pdf_attachment_id(self, payload: dict) -> str | None:
        for part in self._parts(payload):
            if part.get("filename", "").lower().endswith(".pdf"):
                return part["body"].get("attachmentId")
        return None


class Jira:
    def __init__(self, cloud_id: str, email: str, token: str):
        self.base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
        self.session = requests.Session()
        self.session.auth = (email, token)
        self.session.headers["Accept"] = "application/json"

    def find_ticket_this_month(self, project: str, issue_type: str) -> str | None:
        jql = (
            f'project = {project} AND issuetype = "{issue_type}" '
            "AND reporter = currentUser() AND created >= startOfMonth()"
        )
        response = self.session.post(
            f"{self.base_url}/search/jql", json={"jql": jql, "fields": ["key"], "maxResults": 1}, timeout=30
        )
        response.raise_for_status()
        issues = response.json().get("issues", [])
        return issues[0]["key"] if issues else None

    def create_ticket(self, project: str, issue_type: str, summary: str, description: str) -> str:
        fields = {
            "project": {"key": project},
            "issuetype": {"name": issue_type},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
            },
        }
        response = self.session.post(f"{self.base_url}/issue", json={"fields": fields}, timeout=30)
        response.raise_for_status()
        return response.json()["key"]

    def attach(self, issue_key: str, filename: str, content: bytes) -> None:
        response = self.session.post(
            f"{self.base_url}/issue/{issue_key}/attachments",
            headers={"X-Atlassian-Token": "no-check"},
            files={"file": (filename, content, "application/pdf")},
            timeout=60,
        )
        response.raise_for_status()


def main() -> None:
    project = env("JIRA_PROJECT")
    issue_type = env("JIRA_ISSUE_TYPE")
    jira = Jira(env("JIRA_CLOUD_ID"), env("JIRA_EMAIL"), env("JIRA_API_TOKEN"))

    existing = jira.find_ticket_this_month(project, issue_type)
    if existing:
        print(f"Ticket for this month already exists: {existing}")
        return

    due_year, due_month = previous_month(datetime.now(TIMEZONE).date())
    gmail = Gmail(env("GMAIL_CLIENT_ID"), env("GMAIL_CLIENT_SECRET"), env("GMAIL_REFRESH_TOKEN"))
    bill = gmail.find_bill(due_year, due_month)
    if not bill:
        sys.exit(f"No Enel bill due in {due_month:02d}/{due_year} found in Gmail")

    unlocked_pdf = unlock_pdf(bill.pdf, env("PDF_PASSWORD"))
    issue_key = jira.create_ticket(
        project, issue_type, env("TICKET_SUMMARY"), f"Conta de luz no valor de R$ {bill.amount}"
    )
    jira.attach(issue_key, f"{bill.due_date.month:02d}.pdf", unlocked_pdf)
    print(f"Created {issue_key} for bill due {bill.due_date:%d/%m/%Y} (R$ {bill.amount})")


if __name__ == "__main__":
    main()
