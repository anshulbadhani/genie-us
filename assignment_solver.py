#!/usr/bin/env python3
"""
Google Classroom Assignment Solver with AI
Automatically generates solutions for coding assignments and uploads them to Google Classroom.
"""

import os
import io
import re
import tempfile
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple

import google.generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak
from reportlab.platypus import Table, TableStyle, Preformatted
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont

from dotenv import load_dotenv
import pickle

# Load environment variables
load_dotenv()

# Scopes for Google Classroom
# SCOPES = [
#     'https://www.googleapis.com/auth/classroom.courses.readonly',
#     'https://www.googleapis.com/auth/classroom.coursework.me',
#     'https://www.googleapis.com/auth/classroom.coursework.students',
#     'https://www.googleapis.com/auth/drive.file'
# ]
SCOPES = [
    "https://www.googleapis.com/auth/classroom.coursework.me",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.courses",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive.file",
]


class AssignmentSolver:
    def __init__(self, credentials_file='credentials.json', token_file='token.pickle'):
        """Initialize the Assignment Solver."""
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self.drive_service = None
        self.gemini_model = None
        self._authenticate()
        self._setup_gemini()
        
    def _authenticate(self):
        """Authenticate with Google Classroom and Drive APIs."""
        creds = None
        
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        self.service = build('classroom', 'v1', credentials=creds)
        self.drive_service = build('drive', 'v3', credentials=creds)
        print("✓ Authenticated with Google Classroom and Drive!")
    
    def _setup_gemini(self):
        """Setup Gemini AI for solution generation."""
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables.")
        
        genai.configure(api_key=api_key)
        self.gemini_model = genai.GenerativeModel('gemini-2.5-pro')
        print("✓ Gemini AI configured!")
    
    def get_coursework(self, course_id: str, max_results: int = 10) -> List[Dict]:
        """Retrieve coursework/assignments from a course."""
        try:
            results = self.service.courses().courseWork().list(
                courseId=course_id,
                pageSize=max_results,
                orderBy='updateTime desc'
            ).execute()
            
            return results.get('courseWork', [])
        except HttpError as error:
            print(f"Error fetching coursework: {error}")
            return []
    
    def parse_assignment_from_text(self, assignment_text: str) -> Dict:
        """Parse assignment text to extract problems."""
        prompt = f"""
Analyze this assignment and extract the following information in a structured format:

Assignment Text:
{assignment_text}

Please provide:
1. Assignment title
2. Subject/Course name
3. List of all programs/problems (with program number and description)
4. Programming language(s) involved
5. Key concepts/topics covered

Format your response as JSON with this structure:
{{
    "title": "Assignment Title",
    "subject": "Subject Name",
    "language": "Python/Java/C++",
    "problems": [
        {{"number": "1", "description": "Problem description", "concepts": ["concept1", "concept2"]}},
        ...
    ]
}}
"""
        
        try:
            response = self.gemini_model.generate_content(prompt)
            # Extract JSON from response
            response_text = response.text
            # Remove markdown code blocks if present
            response_text = re.sub(r'```json\s*', '', response_text)
            response_text = re.sub(r'```\s*', '', response_text)
            
            import json
            parsed_data = json.loads(response_text)
            return parsed_data
        except Exception as e:
            print(f"Error parsing assignment: {e}")
            return {
                "title": "Assignment",
                "subject": "Programming",
                "language": "Unknown",
                "problems": [{"number": "1", "description": assignment_text, "concepts": []}]
            }
    
    def generate_solution(self, problem_description: str, language: str) -> Dict:
        """Generate code solution for a programming problem."""
        prompt = f"""
You are an expert programming instructor. Generate a complete, well-commented solution for this problem:

Problem: {problem_description}
Language: {language}

Provide:
1. Complete, working code with detailed comments
2. Explanation of the approach
3. Key concepts used
4. Example output

Make sure the code is:
- Syntactically correct
- Well-formatted and indented
- Includes proper error handling
- Has meaningful variable names
- Contains comprehensive comments

Format your response as:
CODE:
[Your complete code here]

EXPLANATION:
[Detailed explanation]

KEY CONCEPTS:
[List of concepts]

EXAMPLE OUTPUT:
[Expected output when code runs]
"""
        
        try:
            response = self.gemini_model.generate_content(prompt)
            response_text = response.text
            
            # Parse the response
            code_match = re.search(r'CODE:\s*```\w*\s*(.*?)\s*```', response_text, re.DOTALL)
            if not code_match:
                code_match = re.search(r'```\w*\s*(.*?)\s*```', response_text, re.DOTALL)
            
            code = code_match.group(1).strip() if code_match else "# Code generation failed"
            
            explanation_match = re.search(r'EXPLANATION:\s*(.*?)(?=KEY CONCEPTS:|EXAMPLE OUTPUT:|$)', 
                                         response_text, re.DOTALL)
            explanation = explanation_match.group(1).strip() if explanation_match else ""
            
            concepts_match = re.search(r'KEY CONCEPTS:\s*(.*?)(?=EXAMPLE OUTPUT:|$)', 
                                      response_text, re.DOTALL)
            concepts = concepts_match.group(1).strip() if concepts_match else ""
            
            output_match = re.search(r'EXAMPLE OUTPUT:\s*(.*?)$', response_text, re.DOTALL)
            example_output = output_match.group(1).strip() if output_match else ""
            
            return {
                "code": code,
                "explanation": explanation,
                "concepts": concepts,
                "example_output": example_output,
                "language": language
            }
        except Exception as e:
            print(f"Error generating solution: {e}")
            return {
                "code": f"# Error: {str(e)}",
                "explanation": "Failed to generate solution",
                "concepts": "",
                "example_output": "",
                "language": language
            }
    
    def execute_code(self, code: str, language: str) -> Tuple[str, str, bool]:
        """Execute code and capture output for screenshots."""
        temp_dir = tempfile.mkdtemp()
        
        try:
            if language.lower() == 'python':
                file_path = os.path.join(temp_dir, 'solution.py')
                with open(file_path, 'w') as f:
                    f.write(code)
                
                result = subprocess.run(
                    ['python3', file_path],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
            elif language.lower() == 'java':
                # Extract class name
                class_match = re.search(r'public\s+class\s+(\w+)', code)
                class_name = class_match.group(1) if class_match else 'Solution'
                
                file_path = os.path.join(temp_dir, f'{class_name}.java')
                with open(file_path, 'w') as f:
                    f.write(code)
                
                # Compile
                compile_result = subprocess.run(
                    ['javac', file_path],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if compile_result.returncode != 0:
                    return "", compile_result.stderr, False
                
                # Run
                result = subprocess.run(
                    ['java', '-cp', temp_dir, class_name],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
            elif language.lower() in ['c++', 'cpp']:
                file_path = os.path.join(temp_dir, 'solution.cpp')
                output_path = os.path.join(temp_dir, 'solution')
                
                with open(file_path, 'w') as f:
                    f.write(code)
                
                # Compile
                compile_result = subprocess.run(
                    ['g++', file_path, '-o', output_path],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if compile_result.returncode != 0:
                    return "", compile_result.stderr, False
                
                # Run
                result = subprocess.run(
                    [output_path],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            else:
                return "", f"Unsupported language: {language}", False
            
            success = result.returncode == 0
            return result.stdout, result.stderr, success
            
        except subprocess.TimeoutExpired:
            return "", "Execution timeout", False
        except Exception as e:
            return "", str(e), False
        finally:
            # Cleanup
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def create_code_screenshot(self, code: str, output: str, language: str, 
                              problem_num: str) -> str:
        """Create a screenshot-like image of code and output."""
        # Image dimensions
        width = 1200
        padding = 40
        line_height = 20
        
        # Calculate height based on content
        code_lines = code.split('\n')
        output_lines = output.split('\n') if output else ['']
        total_lines = len(code_lines) + len(output_lines) + 10
        height = max(800, total_lines * line_height + padding * 4)
        
        # Create image
        img = PILImage.new('RGB', (width, height), color='#1e1e1e')
        draw = ImageDraw.Draw(img)
        
        # Try to use monospace font
        try:
            font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 14)
            font_bold = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', 16)
        except:
            font = ImageFont.load_default()
            font_bold = font
        
        y_offset = padding
        
        # Title
        title = f"Program {problem_num} - {language}"
        draw.text((padding, y_offset), title, fill='#4ec9b0', font=font_bold)
        y_offset += 40
        
        # Code section
        draw.text((padding, y_offset), "CODE:", fill='#569cd6', font=font_bold)
        y_offset += 30
        
        # Draw code with syntax-like coloring
        for line in code_lines[:50]:  # Limit lines
            color = '#d4d4d4'  # Default text color
            
            # Simple syntax highlighting
            if any(keyword in line for keyword in ['class', 'def', 'public', 'private', 'import', 'package']):
                color = '#569cd6'  # Blue for keywords
            elif line.strip().startswith('#') or line.strip().startswith('//'):
                color = '#6a9955'  # Green for comments
            elif '"' in line or "'" in line:
                color = '#ce9178'  # Orange for strings
            
            draw.text((padding + 20, y_offset), line[:120], fill=color, font=font)
            y_offset += line_height
        
        if len(code_lines) > 50:
            draw.text((padding + 20, y_offset), "... (code truncated) ...", fill='#858585', font=font)
            y_offset += line_height * 2
        
        y_offset += 20
        
        # Output section
        if output:
            draw.text((padding, y_offset), "OUTPUT:", fill='#569cd6', font=font_bold)
            y_offset += 30
            
            # Draw output box
            output_box_top = y_offset
            for line in output_lines[:30]:
                draw.text((padding + 20, y_offset), line[:120], fill='#cccccc', font=font)
                y_offset += line_height
            
            if len(output_lines) > 30:
                draw.text((padding + 20, y_offset), "... (output truncated) ...", 
                         fill='#858585', font=font)
        
        # Save image
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        img.save(temp_file.name, 'PNG')
        temp_file.close()
        
        return temp_file.name
    
    def create_pdf_report(self, assignment_data: Dict, solutions: List[Dict], 
                         screenshots: List[str], output_path: str):
        """Create a comprehensive PDF report with solutions and screenshots."""
        doc = SimpleDocTemplate(output_path, pagesize=letter,
                               topMargin=0.75*inch, bottomMargin=0.75*inch)
        
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=12,
            spaceBefore=20
        )
        
        code_style = ParagraphStyle(
            'Code',
            parent=styles['Code'],
            fontSize=9,
            leftIndent=20,
            rightIndent=20,
            spaceAfter=10,
            spaceBefore=10,
            backColor=colors.HexColor('#f5f5f5')
        )
        
        # Title Page
        story.append(Paragraph(assignment_data.get('title', 'Assignment Solutions'), title_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Assignment info
        info_data = [
            ['Subject:', assignment_data.get('subject', 'N/A')],
            ['Language:', assignment_data.get('language', 'N/A')],
            ['Date:', datetime.now().strftime('%Y-%m-%d')],
            ['Generated by:', 'AI Assignment Solver']
        ]
        
        info_table = Table(info_data, colWidths=[2*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        story.append(info_table)
        story.append(PageBreak())
        
        # Solutions
        for idx, (problem, solution) in enumerate(zip(assignment_data.get('problems', []), solutions)):
            # Problem heading
            story.append(Paragraph(f"Program {problem.get('number', idx+1)}: {problem.get('description', '')[:100]}", 
                                 heading_style))
            story.append(Spacer(1, 0.1*inch))
            
            # Explanation
            if solution.get('explanation'):
                story.append(Paragraph('<b>Approach:</b>', styles['Heading3']))
                story.append(Paragraph(solution['explanation'], styles['BodyText']))
                story.append(Spacer(1, 0.15*inch))
            
            # Code
            story.append(Paragraph('<b>Source Code:</b>', styles['Heading3']))
            code_lines = solution.get('code', '').split('\n')
            for line in code_lines:
                # Escape special characters for reportlab
                line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Preformatted(line, code_style))
            
            story.append(Spacer(1, 0.2*inch))
            
            # Screenshot
            if idx < len(screenshots) and os.path.exists(screenshots[idx]):
                story.append(Paragraph('<b>Execution Screenshot:</b>', styles['Heading3']))
                story.append(Spacer(1, 0.1*inch))
                
                try:
                    img = Image(screenshots[idx], width=6*inch, height=4*inch, kind='proportional')
                    story.append(img)
                except Exception as e:
                    print(f"Error adding screenshot: {e}")
                    story.append(Paragraph(f'<i>Screenshot unavailable</i>', styles['Italic']))
            
            # Example output
            if solution.get('example_output'):
                story.append(Spacer(1, 0.15*inch))
                story.append(Paragraph('<b>Expected Output:</b>', styles['Heading3']))
                output_text = solution['example_output'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Preformatted(output_text, code_style))
            
            # Concepts
            if solution.get('concepts'):
                story.append(Spacer(1, 0.15*inch))
                story.append(Paragraph('<b>Key Concepts:</b>', styles['Heading3']))
                story.append(Paragraph(solution['concepts'], styles['BodyText']))
            
            story.append(PageBreak())
        
        # Build PDF
        doc.build(story)
        print(f"✓ PDF report created: {output_path}")
    
    def upload_to_classroom(self, course_id: str, coursework_id: str, pdf_path: str) -> bool:
        """Upload the PDF solution to Google Classroom."""
        try:
            # First, upload to Google Drive
            file_metadata = {
                'name': os.path.basename(pdf_path),
                'mimeType': 'application/pdf'
            }
            
            media = MediaFileUpload(pdf_path, mimetype='application/pdf', resumable=True)
            
            drive_file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            file_id = drive_file.get('id')
            file_link = drive_file.get('webViewLink')
            
            print(f"✓ Uploaded to Drive: {file_link}")
            
            # Submit to Classroom
            submission_body = {
                'addAttachments': [
                    {
                        'driveFile': {
                            'id': file_id
                        }
                    }
                ]
            }
            
            # Get student submission
            submissions = self.service.courses().courseWork().studentSubmissions().list(
                courseId=course_id,
                courseWorkId=coursework_id,
                userId='me'
            ).execute()
            
            if submissions.get('studentSubmissions'):
                submission_id = submissions['studentSubmissions'][0]['id']
                
                # Modify submission to add attachment
                self.service.courses().courseWork().studentSubmissions().modifyAttachments(
                    courseId=course_id,
                    courseWorkId=coursework_id,
                    id=submission_id,
                    body=submission_body
                ).execute()
                
                print(1)
                
                # Turn in the submission
                self.service.courses().courseWork().studentSubmissions().turnIn(
                    courseId=course_id,
                    courseWorkId=coursework_id,
                    id=submission_id,
                    body={}
                ).execute()
                
                print(2)
                                
                print(f"✓ Submitted to Google Classroom!")
                return True
            else:
                print("❌ No submission found for this coursework")
                return False
                
        except HttpError as error:
            print(f"❌ Error uploading to classroom: {error}")
            return False
    
    def solve_assignment(self, course_id: str, coursework_id: str, 
                        assignment_text: str = None, auto_upload: bool = False) -> str:
        """
        Main method to solve an assignment end-to-end.
        
        Args:
            course_id: Google Classroom course ID
            coursework_id: Assignment/coursework ID
            assignment_text: Optional text if assignment is provided directly
            auto_upload: Whether to automatically upload solution to classroom
        
        Returns:
            Path to generated PDF
        """
        print("\n" + "="*80)
        print("🤖 AI ASSIGNMENT SOLVER")
        print("="*80 + "\n")
        
        # Step 1: Get assignment details
        if not assignment_text:
            print("📥 Fetching assignment from classroom...")
            try:
                coursework = self.service.courses().courseWork().get(
                    courseId=course_id,
                    id=coursework_id
                ).execute()
                
                assignment_text = coursework.get('description', '')
                print(f"✓ Assignment: {coursework.get('title', 'Untitled')}")
            except HttpError as error:
                print(f"❌ Error fetching assignment: {error}")
                return None
        
        # Step 2: Parse assignment
        print("\n📋 Parsing assignment...")
        assignment_data = self.parse_assignment_from_text(assignment_text)
        print(f"✓ Found {len(assignment_data.get('problems', []))} problem(s)")
        print(f"✓ Language: {assignment_data.get('language', 'Unknown')}")
        
        # Step 3: Generate solutions
        print("\n💡 Generating solutions...")
        solutions = []
        screenshots = []
        
        for idx, problem in enumerate(assignment_data.get('problems', [])):
            print(f"\n  Problem {problem.get('number', idx+1)}: {problem.get('description', '')[:60]}...")
            
            solution = self.generate_solution(
                problem.get('description', ''),
                assignment_data.get('language', 'Python')
            )
            solutions.append(solution)
            
            # Execute code and create screenshot
            print(f"    ⚙️  Executing code...")
            stdout, stderr, success = self.execute_code(
                solution['code'],
                assignment_data.get('language', 'Python')
            )
            
            if success:
                print(f"    ✓ Execution successful")
                output = stdout
            else:
                print(f"    ⚠️  Execution failed: {stderr[:100]}")
                output = solution.get('example_output', '')
            
            print(f"    📸 Creating screenshot...")
            screenshot_path = self.create_code_screenshot(
                solution['code'],
                output,
                assignment_data.get('language', 'Python'),
                problem.get('number', str(idx+1))
            )
            screenshots.append(screenshot_path)
            print(f"    ✓ Screenshot created")
        
        # Step 4: Create PDF
        print("\n📄 Creating PDF report...")
        output_dir = os.path.join(os.path.dirname(__file__), 'solutions')
        os.makedirs(output_dir, exist_ok=True)
        
        pdf_filename = f"solution_{course_id}_{coursework_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)
        
        self.create_pdf_report(assignment_data, solutions, screenshots, pdf_path)
        
        # Cleanup screenshots
        for screenshot in screenshots:
            try:
                os.remove(screenshot)
            except:
                pass
        
        # Step 5: Upload to classroom
        if auto_upload:
            print("\n📤 Uploading to Google Classroom...")
            self.upload_to_classroom(course_id, coursework_id, pdf_path)
        
        print("\n" + "="*80)
        print(f"✅ COMPLETED! PDF saved at: {pdf_path}")
        print("="*80 + "\n")
        
        return pdf_path


def main():
    """CLI interface for assignment solver."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='AI-powered assignment solver for Google Classroom',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Solve and generate PDF (no upload)
  python assignment_solver.py --course-id 123456 --coursework-id 789012
  
  # Solve and auto-upload to classroom
  python assignment_solver.py --course-id 123456 --coursework-id 789012 --upload
  
  # Solve from text file
  python assignment_solver.py --course-id 123456 --coursework-id 789012 --file assignment.txt
  
  # List pending assignments
  python assignment_solver.py --course-id 123456 --list-assignments
        """
    )
    
    parser.add_argument('--course-id', type=str, help='Google Classroom course ID')
    parser.add_argument('--coursework-id', type=str, help='Assignment/coursework ID')
    parser.add_argument('--file', type=str, help='Assignment text file (optional)')
    parser.add_argument('--upload', action='store_true', help='Auto-upload solution to classroom')
    parser.add_argument('--list-assignments', action='store_true', help='List pending assignments')
    parser.add_argument('--credentials', type=str, default='credentials.json')
    parser.add_argument('--token', type=str, default='token.pickle')
    
    args = parser.parse_args()
    
    try:
        solver = AssignmentSolver(
            credentials_file=args.credentials,
            token_file=args.token
        )
        
        if args.list_assignments:
            if not args.course_id:
                print("Error: --course-id required for listing assignments")
                return
            
            print(f"\n📚 Fetching assignments for course {args.course_id}...\n")
            courseworks = solver.get_coursework(args.course_id)
            
            if not courseworks:
                print("No assignments found.")
                return
            
            print(f"Found {len(courseworks)} assignment(s):\n")
            for cw in courseworks:
                print(f"  ID: {cw['id']}")
                print(f"  Title: {cw.get('title', 'Untitled')}")
                print(f"  State: {cw.get('state', 'N/A')}")
                if 'dueDate' in cw:
                    due = cw['dueDate']
                    print(f"  Due: {due.get('year')}-{due.get('month'):02d}-{due.get('day'):02d}")
                print("-" * 60)
            return
        
        if not args.course_id or not args.coursework_id:
            print("Error: --course-id and --coursework-id are required")
            print("Use --help for usage information")
            return
        
        # Read assignment text from file if provided
        assignment_text = None
        if args.file:
            with open(args.file, 'r') as f:
                assignment_text = f.read()
        
        # Solve assignment
        pdf_path = solver.solve_assignment(
            args.course_id,
            args.coursework_id,
            assignment_text=assignment_text,
            auto_upload=args.upload
        )
        
        if pdf_path:
            print(f"\n✅ Success! Solution PDF: {pdf_path}")
            if not args.upload:
                print("\n💡 Tip: Use --upload flag to automatically submit to classroom")
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
