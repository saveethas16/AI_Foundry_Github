import os
import sys
import json
from openai import AzureOpenAI
import requests

# Azure AI Foundry configuration
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2024-08-01-preview"
)

deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT")
github_token = os.getenv("GITHUB_TOKEN")
pr_number = os.getenv("PR_NUMBER")
repo_name = os.getenv("REPO_NAME")

def get_changed_files():
    """Read the list of changed files"""
    try:
        with open('changed_files.txt', 'r') as f:
            files = [line.strip() for line in f if line.strip()]
        return files
    except FileNotFoundError:
        print("No changed_files.txt found")
        return []

def read_file_content(filepath):
    """Read content of a file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # Limit file size for analysis
            if len(content) > 10000:
                return content[:10000] + "\n... [File truncated for analysis]"
            return content
    except Exception as e:
        return f"Error reading file: {str(e)}"

def analyze_code_with_ai(file_path, content):
    """Use Azure AI Foundry to analyze code syntax"""
    
    file_extension = os.path.splitext(file_path)[1]
    
    prompt = f"""You are an expert code reviewer. Analyze the following code for syntax errors, bugs, and code quality issues.

File: {file_path}
Extension: {file_extension}

Code:
```
{content}
```

Provide a thorough analysis including:
1. Syntax errors (if any)
2. Potential bugs or runtime issues
3. Code quality and best practice suggestions
4. Security concerns (if applicable)

IMPORTANT: Format your response as valid JSON with this exact structure:
{{
    "status": "APPROVED",
    "issues": [],
    "summary": "Brief overall assessment"
}}

OR if there are issues:

{{
    "status": "NEEDS_CHANGES",
    "issues": [
        {{"line": 10, "severity": "error", "message": "Missing closing parenthesis"}},
        {{"line": 15, "severity": "warning", "message": "Variable 'x' is unused"}}
    ],
    "summary": "Found X issues that need attention"
}}

Severity levels: "error" (must fix), "warning" (should fix), "info" (suggestion)
"""

    try:
        print(f"Analyzing {file_path} with Azure AI...")
        
        response = client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": "You are a helpful code review assistant. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )
        
        result = response.choices[0].message.content
        print(f"Raw AI response: {result[:200]}...")
        
        # Extract JSON from response
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0].strip()
        elif "```" in result:
            result = result.split("```")[1].split("```")[0].strip()
        
        # Parse JSON
        parsed_result = json.loads(result)
        return parsed_result
        
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {str(e)}")
        print(f"Response was: {result}")
        return {
            "status": "NEEDS_CHANGES",
            "issues": [{"line": 0, "severity": "error", "message": f"AI response parsing failed: {str(e)}"}],
            "summary": "Unable to parse AI analysis"
        }
    except Exception as e:
        print(f"Error analyzing code: {str(e)}")
        return {
            "status": "NEEDS_CHANGES",
            "issues": [{"line": 0, "severity": "error", "message": f"AI analysis failed: {str(e)}"}],
            "summary": "Analysis error occurred"
        }

def post_pr_comment(comment_body):
    """Post a comment on the PR"""
    url = f"https://api.github.com/repos/{repo_name}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        response = requests.post(url, headers=headers, json={"body": comment_body})
        if response.status_code == 201:
            print("✓ Comment posted successfully")
            return True
        else:
            print(f"✗ Failed to post comment: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"Error posting comment: {str(e)}")
        return False

def main():
    print("=" * 60)
    print("AI Code Syntax Checker - Starting Analysis")
    print("=" * 60)
    
    # Verify environment variables
    if not all([deployment_name, github_token, pr_number, repo_name]):
        print("ERROR: Missing required environment variables")
        print(f"Deployment: {deployment_name}")
        print(f"PR Number: {pr_number}")
        print(f"Repo: {repo_name}")
        sys.exit(1)
    
    changed_files = get_changed_files()
    
    if not changed_files:
        print("No files changed in this PR")
        comment = "## 🤖 AI Code Review\n\n✅ No code files to review in this PR."
        post_pr_comment(comment)
        
        # Write approval status
        with open('approval_status.txt', 'w') as f:
            f.write('approved')
        sys.exit(0)
    
    print(f"\nFound {len(changed_files)} changed file(s)")
    
    # Code file extensions to analyze
    code_extensions = ['.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', 
                      '.go', '.rs', '.php', '.rb', '.cs', '.swift', '.kt', '.scala']
    
    all_results = []
    overall_status = "APPROVED"
    
    # Analyze each changed file
    for file_path in changed_files:
        # Skip non-code files
        file_ext = os.path.splitext(file_path)[1]
        if file_ext not in code_extensions:
            print(f"⊘ Skipping {file_path} (not a code file)")
            continue
        
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"⚠ File not found: {file_path}")
            continue
            
        print(f"\n{'=' * 60}")
        print(f"Analyzing: {file_path}")
        print(f"{'=' * 60}")
        
        content = read_file_content(file_path)
        
        if content.startswith("Error"):
            print(f"✗ {content}")
            continue
            
        result = analyze_code_with_ai(file_path, content)
        all_results.append({
            "file": file_path,
            "result": result
        })
        
        if result["status"] == "NEEDS_CHANGES":
            overall_status = "NEEDS_CHANGES"
            print(f"✗ Issues found in {file_path}")
        else:
            print(f"✓ {file_path} looks good")
    
    if not all_results:
        print("\n⚠ No code files were analyzed")
        comment = "## 🤖 AI Code Review\n\n✅ No code files to review in this PR."
        post_pr_comment(comment)
        
        with open('approval_status.txt', 'w') as f:
            f.write('approved')
        sys.exit(0)
    
    # Generate PR comment
    print(f"\n{'=' * 60}")
    print("Generating PR comment...")
    print(f"{'=' * 60}")
    
    comment = "## 🤖 AI Code Review Results\n\n"
    comment += f"**Analyzed {len(all_results)} file(s)**\n\n"
    comment += "---\n\n"
    
    for item in all_results:
        file_name = item["file"]
        result = item["result"]
        
        status_emoji = "✅" if result["status"] == "APPROVED" else "⚠️"
        comment += f"### {status_emoji} `{file_name}`\n\n"
        comment += f"**Status:** {result['status']}\n\n"
        comment += f"**Summary:** {result['summary']}\n\n"
        
        if result["issues"]:
            comment += "**Issues Found:**\n\n"
            for issue in result["issues"]:
                severity_emoji = {
                    "error": "🔴",
                    "warning": "🟡",
                    "info": "🔵"
                }.get(issue.get("severity", "info"), "⚪")
                
                line_num = issue.get('line', 'N/A')
                message = issue.get('message', 'No description')
                comment += f"- {severity_emoji} **Line {line_num}:** {message}\n"
            comment += "\n"
        else:
            comment += "No issues found! ✨\n\n"
        
        comment += "---\n\n"
    
    # Overall verdict
    if overall_status == "APPROVED":
        comment += "\n## ✅ Overall: APPROVED\n\n"
        comment += "All syntax checks passed! This PR is ready for merge.\n"
    else:
        comment += "\n## ⚠️ Overall: NEEDS CHANGES\n\n"
        comment += "Please address the issues found above before merging.\n"
    
    comment += "\n---\n"
    comment += "*Powered by Azure AI Foundry (GPT-4o-mini)*"
    
    # Post comment to PR
    post_pr_comment(comment)
    
    # Write approval status to file
    with open('approval_status.txt', 'w') as f:
        f.write(overall_status.lower())
    
    print(f"\n{'=' * 60}")
    print(f"Final Status: {overall_status}")
    print(f"{'=' * 60}")
    
    # Exit with appropriate code
    if overall_status == "NEEDS_CHANGES":
        print("\n⚠ Exiting with error code (issues found)")
        sys.exit(1)
    else:
        print("\n✓ All checks passed!")
        sys.exit(0)

if __name__ == "__main__":
    main()
