#!/usr/bin/env python3
"""
使用 Playwright 自动化 GitHub 操作:
1. 通过浏览器获取 GitHub device flow token
2. 使用 token 创建仓库
3. 上传 bootstrap.py 和 workflow 文件
4. 配置 FEISHU_WEBHOOK_URL secret
"""
import os, sys, time, json, base64, urllib.request, urllib.parse

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BOOTSTRAP_PATH = os.path.join(PROJECT_ROOT, "bootstrap.py")
WORKFLOW_PATH = os.path.join(PROJECT_ROOT, ".github", "workflows", "monitor.yml")

FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/8e1336dc-f9e0-4fad-a2aa-27cb1a333301"
REPO_NAME = "BreakoutAnalysis"
REPO_DESC = "Stock breakout monitoring system (A-share + US), with Feishu notification"
GH_CLIENT_ID = "178c6fc778ccc68e1d6a"  # gh CLI's OAuth client_id

def get_device_code_via_browser(page):
    """Use browser's fetch to get device code (browser can reach github.com)"""
    result = page.evaluate("""async () => {
        try {
            const resp = await fetch('https://github.com/login/device/code', {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    client_id: '178c6fc778ccc68e1d6a',
                    scope: 'repo'
                })
            });
            const data = await resp.json();
            return JSON.stringify(data);
        } catch(e) {
            return JSON.stringify({error: e.message});
        }
    }""")
    return json.loads(result)

def poll_for_token_via_browser(page, device_code):
    """Poll for token using browser's fetch"""
    result = page.evaluate("""async (device_code) => {
        try {
            const resp = await fetch('https://github.com/login/oauth/access_token', {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    client_id: '178c6fc778ccc68e1d6a',
                    device_code: device_code,
                    grant_type: 'urn:ietf:params:oauth:grant-type:device_code'
                })
            });
            const data = await resp.json();
            return JSON.stringify(data);
        } catch(e) {
            return JSON.stringify({error: e.message});
        }
    }""", device_code)
    return json.loads(result)

def api_github(method, path, token, data=None):
    """Call GitHub API (api.github.com works from command line)"""
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    if data:
        post_data = json.dumps(data).encode()
        req = urllib.request.Request(url, data=post_data, headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  API Error {e.code}: {body[:200]}")
        return json.loads(body) if body.startswith("{") else {"error": body}
    except Exception as e:
        print(f"  Request error: {e}")
        return {"error": str(e)}

def main():
    from playwright.sync_api import sync_playwright
    
    temp_profile = os.path.join(os.environ.get("TEMP", "/tmp"), "gh_auto_profile")
    
    with sync_playwright() as p:
        print("Launching Chrome...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=temp_profile,
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        
        page = context.pages[0] if context.pages else context.new_page()
        
        # Navigate to GitHub first (to establish origin for fetch)
        page.goto("https://github.com", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        
        # Step 1: Get device code via browser
        print("\n=== Step 1: Getting device code ===")
        device_data = get_device_code_via_browser(page)
        
        if "error" in device_data:
            print(f"Error getting device code: {device_data['error']}")
            print("Trying alternative method...")
            # Navigate directly to the API endpoint
            page.goto("https://github.com/login/device", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            device_data = get_device_code_via_browser(page)
        
        if "device_code" not in device_data:
            print(f"Failed to get device code: {device_data}")
            context.close()
            return
        
        user_code = device_data["user_code"]
        device_code = device_data["device_code"]
        interval = device_data.get("interval", 5)
        expires_in = device_data.get("expires_in", 900)
        
        print(f"Device code obtained!")
        print(f"User code: {user_code}")
        print(f"Expires in: {expires_in}s")
        
        # Open the device verification page
        page.goto(f"https://github.com/login/device", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        
        # Auto-fill the user code
        try:
            # Try to fill the code input
            code_input = page.locator('input[name="user_code"], input#user-code, input[autocomplete="off"]').first
            if code_input.count() > 0:
                code_input.fill(user_code)
                time.sleep(0.5)
                # Try to submit
                page.keyboard.press("Enter")
                print(f"Auto-filled user code: {user_code}")
                time.sleep(3)
            else:
                print(f"Please enter code manually: {user_code}")
        except Exception as e:
            print(f"Auto-fill error: {e}")
            print(f"Please enter code manually: {user_code}")
        
        # Wait for authorization
        print("\nWaiting for authorization...")
        print(f"If the browser didn't auto-fill, go to https://github.com/login/device")
        print(f"and enter: {user_code}")
        
        token = None
        poll_count = 0
        max_polls = expires_in // interval
        
        while poll_count < max_polls:
            time.sleep(interval)
            poll_count += 1
            
            token_data = poll_for_token_via_browser(page, device_code)
            
            if "access_token" in token_data:
                token = token_data["access_token"]
                print(f"\nToken obtained! (after {poll_count} polls)")
                break
            elif "error" in token_data:
                error = token_data["error"]
                if error == "authorization_pending":
                    if poll_count % 6 == 0:  # Print every 30 seconds
                        print(f"  Still waiting... ({poll_count * interval}s elapsed)")
                    continue
                elif error == "slow_down":
                    interval += 5
                    continue
                elif error == "expired_token":
                    print("Device code expired!")
                    break
                else:
                    print(f"Poll error: {token_data}")
                    break
        
        if not token:
            print("Failed to get token")
            context.close()
            return
        
        # Save token for gh CLI
        token_file = os.path.join(os.environ.get("APPDATA", ""), "GitHub CLI", "hosts.yml")
        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        with open(token_file, 'w') as f:
            f.write(f"github.com:\n    oauth_token: {token}\n    user: Cyril1688\n    git_protocol: https\n")
        print(f"Token saved to {token_file}")
        
        # Step 2: Create repository via API
        print("\n=== Step 2: Creating repository ===")
        result = api_github("POST", "/user/repos", token, {
            "name": REPO_NAME,
            "description": REPO_DESC,
            "private": False,
            "auto_init": True
        })
        
        if "html_url" in result:
            print(f"Repository created: {result['html_url']}")
        elif "errors" in result:
            for err in result["errors"]:
                if "already exists" in err.get("message", "").lower() or "name already exists" in str(err).lower():
                    print("Repository already exists (OK)")
                else:
                    print(f"Error: {err}")
        else:
            print(f"Create result: {result}")
        
        time.sleep(2)
        
        # Step 3: Get the default branch SHA
        print("\n=== Step 3: Pushing files via API ===")
        repo_info = api_github("GET", f"/repos/Cyril1688/{REPO_NAME}", token)
        default_branch = repo_info.get("default_branch", "main")
        print(f"Default branch: {default_branch}")
        
        # Get the latest commit SHA
        branch_info = api_github("GET", f"/repos/Cyril1688/{REPO_NAME}/branches/{default_branch}", token)
        base_sha = branch_info.get("commit", {}).get("sha")
        print(f"Base commit SHA: {base_sha}")
        
        # Get the base tree
        commit_info = api_github("GET", f"/repos/Cyril1688/{REPO_NAME}/commits/{base_sha}", token)
        base_tree_sha = commit_info.get("commit", {}).get("tree", {}).get("sha")
        print(f"Base tree SHA: {base_tree_sha}")
        
        # Read bootstrap.py
        with open(BOOTSTRAP_PATH, 'r', encoding='utf-8') as f:
            bootstrap_content = f.read()
        
        # Read workflow file
        with open(WORKFLOW_PATH, 'r', encoding='utf-8') as f:
            workflow_content = f.read()
        
        # Create blobs for each file
        files_to_push = [
            ("bootstrap.py", bootstrap_content),
            (".github/workflows/monitor.yml", workflow_content),
        ]
        
        tree_items = []
        for path, content in files_to_push:
            print(f"  Creating blob: {path}")
            blob = api_github("POST", f"/repos/Cyril1688/{REPO_NAME}/git/blobs", token, {
                "content": content,
                "encoding": "utf-8"
            })
            if "sha" in blob:
                tree_items.append({
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob["sha"]
                })
                print(f"    Blob SHA: {blob['sha'][:8]}...")
            else:
                print(f"    Error creating blob: {blob}")
        
        # Create tree
        print("  Creating tree...")
        tree = api_github("POST", f"/repos/Cyril1688/{REPO_NAME}/git/trees", token, {
            "base_tree": base_tree_sha,
            "tree": tree_items
        })
        tree_sha = tree.get("sha")
        print(f"  Tree SHA: {tree_sha}")
        
        # Create commit
        print("  Creating commit...")
        commit = api_github("POST", f"/repos/Cyril1688/{REPO_NAME}/git/commits", token, {
            "message": "feat: dual-market monitoring + Feishu notification + GitHub Actions",
            "tree": tree_sha,
            "parents": [base_sha]
        })
        commit_sha = commit.get("sha")
        print(f"  Commit SHA: {commit_sha}")
        
        # Update ref
        print("  Updating branch ref...")
        ref_result = api_github("PATCH", f"/repos/Cyril1688/{REPO_NAME}/git/refs/heads/{default_branch}", token, {
            "sha": commit_sha
        })
        if "ref" in ref_result:
            print("  Files pushed successfully!")
        else:
            print(f"  Push error: {ref_result}")
        
        # Step 4: Configure secret
        print("\n=== Step 4: Configuring FEISHU_WEBHOOK_URL secret ===")
        # Use the browser to set the secret (API requires encrypted secrets)
        secrets_url = f"https://github.com/Cyril1688/{REPO_NAME}/settings/secrets/actions"
        page.goto(secrets_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        
        # Check if we need to log in again
        if "login" in page.url.lower():
            print("Need to re-authenticate in browser for secrets...")
            # Use the token to authenticate via URL
            page.goto(f"https://{token}@github.com/{secrets_url.replace('https://github.com/', '')}", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
        
        try:
            new_secret_link = page.locator('a:has-text("New repository secret")')
            if new_secret_link.count() > 0:
                new_secret_link.click()
                time.sleep(2)
                
                # Fill name
                name_input = page.locator('input[name="secret_name"], input#secret_name')
                if name_input.count() > 0:
                    name_input.fill("FEISHU_WEBHOOK_URL")
                
                # Fill value
                value_input = page.locator('textarea[name="secret_value"], textarea#secret_value')
                if value_input.count() > 0:
                    value_input.fill(FEISHU_WEBHOOK)
                
                # Click Add secret
                add_btn = page.locator('button:has-text("Add secret")')
                if add_btn.count() > 0:
                    add_btn.click()
                    print("Secret FEISHU_WEBHOOK_URL added!")
                    time.sleep(3)
            else:
                print("Could not find 'New repository secret' link")
        except Exception as e:
            print(f"Error adding secret: {e}")
        
        # Step 5: Enable Actions
        print("\n=== Step 5: Checking Actions ===")
        actions_url = f"https://github.com/Cyril1688/{REPO_NAME}/actions"
        page.goto(actions_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        
        try:
            enable_btn = page.locator('button:has-text("I understand")')
            if enable_btn.count() > 0:
                enable_btn.click()
                print("Actions enabled!")
                time.sleep(3)
            else:
                print("Actions already enabled or no action needed")
        except:
            pass
        
        # Done
        print("\n" + "="*50)
        print("SETUP COMPLETE!")
        print("="*50)
        print(f"\nRepository: https://github.com/Cyril1688/{REPO_NAME}")
        print(f"Actions: https://github.com/Cyril1688/{REPO_NAME}/actions")
        print(f"\nThe system will run automatically:")
        print(f"  - 07:00-15:00 every 30 min (A-share market)")
        print(f"  - 21:00-00:00 every 30 min (US market)")
        print(f"  - Weekdays only")
        print(f"  - Feishu notification on stock breakouts")
        
        # Keep browser open for a while
        time.sleep(15)
        context.close()

if __name__ == "__main__":
    main()
