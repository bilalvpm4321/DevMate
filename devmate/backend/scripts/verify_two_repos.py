"""Script to connect and test two real public repos in Quick and Detailed modes."""
import asyncio
import json
import os
import sys

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import init_db, db
from app.services import indexer, rag, github

async def main():
    init_db()
    user_id = 1
    q = "What is the purpose of this project?"

    # -------------------------------------------------------------
    # REPO 1: Detailed README (bilalvpm4321/makeaton-virtual)
    # -------------------------------------------------------------
    print("=================================================================")
    print("REPO 1: bilalvpm4321/makeaton-virtual (DETAILED README)")
    print("=================================================================")
    with db() as conn:
        row1 = conn.execute(
            "SELECT id, user_id, owner, name, commit_sha FROM repositories WHERE owner = 'bilalvpm4321' AND name = 'makeaton-virtual' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if row1:
        repo1 = await indexer.reindex_repository(row1["id"], row1["user_id"])
    else:
        repo1 = await indexer.connect_repository(user_id, "https://github.com/bilalvpm4321/makeaton-virtual")

    print(f"README Score: {repo1.get('readme_score')}/100 | Quality: '{repo1.get('readme_quality')}'")

    print("\n--- [Quick Mode] ---")
    ans_quick_1 = await rag.answer(repo1, q, mode="quick")
    mq1 = ans_quick_1.get("meta", {})
    tok_q1 = mq1.get("approx_input_tokens", 0) + mq1.get("approx_output_tokens", 0)
    print(f"Meta Line: Answered from {'README' if mq1.get('used_readme') else 'code analysis'} · {mq1.get('llm_calls')} AI call(s) · ~{tok_q1} tokens · cached: {mq1.get('cached')}")
    print(f"suggest_detailed: {ans_quick_1.get('suggest_detailed')}")
    print("Answer snippet:")
    print(ans_quick_1.get("reply", "")[:350].strip() + "\n...")

    print("\n--- [Detailed Mode] ---")
    ans_det_1 = await rag.answer(repo1, q, mode="detailed")
    md1 = ans_det_1.get("meta", {})
    tok_d1 = md1.get("approx_input_tokens", 0) + md1.get("approx_output_tokens", 0)
    print(f"Meta Line: Answered from {'README' if md1.get('used_readme') else 'code analysis'} · {md1.get('llm_calls')} AI call(s) · ~{tok_d1} tokens · cached: {md1.get('cached')}")
    print(f"suggest_detailed: {ans_det_1.get('suggest_detailed')}")
    print("Answer snippet:")
    print(ans_det_1.get("reply", "")[:350].strip() + "\n...")

    # -------------------------------------------------------------
    # REPO 2: Minimal / Poor README (octocat/Hello-World)
    # -------------------------------------------------------------
    print("\n=================================================================")
    print("REPO 2: octocat/Hello-World (MINIMAL / POOR README)")
    print("=================================================================")
    with db() as conn:
        row2 = conn.execute(
            "SELECT id, user_id, owner, name, commit_sha FROM repositories WHERE owner = 'octocat' AND name = 'Hello-World' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if row2:
        repo2 = await indexer.reindex_repository(row2["id"], row2["user_id"])
    else:
        print("Connecting octocat/Hello-World...")
        repo2 = await indexer.connect_repository(user_id, "https://github.com/octocat/Hello-World")

    print(f"README Score: {repo2.get('readme_score')}/100 | Quality: '{repo2.get('readme_quality')}'")

    print("\n--- [Quick Mode] ---")
    ans_quick_2 = await rag.answer(repo2, q, mode="quick")
    mq2 = ans_quick_2.get("meta", {})
    tok_q2 = mq2.get("approx_input_tokens", 0) + mq2.get("approx_output_tokens", 0)
    print(f"Meta Line: Answered from {'README' if mq2.get('used_readme') else 'code analysis'} · {mq2.get('llm_calls')} AI call(s) · ~{tok_q2} tokens · cached: {mq2.get('cached')}")
    print(f"suggest_detailed: {ans_quick_2.get('suggest_detailed')} ({ans_quick_2.get('suggest_reason')})")
    print("Answer snippet:")
    print(ans_quick_2.get("reply", "")[:350].strip() + "\n...")

    print("\n--- [Detailed Mode] ---")
    ans_det_2 = await rag.answer(repo2, q, mode="detailed")
    md2 = ans_det_2.get("meta", {})
    tok_d2 = md2.get("approx_input_tokens", 0) + md2.get("approx_output_tokens", 0)
    print(f"Meta Line: Answered from {'README' if md2.get('used_readme') else 'code analysis'} · {md2.get('llm_calls')} AI call(s) · ~{tok_d2} tokens · cached: {md2.get('cached')}")
    print(f"suggest_detailed: {ans_det_2.get('suggest_detailed')}")
    print("Answer snippet:")
    print(ans_det_2.get("reply", "")[:350].strip() + "\n...")

if __name__ == "__main__":
    asyncio.run(main())
