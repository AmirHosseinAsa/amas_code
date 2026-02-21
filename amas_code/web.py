"""Web tools — search, fetch, browser (lazy-loaded Playwright)."""
from amas_code import ui


# ── Web Search (multi-engine: DDG API → DDG HTML → Google) ───────────────────

_SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def web_search(query: str, num_results: int = 5) -> str:
    """Search the web and return results. Tries multiple search engines."""
    try:
        import httpx

        with httpx.Client(
            headers=_SEARCH_HEADERS,
            follow_redirects=True,
            timeout=10,
        ) as client:
            # Engine 1: DuckDuckGo JSON API (most reliable)
            results = _ddg_api_search(client, query, num_results)

            # Engine 2: DuckDuckGo HTML Lite
            if not results:
                results = _ddg_html_search(client, query, num_results)

            # Engine 3: Google HTML
            if not results:
                results = _google_html_search(client, query, num_results)

        if not results:
            return f"No results found for: {query}"

        formatted = "\n\n".join(
            f"{i}. [{r['title']}]({r['url']})\n   {r.get('snippet', '')}"
            for i, r in enumerate(results, 1)
        )
        return f"Search results for '{query}':\n\n{formatted}"
    except ImportError as e:
        return f"Error: missing dependency ({e}). Run: pip install httpx beautifulsoup4"
    except Exception as e:
        return f"Error searching: {e}"


def _ddg_api_search(client, query: str, num: int) -> list[dict]:
    """Search via DuckDuckGo's internal API (VQD token + d.js JSON)."""
    import re
    import json

    try:
        # Step 1: Get VQD token
        resp = client.post(
            "https://duckduckgo.com/",
            data={"q": query},
        )
        # Try multiple patterns for VQD extraction
        vqd = None
        for pattern in [
            r'vqd="([^"]+)"',
            r"vqd='([^']+)'",
            r"vqd=([\d-]+)",
        ]:
            m = re.search(pattern, resp.text)
            if m:
                vqd = m.group(1)
                break

        if not vqd:
            return []

        # Step 2: Fetch actual results from d.js
        resp = client.get(
            "https://links.duckduckgo.com/d.js",
            params={
                "q": query,
                "vqd": vqd,
                "kl": "wt-wt",
                "l": "wt-wt",
                "p": "",
                "s": "0",
                "df": "",
                "ex": "-1",
            },
        )

        # d.js returns JSONP-like content; extract the JSON array
        text = resp.text
        # Try direct JSON parse first
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                data = data.get("results", [])
        except (json.JSONDecodeError, ValueError):
            # Try extracting JSON array from JSONP wrapper
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except (json.JSONDecodeError, ValueError):
                    return []
            else:
                return []

        results = []
        for item in data:
            if not isinstance(item, dict):
                continue
            # DDG d.js uses 't' for title, 'u' for URL, 'a' for snippet
            title = item.get("t", "") or item.get("title", "")
            url = item.get("u", "") or item.get("url", "")
            snippet = item.get("a", "") or item.get("snippet", "")
            if title and url and not url.startswith("//duckduckgo"):
                # Clean HTML from snippet
                if "<" in snippet:
                    snippet = re.sub(r'<[^>]+>', '', snippet)
                results.append({"title": title, "url": url, "snippet": snippet})
                if len(results) >= num:
                    break

        return results
    except Exception:
        return []


def _ddg_html_search(client, query: str, num: int) -> list[dict]:
    """Scrape DuckDuckGo's HTML lite page."""
    import re

    try:
        resp = client.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query, "kd": "-1"},  # kd=-1 disables safe search redirect
        )
        html = resp.text

        # DDG Lite has a very simple table-based layout
        # Results are in <a class="result-link"> or just <a> with external hrefs
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        results = []

        # Try result-link class first (DDG Lite format)
        links = soup.select("a.result-link")

        # Fallback: find all links that point to external sites
        if not links:
            links = soup.find_all("a", href=True)
            links = [
                a for a in links
                if a["href"].startswith("http")
                and "duckduckgo" not in a["href"]
                and "duck.co" not in a["href"]
                and a.get_text(strip=True)
                and len(a.get_text(strip=True)) > 5
            ]

        for link in links:
            title = link.get_text(strip=True)
            url = link.get("href", "")
            if not title or not url:
                continue

            # Try to find snippet text near this link
            snippet = ""
            parent = link.parent
            if parent:
                # Look for next sibling text or td
                for sibling in parent.find_next_siblings(limit=2):
                    text = sibling.get_text(strip=True)
                    if text and len(text) > 20 and text != title:
                        snippet = text[:300]
                        break

            results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= num:
                break

        return results
    except Exception:
        return []


def _google_html_search(client, query: str, num: int) -> list[dict]:
    """Scrape Google search results as a last resort."""
    import re

    try:
        resp = client.get(
            "https://www.google.com/search",
            params={"q": query, "num": str(num), "hl": "en"},
        )
        html = resp.text

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        results = []

        # Google's main result containers
        for div in soup.select("div.g, div.tF2Cxc, div.yuRUbf"):
            link = div.find("a", href=True)
            h3 = div.find("h3")
            if not link or not h3:
                continue

            title = h3.get_text(strip=True)
            url = link.get("href", "")

            if not url.startswith("http"):
                continue

            # Snippet
            snippet = ""
            for snip_sel in [".VwiC3b", ".IsZvec", "span.st"]:
                snip_el = div.select_one(snip_sel)
                if snip_el:
                    snippet = snip_el.get_text(strip=True)[:300]
                    break

            results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= num:
                break

        # Regex fallback if BeautifulSoup selectors don't match
        if not results:
            # Find patterns like <h3>...<a href="https://...">
            for m in re.finditer(
                r'<a href="(https?://(?!www\.google)[^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>',
                html, re.DOTALL
            ):
                url = m.group(1)
                title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if title and url:
                    results.append({"title": title, "url": url, "snippet": ""})
                    if len(results) >= num:
                        break

        return results
    except Exception:
        return []


# ── URL Fetch ────────────────────────────────────────────────────────────────

def fetch_url(url: str, max_chars: int = 1000000) -> str:
    """Fetch a URL and return text content."""
    try:
        import httpx  # Lazy import

        headers = {"User-Agent": "Mozilla/5.0 (compatible; AmasCode/1.0)"}
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=15)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "html" in content_type:
            text = _extract_text_from_html(response.text)
        else:
            text = response.text

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[truncated — page is {len(response.text):,} chars]"

        return f"Fetched {url} ({len(response.text):,} chars):\n\n{text}"
    except ImportError:
        return "Error: httpx not installed. Run: pip install httpx"
    except Exception as e:
        return f"Error fetching {url}: {e}"


def _extract_text_from_html(html: str) -> str:
    """Extract readable text from HTML, stripping tags."""
    import re
    # Remove script and style tags
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Clean whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Decode all HTML entities using stdlib
    import html
    text = html.unescape(text)
    return text


# ── Playwright Browser (persistent subprocess — full power) ──────────────────

_browser_proc = None
_cmd_queue = None
_result_queue = None

_TIMEOUT = 15000  # 15s for element waits

# Common input selectors to try as fallback, in priority order
_INPUT_FALLBACKS = [
    "textarea",
    "[contenteditable='true']",
    "[contenteditable]",
    "div.tiptap.ProseMirror",
    "div.ProseMirror",
    "input[type='text']",
    "input:not([type='hidden'])",
]


def _browser_worker(cmd_q, res_q):
    """Long-lived worker process that owns the browser."""
    try:
        from playwright.sync_api import sync_playwright
        import time

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        # Use a mutable container so nested functions can update the active page
        state = {"page": ctx.new_page()}
        console_log: list[str] = []  # Captured console errors/warnings/pageerrors

        def _setup_listeners(p):
            """Attach console and pageerror listeners to capture JS errors."""
            p.on("console", lambda msg: console_log.append(f"[{msg.type}] {msg.text}")
                 if msg.type in ("error", "warning") else None)
            p.on("pageerror", lambda exc: console_log.append(f"[uncaught] {exc}"))

        _setup_listeners(state["page"])

        # Auto-track new pages/tabs opened by the site (e.g., Grok redirect)
        def _on_new_page(new_page):
            state["page"] = new_page
            _setup_listeners(new_page)
        ctx.on("page", _on_new_page)

        res_q.put("__READY__")

        def _get_page():
            """Return the currently active page, auto-switching to latest if closed."""
            p = state.get("page")
            if not p or p.is_closed():
                pages = [p for p in ctx.pages if not p.is_closed()]
                if pages:
                    state["page"] = pages[-1]
                else:
                    state["page"] = ctx.new_page()
            return state["page"]

        def _smart_type(sel, text):
            """Type into any element — works for input, textarea, AND contenteditable divs.
            If the given selector fails, tries common fallback selectors."""
            page = _get_page()
            el = None

            # Try the given selector first
            try:
                el = page.wait_for_selector(sel, state="visible", timeout=5000)
            except Exception:
                pass

            # If that failed, re-get page (it may have changed!) then try fallbacks
            if el is None:
                page = _get_page()  # Page may have redirected
                for fallback in _INPUT_FALLBACKS:
                    if fallback == sel:
                        continue
                    try:
                        el = page.wait_for_selector(fallback, state="visible", timeout=3000)
                        if el:
                            sel = fallback  # Update selector for reporting
                            break
                    except Exception:
                        continue

            if el is None:
                raise RuntimeError(f"Could not find any input element. Tried: {sel} and fallbacks {_INPUT_FALLBACKS}")

            tag = el.evaluate("e => e.tagName.toLowerCase()")
            is_editable = el.evaluate("e => e.isContentEditable")

            el.click()
            time.sleep(0.2)

            if tag in ("input", "textarea"):
                try:
                    page.fill(sel, "")
                except Exception:
                    page.keyboard.press("Control+a")
                    page.keyboard.press("Backspace")
                page.type(sel, text, delay=30)
            elif is_editable:
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
                time.sleep(0.1)
                page.keyboard.type(text, delay=30)
            else:
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
                page.keyboard.type(text, delay=30)

            return sel  # Return actual selector used

        while True:
            try:
                task = cmd_q.get(timeout=1)
            except Exception:
                continue

            if task is None:  # Shutdown signal
                break

            func_name = task.get("func")
            kw = task.get("kw", {})

            try:
                page = _get_page()

                if func_name == "navigate":
                    console_log.clear()  # Fresh error log for this navigation
                    page.goto(kw["url"], wait_until="domcontentloaded", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        time.sleep(2)  # Fallback if networkidle times out
                    # After navigation, re-get page in case it changed
                    page = _get_page()
                    title = page.title()
                    url = page.url
                    text = page.inner_text("body")
                    if len(text) > 10000:
                        text = text[:10000] + "\n\n[truncated]"

                    # Detect interactive elements so LLM knows what's available
                    input_info = []
                    for check_sel, label in [
                        ("textarea", "textarea"),
                        ("[contenteditable='true']", "contenteditable div"),
                        ("div.ProseMirror", "ProseMirror editor"),
                        ("input[type='text']", "text input"),
                        ("input:not([type='hidden'])", "input field"),
                    ]:
                        try:
                            found = page.query_selector(check_sel)
                            if found and found.is_visible():
                                input_info.append(label)
                        except Exception:
                            pass

                    elements_line = ""
                    if input_info:
                        elements_line = f"\n\n✅ Interactive elements found: {', '.join(input_info)} — you can type into these!"
                    else:
                        elements_line = "\n\n⚠️ No visible input elements detected. Page may still be loading or may require login."

                    errors_line = ""
                    if console_log:
                        errors_line = "\n\n🚨 Console errors detected:\n" + "\n".join(console_log[:20])

                    res_q.put(f"Navigated to: {title}\nURL: {url}{elements_line}{errors_line}\n\n{text}")

                elif func_name == "click":
                    sel = kw["selector"]
                    page.wait_for_selector(sel, state="visible", timeout=_TIMEOUT)
                    page.click(sel, timeout=_TIMEOUT)
                    try:
                        page.wait_for_load_state("networkidle", timeout=6000)
                    except Exception:
                        time.sleep(1)
                    page = _get_page()  # Re-get in case click opened new tab
                    title = page.title()
                    url = page.url
                    try:
                        text = page.inner_text("body", timeout=5000)
                        if len(text) > 6000:
                            text = text[:6000] + "\n[truncated]"
                    except Exception:
                        text = ""
                    res_q.put(f"Clicked: {sel}\nPage: {title}\nURL: {url}\n\n{text}")

                elif func_name == "type":
                    sel = kw["selector"]
                    actual_sel = _smart_type(sel, kw["text"])
                    res_q.put(f"Typed into {actual_sel}: {kw['text']}")

                elif func_name == "press":
                    key = kw.get("key", "Enter")
                    old_url = page.url
                    page.keyboard.press(key)
                    time.sleep(2)  # Give more time for redirects
                    page = _get_page()  # Re-get in case Enter caused navigation/new tab
                    new_url = page.url
                    title = page.title()

                    # Detect URL change and report available inputs
                    url_changed = old_url != new_url
                    parts = [f"Pressed: {key}", f"Page: {title}", f"URL: {new_url}"]
                    if url_changed:
                        parts.append(f"⚠️ URL changed from {old_url} → {new_url}")

                    # After pressing Enter, check what input elements are available now
                    available = []
                    for check_sel, label in [
                        ("textarea", "textarea"),
                        ("[contenteditable='true']", "contenteditable"),
                        ("div.ProseMirror", "ProseMirror"),
                    ]:
                        try:
                            found = page.query_selector(check_sel)
                            if found and found.is_visible():
                                available.append(label)
                        except Exception:
                            pass
                    if available:
                        parts.append(f"✅ Available inputs: {', '.join(available)}")

                    res_q.put("\n".join(parts))

                elif func_name == "screenshot":
                    path = kw.get("path", "screenshot.png")
                    page.screenshot(path=path, full_page=False)
                    res_q.put(f"Screenshot saved to: {path}")

                elif func_name == "get_text":
                    sel = kw.get("selector", "body")
                    page = _get_page()  # Always re-get in case page changed
                    page.wait_for_selector(sel, timeout=_TIMEOUT)
                    text = page.inner_text(sel, timeout=_TIMEOUT)
                    if len(text) > 10000:
                        text = text[:10000] + "\n\n[truncated]"

                    # If result is very short and selector isn't body, also provide body context
                    if len(text.strip()) < 50 and sel != "body":
                        try:
                            body_text = page.inner_text("body", timeout=3000)
                            if len(body_text) > 2000:
                                body_text = body_text[:2000] + "\n[truncated]"
                            text = f"{text}\n\n⚠️ Result was very short. Full page body for context:\n{body_text}\nURL: {page.url}"
                        except Exception:
                            pass

                    res_q.put(text)

                elif func_name == "eval":
                    expr = kw["expression"]
                    if any(keyword in expr for keyword in ("return ", "let ", "const ", "var ")):
                        expr = f"(() => {{ {expr} }})()"
                    result = page.evaluate(expr)
                    res_q.put(f"Result: {result}")

                elif func_name == "wait":
                    sel = kw["selector"]
                    timeout = kw.get("timeout", _TIMEOUT)
                    page.wait_for_selector(sel, state="visible", timeout=timeout)
                    res_q.put(f"Element found: {sel}")

                elif func_name == "wait_idle":
                    sel = kw.get("selector", "body")
                    max_wait = kw.get("wait_timeout", 30)
                    stable_secs = kw.get("stable", 3)

                    prev_text = ""
                    stable_since = None
                    deadline = time.time() + max_wait

                    while time.time() < deadline:
                        page = _get_page()
                        try:
                            cur_text = page.inner_text(sel, timeout=3000)
                        except Exception:
                            cur_text = ""

                        if cur_text and cur_text == prev_text:
                            if stable_since is None:
                                stable_since = time.time()
                            elif time.time() - stable_since >= stable_secs:
                                if len(cur_text) > 8000:
                                    cur_text = cur_text[:8000] + "\n\n[truncated]"
                                res_q.put(f"Page stabilized.\n\n{cur_text}")
                                break
                        else:
                            stable_since = None
                            prev_text = cur_text

                        time.sleep(1)
                    else:
                        if len(prev_text) > 8000:
                            prev_text = prev_text[:8000] + "\n\n[truncated]"
                        res_q.put(f"Timeout ({max_wait}s), returning current content.\n\n{prev_text}")

                elif func_name == "get_console_errors":
                    if console_log:
                        res_q.put(f"Console errors/warnings ({len(console_log)}):\n" + "\n".join(console_log))
                    else:
                        res_q.put("No console errors detected.")

                elif func_name == "url":
                    res_q.put(f"Current URL: {page.url}\nTitle: {page.title()}")

                elif func_name == "scroll":
                    direction = kw.get("direction", "down")
                    amount = kw.get("amount", 500)
                    if direction == "down":
                        page.evaluate(f"window.scrollBy(0, {amount})")
                    elif direction == "up":
                        page.evaluate(f"window.scrollBy(0, -{amount})")
                    time.sleep(0.5)
                    res_q.put(f"Scrolled {direction} by {amount}px")

                # ── Tab management ──────────────────────────────────
                elif func_name == "new_tab":
                    url = kw.get("url", "about:blank")
                    new_page = ctx.new_page()
                    state["page"] = new_page
                    if url != "about:blank":
                        new_page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(2)
                    tab_idx = ctx.pages.index(new_page)
                    total = len(ctx.pages)
                    title = new_page.title() or "(blank)"
                    res_q.put(f"Opened new tab #{tab_idx} (total: {total})\nURL: {new_page.url}\nTitle: {title}")

                elif func_name == "switch_tab":
                    idx = kw.get("index", 0)
                    pages = ctx.pages
                    if idx < 0 or idx >= len(pages):
                        res_q.put(f"Error: Tab index {idx} out of range (0-{len(pages)-1})")
                    else:
                        state["page"] = pages[idx]
                        pages[idx].bring_to_front()
                        time.sleep(0.5)
                        title = pages[idx].title()
                        url = pages[idx].url
                        res_q.put(f"Switched to tab #{idx}\nURL: {url}\nTitle: {title}")

                elif func_name == "close_tab":
                    idx = kw.get("index", -1)
                    pages = ctx.pages
                    if len(pages) <= 1:
                        res_q.put("Error: Cannot close the last tab.")
                    else:
                        if idx == -1:
                            idx = pages.index(state["page"])
                        if idx < 0 or idx >= len(pages):
                            res_q.put(f"Error: Tab index {idx} out of range (0-{len(pages)-1})")
                        else:
                            pages[idx].close()
                            remaining = ctx.pages
                            if remaining:
                                state["page"] = remaining[min(idx, len(remaining) - 1)]
                                state["page"].bring_to_front()
                            res_q.put(f"Closed tab #{idx}. Now on: {state['page'].url} ({len(remaining)} tabs)")

                elif func_name == "list_tabs":
                    pages = ctx.pages
                    current = state["page"]
                    lines = [f"Open tabs ({len(pages)}):"]
                    for i, p in enumerate(pages):
                        marker = " ◀ active" if p == current else ""
                        try:
                            title = p.title() or "(untitled)"
                            url = p.url
                        except Exception:
                            title = "(closed)"
                            url = ""
                        lines.append(f"  [{i}] {title} — {url}{marker}")
                    res_q.put("\n".join(lines))

                else:
                    res_q.put(f"Error: Unknown browser command: {func_name}")
            except Exception as e:
                res_q.put(f"Error: {e}")

        browser.close()
        pw.stop()
    except ImportError:
        res_q.put("Error: Playwright not installed. Run: pip install playwright && playwright install chromium")
    except Exception as e:
        res_q.put(f"Error starting browser: {e}")


def _ensure_browser():
    """Start the browser process if not running. Auto-installs Playwright if missing."""
    global _browser_proc, _cmd_queue, _result_queue
    import multiprocessing as mp

    if _browser_proc and _browser_proc.is_alive():
        return True

    _cmd_queue = mp.Queue()
    _result_queue = mp.Queue()
    _browser_proc = mp.Process(target=_browser_worker, args=(_cmd_queue, _result_queue), daemon=True)
    _browser_proc.start()

    try:
        msg = _result_queue.get(timeout=20)
        if msg == "__READY__":
            ui.success("Browser started (Chromium).")
            return True
        if "Playwright not installed" in msg:
            return _install_playwright_and_retry()
        ui.error(msg)
        return False
    except Exception:
        ui.error("Browser failed to start (timeout).")
        return False


def _install_playwright_and_retry() -> bool:
    """Auto-install Playwright + Chromium, then restart the browser."""
    import subprocess
    ui.info("Playwright not found — installing automatically (this may take a minute)...")
    result = subprocess.run(
        "pip install playwright && playwright install chromium",
        shell=True, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        ui.error(f"Playwright install failed:\n{(result.stderr or result.stdout)[:400]}")
        return False
    ui.success("Playwright installed! Restarting browser...")
    global _browser_proc, _cmd_queue, _result_queue
    _browser_proc = None
    _cmd_queue = None
    _result_queue = None
    return _ensure_browser()


def _send_browser_cmd(func_name: str, timeout: int = 60, **kwargs) -> str:
    """Send a command to the persistent browser process."""
    if not _ensure_browser():
        return "Error: Browser not available."

    _cmd_queue.put({"func": func_name, "kw": kwargs})

    try:
        return _result_queue.get(timeout=timeout)
    except Exception:
        return f"Error: Browser operation '{func_name}' timed out ({timeout}s)."


def browser_navigate(url: str) -> str:
    """Navigate the browser to a URL and return page text."""
    # Resolve relative file:// URLs (e.g. file://./foo.html → file:///abs/path/foo.html)
    if url.startswith("file://") and not url.startswith("file:///"):
        from pathlib import Path
        url = Path(url[7:]).resolve().as_uri()
    ui.info("Opening in browser...")
    return _send_browser_cmd("navigate", timeout=45, url=url)


def browser_click(selector: str) -> str:
    """Click an element on the current page."""
    return _send_browser_cmd("click", selector=selector)


def browser_type(selector: str, text: str) -> str:
    """Type text into any element. Auto-tries fallback selectors (textarea, contenteditable, ProseMirror, input) if given selector fails."""
    return _send_browser_cmd("type", selector=selector, text=text)


def browser_press(key: str = "Enter") -> str:
    """Press a keyboard key (Enter, Tab, Escape, ArrowDown, etc)."""
    return _send_browser_cmd("press", key=key)


def browser_screenshot(path: str = "screenshot.png") -> str:
    """Take a screenshot of the current page."""
    return _send_browser_cmd("screenshot", path=path)


def browser_get_text(selector: str = "body") -> str:
    """Get text content of an element on the current page."""
    return _send_browser_cmd("get_text", selector=selector)


def browser_eval(expression: str) -> str:
    """Execute arbitrary JavaScript on the current page. Full power."""
    return _send_browser_cmd("eval", expression=expression)


def browser_wait(selector: str, timeout: int = 15000) -> str:
    """Wait for an element to become visible on the page."""
    return _send_browser_cmd("wait", selector=selector, timeout=timeout)


def browser_wait_idle(selector: str = "body", timeout: int = 30, stable: int = 3) -> str:
    """Wait for page content to stop changing. Use after sending a chat message to wait for the AI response."""
    return _send_browser_cmd("wait_idle", timeout=timeout + 15, selector=selector, wait_timeout=timeout, stable=stable)


def browser_get_console_errors() -> str:
    """Return all captured JS console errors/warnings since the last navigation."""
    return _send_browser_cmd("get_console_errors")


def browser_url() -> str:
    """Get the current page URL and title."""
    return _send_browser_cmd("url")


def browser_scroll(direction: str = "down", amount: int = 500) -> str:
    """Scroll the page up or down by a pixel amount."""
    return _send_browser_cmd("scroll", direction=direction, amount=amount)


# ── Tab management ──────────────────────────────────────────────

def browser_new_tab(url: str = "about:blank") -> str:
    """Open a new browser tab, optionally navigating to a URL."""
    return _send_browser_cmd("new_tab", timeout=45, url=url)


def browser_switch_tab(index: int = 0) -> str:
    """Switch to a browser tab by index. Use browser_list_tabs to see available tabs."""
    return _send_browser_cmd("switch_tab", index=index)


def browser_close_tab(index: int = -1) -> str:
    """Close a browser tab by index. -1 closes the current tab."""
    return _send_browser_cmd("close_tab", index=index)


def browser_list_tabs() -> str:
    """List all open browser tabs with their index, title, and URL."""
    return _send_browser_cmd("list_tabs")


def close_browser() -> None:
    """Shut down the persistent browser process."""
    global _browser_proc, _cmd_queue, _result_queue
    if _cmd_queue:
        try:
            _cmd_queue.put(None)  # Shutdown signal
        except Exception:
            pass
    if _browser_proc:
        _browser_proc.join(timeout=5)
        if _browser_proc.is_alive():
            _browser_proc.terminate()
    _browser_proc = None
    _cmd_queue = None
    _result_queue = None
