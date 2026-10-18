"""
Deploy Dashboard to Hugging Face Spaces (Static Space)
Uploads dashboard.html as index.html to the user's alphaquant-sovereign-control Space.
Includes retry logic for intermittent DNS/network latency.
"""
import os
import sys
import time
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

def run_with_retry(fn, desc: str, max_retries: int = 6, delay: float = 2.0):
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            print(f"  [Attempt {attempt}/{max_retries}] {desc} transient issue: {e}")
            if attempt < max_retries:
                time.sleep(delay)
    raise last_err

def deploy(token: str = None, space_name: str = "alphaquant-sovereign-control"):
    hf_token = token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    
    if not hf_token:
        print("ERROR: Hugging Face Token not found.")
        print("Please add HF_TOKEN=hf_... to your .env file or pass it to this script.")
        print("You can get a Write token from: https://huggingface.co/settings/tokens")
        return False

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("ERROR: huggingface_hub is not installed in the virtual environment.")
        return False

    api = HfApi(token=hf_token)

    # 1. Authenticate & identify username
    print("Connecting to Hugging Face API...")
    try:
        user_info = run_with_retry(lambda: api.whoami(token=hf_token), "User authentication")
        username = user_info.get("name")
        print(f"Authenticated successfully as Hugging Face user: {username}")
    except Exception as e:
        print(f"ERROR: Authentication failed after retries: {e}")
        return False

    repo_id = f"{username}/{space_name}"
    dashboard_file = os.path.join(BASE_DIR, "dashboard.html")

    if not os.path.exists(dashboard_file):
        print(f"ERROR: File not found: {dashboard_file}")
        return False

    # 2. Ensure Space exists (Static SDK)
    print(f"Verifying repository: {repo_id} (type: space)...")
    try:
        run_with_retry(
            lambda: api.create_repo(
                repo_id=repo_id,
                repo_type="space",
                space_sdk="static",
                exist_ok=True,
                token=hf_token
            ),
            "Create/Verify Space repo"
        )
        print(f"Repository {repo_id} is ready.")
    except Exception as e:
        print(f"Warning while verifying space repo: {e}")

    # 2b. Sync paper_state.json into data/pipeline_bus.json if available
    bus_file = os.path.join(BASE_DIR, "data", "pipeline_bus.json")
    paper_file = os.path.join(BASE_DIR, "paper_state.json")
    if os.path.exists(paper_file):
        try:
            import json
            from pipeline_bus import update_bus_section
            with open(paper_file, "r", encoding="utf-8") as pf:
                pdata = json.load(pf)
            update_bus_section("paper_state", pdata)
            update_bus_section("last_sync_time", time.strftime("%Y-%m-%d %H:%M:%S UTC"))
            print("Synced paper_state.json into data/pipeline_bus.json.")
        except Exception as e:
            print(f"Notice: Bus sync skipped: {e}")

    # 3. Upload dashboard.html as index.html
    print(f"Uploading dashboard.html as index.html to {repo_id}...")
    try:
        run_with_retry(
            lambda: api.upload_file(
                path_or_fileobj=dashboard_file,
                path_in_repo="index.html",
                repo_id=repo_id,
                repo_type="space",
                token=hf_token,
                commit_message="Deploy AlphaQuant Sovereign Fund Operations Room Dashboard"
            ),
            "Upload index.html"
        )
    except Exception as e:
        print(f"ERROR: Upload of index.html failed: {e}")
        return False

    # 4. Upload data/pipeline_bus.json
    if os.path.exists(bus_file):
        print(f"Uploading data/pipeline_bus.json to {repo_id}...")
        try:
            run_with_retry(
                lambda: api.upload_file(
                    path_or_fileobj=bus_file,
                    path_in_repo="data/pipeline_bus.json",
                    repo_id=repo_id,
                    repo_type="space",
                    token=hf_token,
                    commit_message="Update data/pipeline_bus.json with latest paper state"
                ),
                "Upload data/pipeline_bus.json"
            )
            print("data/pipeline_bus.json uploaded successfully.")
        except Exception as e:
            print(f"Warning: Upload of pipeline_bus.json skipped: {e}")

    print("\n" + "=" * 70)
    print("SUCCESS! Dashboard and pipeline bus deployed successfully.")
    print(f"Live Space URL : https://huggingface.co/spaces/{repo_id}")
    print("=" * 70)
    return True

if __name__ == "__main__":
    cli_token = sys.argv[1] if len(sys.argv) > 1 else None
    success = deploy(token=cli_token)
    if not success:
        sys.exit(1)
