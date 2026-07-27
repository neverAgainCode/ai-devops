
# scripts/ai_review.py
"""
AI code review gate:
1. Fetch review rules from a Confluence page
2. Get the PR diff vs the base branch
3. Ask Claude to review the diff against the rules
4. Post the result as a PR comment
5. Fail the job if any BLOCKER-severity violation is found
"""

import os
import re
import json
import subprocess
import requests

# ---------- 1. Fetch rules from Confluence ----------

def get_confluence_rules():
    url = (
        f"{os.environ['CONFLUENCE_BASE_URL']}/rest/api/content/"
        f"{os.environ['CONFLUENCE_PAGE_ID']}?expand=body.storage"
    )
    resp = requests.get(
        url,
        auth=(os.environ["CONFLUENCE_EMAIL"], os.environ["CONFLUENCE_API_TOKEN"]),
        timeout=30,
    )
    resp.raise_for_status()
    html = resp.json()["body"]["storage"]["value"]
    # Strip HTML tags to plain text (good enough for rules text)
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    print("=== Rules fetched from Confluence ===")
    print(text)
    return text


# ---------- 2. Get the PR diff ----------

def get_diff():
    base = os.environ["BASE_REF"]
    diff = subprocess.check_output(
        ["git", "diff", f"origin/{base}...HEAD"], text=True
    )
    if not diff.strip():
        print("No changes found in diff.")
    return diff


# ---------- 3. Ask Claude to review ----------

def review_with_claude(rules, diff):
    prompt = f"""You are a strict code reviewer for a Salesforce project.

Review the following code diff against these team rules from our Confluence standards page:

<rules>
{rules}
</rules>

<diff>
{diff}
</diff>

Respond ONLY with valid JSON, no markdown fences, in this exact format:
{{
  "violations": [
    {{
      "file": "path/to/file",
      "rule": "which rule was broken",
      "severity": "BLOCKER" or "WARNING",
      "explanation": "short explanation",
      "suggestion": "how to fix it"
    }}
  ],
  "summary": "one-sentence overall assessment"
}}

If there are no violations, return an empty violations array."""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"]
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ---------- 4. Post result as a PR comment ----------

def post_pr_comment(result):
    violations = result.get("violations", [])
    if violations:
        lines = ["## 🤖 AI Code Review — issues found\n"]
        for v in violations:
            icon = "🚫" if v["severity"] == "BLOCKER" else "⚠️"
            lines.append(
                f"{icon} **{v['severity']}** — `{v['file']}`\n"
                f"- **Rule:** {v['rule']}\n"
                f"- {v['explanation']}\n"
                f"- **Suggestion:** {v['suggestion']}\n"
            )
        lines.append(f"\n> {result.get('summary', '')}")
        body = "\n".join(lines)
    else:
        body = f"## 🤖 AI Code Review — ✅ no violations\n\n> {result.get('summary', '')}"

    url = (
        f"https://api.github.com/repos/{os.environ['REPO']}/issues/"
        f"{os.environ['PR_NUMBER']}/comments"
    )
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
        json={"body": body},
        timeout=30,
    )
    resp.raise_for_status()


# ---------- Main ----------

if __name__ == "__main__":
    rules = get_confluence_rules()
    diff = get_diff()
    if not diff.strip():
        print("Nothing to review.")
        exit(0)

    result = review_with_claude(rules, diff)
    print("=== Claude review result ===")
    print(json.dumps(result, indent=2))

    post_pr_comment(result)

    blockers = [v for v in result.get("violations", []) if v["severity"] == "BLOCKER"]
    if blockers:
        print(f"❌ {len(blockers)} blocker(s) found — failing the check.")
        exit(1)
    print("✅ Review passed.")
