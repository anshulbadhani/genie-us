#!/usr/bin/env python3
"""
Google Classroom Assignment Solver with AI (Typer CLI)
Automatically generates solutions for coding assignments and uploads them to Google Classroom.
"""

import typer
from typing import Optional
from pathlib import Path
from assignment_solver import AssignmentSolver  # your existing class module

app = typer.Typer(
    help="🤖 AI-powered Assignment Solver for Google Classroom"
)

@app.command("list")
def list_assignments(
    course_id: str = typer.Option(..., "--course-id", "-c", help="Google Classroom course ID"),
    credentials: str = typer.Option("credentials.json", help="Path to Google API credentials JSON"),
    token: str = typer.Option("token.pickle", help="Path to OAuth token pickle file"),
):
    """
    📚 List all assignments for a Google Classroom course.
    """
    solver = AssignmentSolver(credentials_file=credentials, token_file=token)
    typer.echo(f"\n📚 Fetching assignments for course {course_id}...\n")

    courseworks = solver.get_coursework(course_id)
    if not courseworks:
        typer.echo("No assignments found.")
        raise typer.Exit()

    typer.echo(f"Found {len(courseworks)} assignment(s):\n")
    for cw in courseworks:
        typer.echo(f"  ID: {cw['id']}")
        typer.echo(f"  Title: {cw.get('title', 'Untitled')}")
        typer.echo(f"  State: {cw.get('state', 'N/A')}")
        if 'dueDate' in cw:
            due = cw['dueDate']
            typer.echo(f"  Due: {due.get('year')}-{due.get('month'):02d}-{due.get('day'):02d}")
        typer.echo("-" * 60)


@app.command("solve")
def solve_assignment(
    course_id: str = typer.Option(..., "--course-id", "-c", help="Google Classroom course ID"),
    coursework_id: str = typer.Option(..., "--coursework-id", "-w", help="Assignment/coursework ID"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Assignment text file"),
    upload: bool = typer.Option(False, "--upload", "-u", help="Auto-upload solution to Google Classroom"),
    credentials: str = typer.Option("credentials.json", help="Path to Google API credentials JSON"),
    token: str = typer.Option("token.pickle", help="Path to OAuth token pickle file"),
):
    """
    💡 Solve a Google Classroom assignment and (optionally) upload the result.
    """
    solver = AssignmentSolver(credentials_file=credentials, token_file=token)
    assignment_text = None

    if file:
        assignment_text = file.read_text()
        typer.echo(f"📄 Loaded assignment from {file}")

    pdf_path = solver.solve_assignment(
        course_id=course_id,
        coursework_id=coursework_id,
        assignment_text=assignment_text,
        auto_upload=upload,
    )

    if pdf_path:
        typer.echo(f"\n✅ Success! Solution PDF: {pdf_path}")
        if not upload:
            typer.echo("\n💡 Tip: Use '--upload' to automatically submit to Classroom")


@app.command("auth")
def auth(
    credentials: str = typer.Option("credentials.json", help="Google API credentials JSON file"),
    token: str = typer.Option("token.pickle", help="OAuth token file"),
):
    """
    🔐 Run initial Google authentication flow.
    """
    solver = AssignmentSolver(credentials_file=credentials, token_file=token)
    typer.echo("✅ Authentication successful!")


if __name__ == "__main__":
    app()

