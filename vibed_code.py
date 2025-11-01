#!/usr/bin/env python3
"""
Google Classroom Announcement Monitor (Typer Version)
======================================================

This CLI connects to the Google Classroom API to retrieve announcements
and summarizes them *per course* using Google’s Gemini API.

Features:
----------
• OAuth2 authentication with Google Classroom.
• Fetches announcements and optionally filters by time window.
• Summarizes *all* announcements per course.
• Supports multiple commands via Typer.

Setup:
-------
1. Enable Google Classroom & Drive APIs in Google Cloud Console.
2. Download OAuth credentials.json.
3. Install dependencies:
   pip install google-auth google-auth-oauthlib google-api-python-client google-generativeai python-dotenv typer rich
4. Create a .env file with:
   GEMINI_API_KEY=your_api_key_here
5. Run:
   python classroom_monitor.py summarize --all-courses --since 24
"""

import os
import pickle
from datetime import datetime, timedelta
import typer
from rich import print
from rich.console import Console

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import google.generativeai as genai
from dotenv import load_dotenv

# ---------------------- Setup ----------------------
app = typer.Typer(help="Monitor and summarize Google Classroom announcements with Gemini AI.")
console = Console()
load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.announcements.readonly'
]


# ---------------------- Core Class ----------------------
class ClassroomMonitor:
    def __init__(self, credentials_file='credentials.json', token_file='token.pickle'):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self.gemini_model = None
        self._authenticate()
        self._setup_gemini()

    def _authenticate(self):
        """Authenticate with Google Classroom API."""
        creds = None
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                console.print("[yellow]Refreshing expired credentials...[/yellow]")
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Credentials file '{self.credentials_file}' not found. "
                        "Download it from Google Cloud Console and name it 'credentials.json'."
                    )
                console.print("[cyan]Authenticating with Google Classroom...[/cyan]")
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)
            console.print("[green]✓ Authentication successful![/green]")

        self.service = build('classroom', 'v1', credentials=creds)

    def _setup_gemini(self):
        """Setup Gemini AI."""
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("Missing GEMINI_API_KEY in environment variables (.env file).")
        genai.configure(api_key=api_key)
        self.gemini_model = genai.GenerativeModel('models/gemini-2.5-flash')
        console.print("[green]✓ Gemini AI configured![/green]")

    def get_courses(self):
        """Fetch available Google Classroom courses."""
        try:
            results = self.service.courses().list(pageSize=100).execute()
            return results.get('courses', [])
        except HttpError as e:
            console.print(f"[red]⚠️ Error fetching courses:[/red] {e}")
            return []

    def get_announcements(self, course_id, max_results=10, since_hours=None):
        """Retrieve course announcements."""
        try:
            announcements, page_token = [], None
            while True:
                response = self.service.courses().announcements().list(
                    courseId=course_id,
                    pageSize=min(max_results, 100),
                    pageToken=page_token,
                    orderBy='updateTime desc'
                ).execute()

                items = response.get('announcements', [])
                if since_hours:
                    cutoff = datetime.now() - timedelta(hours=since_hours)
                    items = [i for i in items if self._parse_timestamp(i.get('updateTime')) > cutoff]

                announcements.extend(items)
                page_token = response.get('nextPageToken')
                if not page_token or len(announcements) >= max_results:
                    break

            return announcements[:max_results]
        except HttpError as e:
            console.print(f"[red]⚠️ Error fetching announcements:[/red] {e}")
            return []

    def _parse_timestamp(self, ts: str):
        if not ts:
            return datetime.min
        ts = ts.replace('Z', '+00:00')
        try:
            return datetime.fromisoformat(ts.replace('+00:00', ''))
        except Exception:
            return datetime.min

    def summarize_course_announcements(self, course_name, announcements):
        """Summarize all announcements in a single Gemini summary."""
        if not announcements:
            return "No recent announcements to summarize."

        compiled_texts = []
        for ann in announcements:
            timestamp = self._parse_timestamp(ann.get('updateTime', '')).strftime("%Y-%m-%d %H:%M")
            text = ann.get('text', '').strip() or 'No content.'
            compiled_texts.append(f"[{timestamp}] {text}")

        prompt = f"""
You are a helpful assistant summarizing all recent announcements for a course.

Course: {course_name}

Announcements:
{chr(10).join(compiled_texts)}

Provide a concise, student-friendly summary including:
- Main topics or updates
- Deadlines or key info
- Context or instructions

Do not bold the text.
"""
        try:
            response = self.gemini_model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"⚠️ Error generating summary: {str(e)}"


# ---------------------- Typer Commands ----------------------

@app.command()
def list_courses(
    credentials: str = typer.Option("credentials.json", help="Path to credentials file"),
    token: str = typer.Option("token.pickle", help="Path to saved token file"),
):
    """List all available Google Classroom courses."""
    console.print("📚 [bold]Fetching your courses...[/bold]\n")
    monitor = ClassroomMonitor(credentials_file=credentials, token_file=token)
    courses = monitor.get_courses()
    if not courses:
        console.print("No courses found.")
        raise typer.Exit()
    for c in courses:
        console.print(f"• [green]{c['name']}[/green] (ID: {c['id']})")


@app.command()
def summarize(
    course_id: str = typer.Option(None, help="Specific course ID to summarize."),
    all_courses: bool = typer.Option(False, "--all-courses", help="Summarize all available courses."),
    max: int = typer.Option(10, help="Max announcements per course."),
    since: int = typer.Option(None, help="Only include announcements from last N hours."),
    no_summary: bool = typer.Option(False, help="Disable AI summarization."),
    credentials: str = typer.Option("credentials.json", help="Path to credentials file."),
    token: str = typer.Option("token.pickle", help="Path to saved token file.")
):
    """Fetch and summarize Google Classroom announcements per course."""
    console.print("🚀 [bold]Initializing Google Classroom Monitor...[/bold]")
    monitor = ClassroomMonitor(credentials_file=credentials, token_file=token)
    print()

    # Determine which courses to process
    if course_id:
        courses = [{'id': course_id, 'name': f'Course {course_id}'}]
    elif all_courses:
        courses = monitor.get_courses()
        if not courses:
            console.print("[red]No courses found.[/red]")
            raise typer.Exit()
    else:
        console.print("[yellow]❗ Please specify either --course-id or --all-courses.[/yellow]")
        raise typer.Exit()

    total = 0
    for course in courses:
        console.rule(f"[bold blue]🔍 {course['name']} (ID: {course['id']})[/bold blue]")
        anns = monitor.get_announcements(course['id'], max_results=max, since_hours=since)
        if not anns:
            console.print("No announcements found.\n")
            continue

        total += len(anns)
        console.print(f"📢 Found [green]{len(anns)}[/green] announcement(s):\n")
        for i, ann in enumerate(anns, start=1):
            timestamp = monitor._parse_timestamp(ann.get('updateTime')).strftime("%Y-%m-%d %H:%M")
            console.print(f"{i}. [{timestamp}] {ann.get('text', 'No content').strip()}")

        if not no_summary:
            console.print("\n🤖 [cyan]Generating overall course summary...[/cyan]\n")
            summary = monitor.summarize_course_announcements(course['name'], anns)
            console.print(f"[bold white]📘 COURSE SUMMARY:[/bold white]\n\n{summary}\n")

    console.print(f"\n✅ Completed! Processed [bold]{total}[/bold] announcements total.\n")


# ---------------------- Main ----------------------
if __name__ == "__main__":
    app()
