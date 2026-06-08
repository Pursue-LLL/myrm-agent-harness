"""E2E tests for complex page scenarios.

Tests handling of challenging real-world page scenarios:
- Large pages with many elements
- SPAs with dynamic routing
- Nested frames and shadow DOM
- Complex forms and interactions

Run with: pytest -m e2e tests/toolkits/browser/test_browser_e2e_complex_pages.py
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession


@pytest.fixture
async def browser_pool() -> GlobalBrowserPool:
    """Real browser pool for E2E tests."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    yield pool
    await pool.shutdown()


@pytest.fixture
async def browser_session(browser_pool: GlobalBrowserPool) -> BrowserSession:
    """BrowserSession for complex page tests."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


# =============================================================================
# Complex 1: Large page with many elements
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_page_with_many_elements(browser_session: BrowserSession) -> None:
    """Test page with 1000+ interactive elements."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    # Generate large page
    buttons_html = "\n".join([f'<button id="btn{i}">Button {i}</button>' for i in range(1000)])
    await page.set_content(f"""
        <!DOCTYPE html>
        <html><body>
            <h1>Large Page Test</h1>
            {buttons_html}
        </body></html>
    """)
    await asyncio.sleep(1.0)

    # Snapshot should handle large tree
    result = await browser_session.snapshot(scope="content", diff=False)

    # Verify refs are generated
    assert result.meta.ref_count >= 100  # Should have many refs

    # Verify specific elements are in tree
    text = await browser_session.extract_text()
    assert "Button 0" in text and "Button 999" in text


# =============================================================================
# Complex 2: Deeply nested structure
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_deeply_nested_dom(browser_session: BrowserSession) -> None:
    """Test page with deeply nested DOM structure."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    # Generate nested structure
    nested_html = "<div>" * 50 + "<button id='deepBtn'>Deep Button</button>" + "</div>" * 50

    await page.set_content(f"""
        <!DOCTYPE html>
        <html><body>
            <h1>Nested Structure Test</h1>
            {nested_html}
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Should handle deep nesting
    result = await browser_session.snapshot(scope="content", diff=False)
    assert result.meta.ref_count >= 1

    # Verify deep button is accessible
    text = await browser_session.extract_text()
    assert "Deep Button" in text


# =============================================================================
# Complex 3: Dynamic SPA routing
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_spa_dynamic_routing(browser_session: BrowserSession) -> None:
    """Test SPA with client-side routing."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <nav>
                <a href="#home" onclick="navigate('home'); return false;">Home</a>
                <a href="#about" onclick="navigate('about'); return false;">About</a>
                <a href="#contact" onclick="navigate('contact'); return false;">Contact</a>
            </nav>
            <div id="content">
                <h1>Home Page</h1>
                <p>Welcome to home</p>
            </div>
            <script>
                function navigate(page) {
                    const content = document.getElementById('content');
                    if (page === 'home') {
                        content.innerHTML = '<h1>Home Page</h1><p>Welcome to home</p>';
                    } else if (page === 'about') {
                        content.innerHTML = '<h1>About Page</h1><p>Learn more about us</p>';
                    } else if (page === 'contact') {
                        content.innerHTML = '<h1>Contact Page</h1><p>Get in touch</p>';
                    }
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Navigate to About
    await page.click("a:has-text('About')")
    await asyncio.sleep(0.5)

    # Verify content changed via evaluate
    content_html = await page.evaluate("document.getElementById('content').innerHTML")
    assert "About Page" in content_html

    # Navigate to Contact
    await page.click("a:has-text('Contact')")
    await asyncio.sleep(0.5)

    content_html = await page.evaluate("document.getElementById('content').innerHTML")
    assert "Contact Page" in content_html


# =============================================================================
# Complex 4: Multiple form types
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_multi_input_form(browser_session: BrowserSession) -> None:
    """Test form with various input types."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <form id="complexForm">
                <input type="text" id="name" placeholder="Name"/>
                <input type="email" id="email" placeholder="Email"/>
                <select id="country">
                    <option value="">Select country</option>
                    <option value="us">USA</option>
                    <option value="uk">UK</option>
                </select>
                <input type="checkbox" id="terms"/>
                <label for="terms">Accept terms</label>
                <textarea id="comments" placeholder="Comments"></textarea>
                <button type="submit">Submit</button>
            </form>
            <div id="result"></div>
            <script>
                document.getElementById('complexForm').addEventListener('submit', (e) => {
                    e.preventDefault();
                    const data = {
                        name: document.getElementById('name').value,
                        email: document.getElementById('email').value,
                        country: document.getElementById('country').value,
                        terms: document.getElementById('terms').checked,
                        comments: document.getElementById('comments').value
                    };
                    document.getElementById('result').innerText = JSON.stringify(data);
                });
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Fill all form fields
    await page.fill("#name", "Alice")
    await page.fill("#email", "alice@test.com")
    await page.select_option("#country", "us")
    await page.check("#terms")
    await page.fill("#comments", "This is a test comment")
    await asyncio.sleep(0.3)

    # Submit form
    await page.click("button[type='submit']")
    await asyncio.sleep(0.5)

    # Verify all data was captured
    result_text = await page.evaluate("document.getElementById('result').innerText")
    assert "Alice" in result_text
    assert "alice@test.com" in result_text
    assert "us" in result_text
    assert "test comment" in result_text


# =============================================================================
# Complex 5: Infinite scroll simulation
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_infinite_scroll(browser_session: BrowserSession) -> None:
    """Test handling of infinite scroll content loading."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body style="height: 2000px;">
            <div id="content">
                <div class="item">Item 1</div>
                <div class="item">Item 2</div>
            </div>
            <script>
                let itemCount = 2;
                window.addEventListener('scroll', () => {
                    if ((window.innerHeight + window.scrollY) >= document.body.offsetHeight - 100) {
                        if (itemCount < 10) {
                            itemCount++;
                            const div = document.createElement('div');
                            div.className = 'item';
                            div.innerText = 'Item ' + itemCount;
                            document.getElementById('content').appendChild(div);
                        }
                    }
                });
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Initial items
    text1 = await browser_session.extract_text()
    assert "Item 1" in text1
    assert "Item 2" in text1

    # Scroll to trigger load
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(0.5)

    # Check new items loaded
    text2 = await browser_session.extract_text()
    assert "Item 3" in text2 or await page.evaluate("document.querySelectorAll('.item').length > 2")


# =============================================================================
# Complex 6: Table with sorting and filtering
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_interactive_table(browser_session: BrowserSession) -> None:
    """Test interactive table with sorting."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <table id="dataTable">
                <thead>
                    <tr>
                        <th onclick="sortTable()">Name</th>
                        <th>Age</th>
                    </tr>
                </thead>
                <tbody id="tbody">
                    <tr><td>Charlie</td><td>30</td></tr>
                    <tr><td>Alice</td><td>25</td></tr>
                    <tr><td>Bob</td><td>35</td></tr>
                </tbody>
            </table>
            <script>
                function sortTable() {
                    const tbody = document.getElementById('tbody');
                    const rows = Array.from(tbody.querySelectorAll('tr'));
                    rows.sort((a, b) =>
                        a.cells[0].innerText.localeCompare(b.cells[0].innerText)
                    );
                    tbody.innerHTML = '';
                    rows.forEach(row => tbody.appendChild(row));
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Initial order
    text_before = await browser_session.extract_text()
    assert text_before.index("Charlie") < text_before.index("Alice")

    # Click to sort
    await page.click("th:has-text('Name')")
    await asyncio.sleep(0.5)

    # Verify sorted order
    text_after = await browser_session.extract_text()
    assert text_after.index("Alice") < text_after.index("Bob")
    assert text_after.index("Bob") < text_after.index("Charlie")


# =============================================================================
# Complex 7: Conditional rendering
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_conditional_rendering(browser_session: BrowserSession) -> None:
    """Test conditional UI rendering based on user actions."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <select id="userType" onchange="updateForm()">
                <option value="">Select type</option>
                <option value="individual">Individual</option>
                <option value="business">Business</option>
            </select>
            <div id="individualForm" style="display:none">
                <input type="text" id="firstName" placeholder="First Name"/>
                <input type="text" id="lastName" placeholder="Last Name"/>
            </div>
            <div id="businessForm" style="display:none">
                <input type="text" id="companyName" placeholder="Company Name"/>
                <input type="text" id="taxId" placeholder="Tax ID"/>
            </div>
            <script>
                function updateForm() {
                    const type = document.getElementById('userType').value;
                    document.getElementById('individualForm').style.display =
                        type === 'individual' ? 'block' : 'none';
                    document.getElementById('businessForm').style.display =
                        type === 'business' ? 'block' : 'none';
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Select individual
    await page.select_option("#userType", "individual")
    await asyncio.sleep(0.3)

    # Verify individual form visible
    individual_visible = await page.evaluate("document.getElementById('individualForm').style.display !== 'none'")
    assert individual_visible

    # Select business
    await page.select_option("#userType", "business")
    await asyncio.sleep(0.3)

    # Verify business form visible
    business_visible = await page.evaluate("document.getElementById('businessForm').style.display !== 'none'")
    assert business_visible


# =============================================================================
# Complex 8: Drag and drop simulation
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_drag_and_drop(browser_session: BrowserSession) -> None:
    """Test drag and drop interactions."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <div id="source" draggable="true" style="width:100px;height:50px;background:blue;">
                Drag me
            </div>
            <div id="target" style="width:200px;height:100px;background:lightgray;margin-top:20px;">
                Drop here
            </div>
            <div id="status"></div>
            <script>
                document.getElementById('source').addEventListener('dragstart', (e) => {
                    e.dataTransfer.setData('text', 'dragged');
                });
                document.getElementById('target').addEventListener('dragover', (e) => {
                    e.preventDefault();
                });
                document.getElementById('target').addEventListener('drop', (e) => {
                    e.preventDefault();
                    document.getElementById('status').innerText = 'Dropped successfully';
                });
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Perform drag and drop using Playwright API
    source = await page.query_selector("#source")
    target = await page.query_selector("#target")

    # Get bounding boxes
    source_box = await source.bounding_box()
    target_box = await target.bounding_box()

    # Perform drag
    await page.mouse.move(source_box["x"] + 50, source_box["y"] + 25)
    await page.mouse.down()
    await page.mouse.move(target_box["x"] + 100, target_box["y"] + 50, steps=10)
    await page.mouse.up()
    await asyncio.sleep(0.5)

    # Verify drop
    text = await browser_session.extract_text()
    assert "Dropped successfully" in text


# =============================================================================
# Complex 9: Real-time content updates
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_realtime_updates(browser_session: BrowserSession) -> None:
    """Test handling of real-time content updates."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Real-time Updates</h1>
            <div id="counter">0</div>
            <button id="start" onclick="startUpdates()">Start Updates</button>
            <button id="stop" onclick="stopUpdates()">Stop Updates</button>
            <script>
                let interval = null;
                let count = 0;
                function startUpdates() {
                    if (!interval) {
                        interval = setInterval(() => {
                            count++;
                            document.getElementById('counter').innerText = count;
                        }, 100);
                    }
                }
                function stopUpdates() {
                    if (interval) {
                        clearInterval(interval);
                        interval = null;
                    }
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Start updates
    await page.click("#start")
    await asyncio.sleep(1.0)

    # Check counter increased
    counter1 = await page.evaluate("parseInt(document.getElementById('counter').innerText)")
    assert counter1 > 0

    # Wait more
    await asyncio.sleep(0.5)

    # Check counter increased further
    counter2 = await page.evaluate("parseInt(document.getElementById('counter').innerText)")
    assert counter2 > counter1

    # Stop updates
    await page.click("#stop")
    await asyncio.sleep(0.3)
    counter3 = await page.evaluate("parseInt(document.getElementById('counter').innerText)")

    # Wait and verify counter stopped
    await asyncio.sleep(0.5)
    counter4 = await page.evaluate("parseInt(document.getElementById('counter').innerText)")
    assert counter4 == counter3  # Should not increase


# =============================================================================
# Complex 10: Shadow DOM penetration in text extraction
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_shadow_dom_text_extraction(browser_session: BrowserSession) -> None:
    """Test that extract_text correctly penetrates open Shadow DOM."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Shadow DOM Test</h1>
            <p>Light DOM content</p>
            <div id="shadow-host"></div>
            <script>
                const host = document.getElementById('shadow-host');
                const shadow = host.attachShadow({mode: 'open'});
                shadow.innerHTML = '<p>Shadow content visible only via penetration</p>';
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    text = await browser_session.extract_text()

    assert "Light DOM content" in text
    assert "Shadow content visible only via penetration" in text


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_nested_shadow_dom_text_extraction(browser_session: BrowserSession) -> None:
    """Test nested Shadow DOM (shadow root inside shadow root)."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Nested Shadow Test</h1>
            <div id="outer-host"></div>
            <script>
                const outerHost = document.getElementById('outer-host');
                const outerShadow = outerHost.attachShadow({mode: 'open'});
                outerShadow.innerHTML = '<p>Outer shadow</p><div id="inner-host"></div>';
                const innerHost = outerShadow.getElementById('inner-host');
                const innerShadow = innerHost.attachShadow({mode: 'open'});
                innerShadow.innerHTML = '<p>Inner shadow deeply nested</p>';
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    text = await browser_session.extract_text()

    assert "Nested Shadow Test" in text
    assert "Outer shadow" in text
    assert "Inner shadow deeply nested" in text


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_closed_shadow_dom_not_accessible(browser_session: BrowserSession) -> None:
    """Test that closed Shadow DOM content is correctly skipped (browser security boundary)."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Closed Shadow Test</h1>
            <p>Visible light content</p>
            <div id="closed-host"></div>
            <script>
                const host = document.getElementById('closed-host');
                const shadow = host.attachShadow({mode: 'closed'});
                shadow.innerHTML = '<p>Closed shadow secret</p>';
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    text = await browser_session.extract_text()

    assert "Visible light content" in text
    assert "Closed shadow secret" not in text


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_shadow_dom_with_slot_projection(browser_session: BrowserSession) -> None:
    """Test Shadow DOM with <slot> projection extracts both shadow and light DOM content."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Slot Projection Test</h1>
            <div id="slot-host">
                <span>Projected light content</span>
            </div>
            <script>
                const host = document.getElementById('slot-host');
                const shadow = host.attachShadow({mode: 'open'});
                shadow.innerHTML = '<div>Shadow wrapper</div><slot></slot>';
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    text = await browser_session.extract_text()

    assert "Slot Projection Test" in text
    assert "Shadow wrapper" in text
    assert "Projected light content" in text


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_page_without_shadow_dom_unaffected(browser_session: BrowserSession) -> None:
    """Test that pages without Shadow DOM still work correctly (regression guard)."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>No Shadow</h1>
            <p>Regular paragraph</p>
            <ul><li>List item 1</li><li>List item 2</li></ul>
            <a href="https://example.com">Example Link</a>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    text = await browser_session.extract_text()

    assert "No Shadow" in text
    assert "Regular paragraph" in text
    assert "List item 1" in text
    assert "List item 2" in text


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complex_shadow_dom_hidden_elements_skipped(browser_session: BrowserSession) -> None:
    """Test that hidden elements inside Shadow DOM are correctly skipped."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Hidden Shadow Test</h1>
            <div id="shadow-host"></div>
            <script>
                const host = document.getElementById('shadow-host');
                const shadow = host.attachShadow({mode: 'open'});
                shadow.innerHTML = `
                    <p>Visible shadow text</p>
                    <p style="display:none">Hidden shadow text</p>
                    <p style="visibility:hidden">Invisible shadow text</p>
                `;
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    text = await browser_session.extract_text()

    assert "Visible shadow text" in text
    assert "Hidden shadow text" not in text
    assert "Invisible shadow text" not in text
