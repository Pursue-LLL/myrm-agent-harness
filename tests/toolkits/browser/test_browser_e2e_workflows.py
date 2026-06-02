"""E2E tests for complete user workflows — real-world scenarios.

Tests complete end-to-end workflows that users would actually perform:
- Form filling and submission
- Multi-step interactions
- Dynamic content verification
- Navigation flows

Run with: pytest -m e2e tests/toolkits/browser/test_browser_e2e_workflows.py
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
    """BrowserSession for E2E workflows."""
    session = BrowserSession(browser_pool, ContextType.AGENT)
    yield session
    await session.close()


# =============================================================================
# Workflow 1: Search form interaction
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_search_form_complete(browser_session: BrowserSession) -> None:
    """Complete workflow: load page → fill form → submit → verify results."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    # Create search form page
    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <form id="searchForm">
                <input type="text" id="query" placeholder="Search query"/>
                <button type="submit" id="searchBtn">Search</button>
            </form>
            <div id="results"></div>
            <script>
                document.getElementById('searchForm').addEventListener('submit', (e) => {
                    e.preventDefault();
                    const query = document.getElementById('query').value;
                    document.getElementById('results').innerText = 'Results for: ' + query;
                });
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Step 1: Snapshot to get refs
    result = await browser_session.snapshot(scope="content", diff=False)
    assert result.meta.ref_count >= 2  # query textbox + submit button

    # Step 2: Fill search query
    await page.fill("#query", "Python Programming")
    await asyncio.sleep(0.2)

    # Step 3: Click submit
    await page.click("#searchBtn")
    await asyncio.sleep(0.5)

    # Step 4: Verify results
    text = await browser_session.extract_text()
    assert "Results for: Python Programming" in text


# =============================================================================
# Workflow 2: Multi-step form filling
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_multi_step_form_filling(browser_session: BrowserSession) -> None:
    """Multi-step form: personal info → address → review → submit."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <div id="step1" class="step">
                <h2>Step 1: Personal Info</h2>
                <input type="text" id="name" placeholder="Name"/>
                <input type="email" id="email" placeholder="Email"/>
                <button id="next1" onclick="showStep(2)">Next</button>
            </div>
            <div id="step2" class="step" style="display:none">
                <h2>Step 2: Address</h2>
                <input type="text" id="city" placeholder="City"/>
                <button id="next2" onclick="showStep(3)">Next</button>
            </div>
            <div id="step3" class="step" style="display:none">
                <h2>Step 3: Review</h2>
                <div id="review"></div>
                <button id="submit" onclick="submitForm()">Submit</button>
            </div>
            <div id="confirmation" style="display:none">
                <h2>Success!</h2>
            </div>
            <script>
                function showStep(num) {
                    document.querySelectorAll('.step').forEach(s => s.style.display = 'none');
                    document.getElementById('step' + num).style.display = 'block';
                    if (num === 3) {
                        const name = document.getElementById('name').value;
                        const email = document.getElementById('email').value;
                        const city = document.getElementById('city').value;
                        document.getElementById('review').innerText =
                            `Name: ${name}, Email: ${email}, City: ${city}`;
                    }
                }
                function submitForm() {
                    document.querySelectorAll('.step').forEach(s => s.style.display = 'none');
                    document.getElementById('confirmation').style.display = 'block';
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Step 1: Fill personal info
    await page.fill("#name", "John Doe")
    await page.fill("#email", "john@example.com")
    await page.click("#next1")
    await asyncio.sleep(0.3)

    # Step 2: Fill address
    await page.fill("#city", "San Francisco")
    await page.click("#next2")
    await asyncio.sleep(0.3)

    # Step 3: Review and submit
    text = await browser_session.extract_text()
    assert "John Doe" in text
    assert "john@example.com" in text
    assert "San Francisco" in text

    await page.click("#submit")
    await asyncio.sleep(0.3)

    # Verify confirmation
    final_text = await browser_session.extract_text()
    assert "Success!" in final_text


# =============================================================================
# Workflow 3: Dynamic content loading
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_dynamic_content_loading(browser_session: BrowserSession) -> None:
    """Test workflow with AJAX-like dynamic content."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <button id="loadBtn" onclick="loadContent()">Load Content</button>
            <div id="content"></div>
            <script>
                function loadContent() {
                    document.getElementById('loadBtn').disabled = true;
                    document.getElementById('content').innerText = 'Loading...';
                    setTimeout(() => {
                        document.getElementById('content').innerHTML =
                            '<h2>Loaded Data</h2><ul><li>Item 1</li><li>Item 2</li></ul>';
                    }, 500);
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Click load button
    await page.click("#loadBtn")
    await asyncio.sleep(0.2)

    # Verify loading state
    text_loading = await browser_session.extract_text()
    assert "Loading..." in text_loading

    # Wait for content to load
    await asyncio.sleep(0.6)

    # Verify loaded content
    text_loaded = await browser_session.extract_text()
    assert "Loaded Data" in text_loaded
    assert "Item 1" in text_loaded
    assert "Item 2" in text_loaded


# =============================================================================
# Workflow 4: Navigation with history
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_navigation_with_history(browser_session: BrowserSession) -> None:
    """Test navigation flow with back/forward."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    # Page 1
    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <h1>Page 1</h1>
            <a href="#page2" onclick="navigate(2); return false;">Go to Page 2</a>
            <div id="content">Content 1</div>
            <script>
                function navigate(num) {
                    document.querySelector('h1').innerText = 'Page ' + num;
                    document.getElementById('content').innerText = 'Content ' + num;
                    if (num === 2) {
                        document.body.innerHTML += '<a href=\"#page3\" onclick=\"navigate(3); return false;\">Go to Page 3</a>';
                    }
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Navigate to page 2
    await page.click("a")
    await asyncio.sleep(0.3)

    text2 = await browser_session.extract_text()
    assert "Page 2" in text2
    assert "Content 2" in text2

    # Navigate to page 3
    await page.click("a")
    await asyncio.sleep(0.3)

    text3 = await browser_session.extract_text()
    assert "Page 3" in text3


# =============================================================================
# Workflow 5: Form validation and error handling
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_form_validation_recovery(browser_session: BrowserSession) -> None:
    """Test form validation errors and recovery."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <form id="myForm">
                <input type="email" id="email" required/>
                <button type="submit">Submit</button>
            </form>
            <div id="error" style="color:red;display:none"></div>
            <div id="success" style="color:green;display:none"></div>
            <script>
                document.getElementById('myForm').addEventListener('submit', (e) => {
                    e.preventDefault();
                    const email = document.getElementById('email').value;
                    const errorDiv = document.getElementById('error');
                    const successDiv = document.getElementById('success');

                    errorDiv.style.display = 'none';
                    successDiv.style.display = 'none';

                    if (!email.includes('@')) {
                        errorDiv.innerText = 'Invalid email';
                        errorDiv.style.display = 'block';
                    } else {
                        successDiv.innerText = 'Form submitted successfully';
                        successDiv.style.display = 'block';
                    }
                });
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Submit with invalid email
    await page.fill("#email", "invalid-email")
    await page.evaluate("""
        document.getElementById('myForm').dispatchEvent(
            new Event('submit', {bubbles: true, cancelable: true})
        );
    """)
    await asyncio.sleep(0.3)

    # Check error visibility
    error_visible = await page.evaluate("document.getElementById('error').style.display !== 'none'")
    assert error_visible

    # Submit with valid email
    await page.fill("#email", "user@example.com")
    await page.evaluate("""
        document.getElementById('myForm').dispatchEvent(
            new Event('submit', {bubbles: true, cancelable: true})
        );
    """)
    await asyncio.sleep(0.3)

    # Verify success
    success_visible = await page.evaluate("document.getElementById('success').style.display !== 'none'")
    assert success_visible


# =============================================================================
# Workflow 6: Modal dialog interaction
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_modal_dialog_interaction(browser_session: BrowserSession) -> None:
    """Test workflow with modal dialogs."""
    tab_id = await browser_session.new_tab("about:blank")
    page = browser_session._tab_controller._tabs[tab_id].page

    await page.set_content("""
        <!DOCTYPE html>
        <html><body>
            <button id="openModal" onclick="showModal()">Open Modal</button>
            <div id="modal" style="display:none; position:fixed; top:50%; left:50%; background:white; padding:20px;">
                <h2>Modal Title</h2>
                <input type="text" id="modalInput" placeholder="Enter text"/>
                <button id="closeModal" onclick="closeModal()">Close</button>
            </div>
            <div id="result"></div>
            <script>
                function showModal() {
                    document.getElementById('modal').style.display = 'block';
                }
                function closeModal() {
                    const value = document.getElementById('modalInput').value;
                    document.getElementById('modal').style.display = 'none';
                    document.getElementById('result').innerText = 'Entered: ' + value;
                }
            </script>
        </body></html>
    """)
    await asyncio.sleep(0.5)

    # Open modal
    await page.click("#openModal")
    await asyncio.sleep(0.3)

    # Verify modal is visible
    modal_visible = await page.evaluate("document.getElementById('modal').style.display !== 'none'")
    assert modal_visible

    # Fill modal input
    await page.fill("#modalInput", "Test Data")
    await asyncio.sleep(0.2)

    # Close modal
    await page.click("#closeModal")
    await asyncio.sleep(0.3)

    # Verify result
    text = await browser_session.extract_text()
    assert "Entered: Test Data" in text


# =============================================================================
# Workflow 7: Tab switching workflow
# =============================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_multi_tab_coordination(browser_session: BrowserSession) -> None:
    """Test workflow coordinating multiple tabs."""
    # Create tab 1
    tab1 = await browser_session.new_tab("about:blank")
    page1 = browser_session._tab_controller._tabs[tab1].page
    await page1.set_content("<html><body><h1>Tab 1 Content</h1></body></html>")
    await asyncio.sleep(0.3)

    # Create tab 2
    tab2 = await browser_session.new_tab("about:blank")
    page2 = browser_session._tab_controller._tabs[tab2].page
    await page2.set_content("<html><body><h1>Tab 2 Content</h1></body></html>")
    await asyncio.sleep(0.3)

    # Verify tab 2 is active
    text2 = await browser_session.extract_text()
    assert "Tab 2 Content" in text2

    # Switch to tab 1
    await browser_session.switch_tab(tab1)
    await asyncio.sleep(0.2)

    # Verify tab 1 is active
    text1 = await browser_session.extract_text()
    assert "Tab 1 Content" in text1

    # Switch back to tab 2
    await browser_session.switch_tab(tab2)
    await asyncio.sleep(0.2)

    # Verify tab 2 is active again
    text2_again = await browser_session.extract_text()
    assert "Tab 2 Content" in text2_again
