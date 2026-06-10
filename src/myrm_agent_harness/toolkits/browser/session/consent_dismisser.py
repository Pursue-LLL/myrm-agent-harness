"""Cookie consent auto-dismisser for BrowserSession.

[INPUT]
- (none — self-contained JS execution)

[OUTPUT]
- ConsentDismisser: auto-accept cookie consent banners after page navigation

[POS]
Automatically detects and accepts GDPR/cookie consent popups via JS evaluate
after page navigation. 7-phase strategy: CMP-specific Accept buttons → generic
attribute selectors → multilingual text matching (14 languages) → Shadow DOM
CMPs → CMP JS APIs (Didomi/Cookiebot/Osano/Klaro) → force-remove CMP
containers (55+ selectors + CMP iframes) → restore body scroll.
Zero LLM cost, ~50ms per invocation. Also hooked into Navigator for L2
web_fetch coverage (not just BrowserSession).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

_DISMISS_CONSENT_JS = """
async () => {
    const isVisible = (elem) => {
        if (!elem) return false;
        const style = window.getComputedStyle(elem);
        return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
    };

    // Phase 1: CMP-specific Accept button selectors (ordered by market share)
    const cmpAcceptSelectors = [
        '#onetrust-accept-btn-handler',
        '#accept-recommended-btn-handler',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
        '#CybotCookiebotDialogBodyButtonAccept',
        '#CybotCookiebotDialogBodyLevelButtonAccept',
        '#didomi-notice-agree-button',
        '.didomi-button-highlight',
        '.qc-cmp2-summary-buttons button[mode="primary"]',
        '.sp_choice_type_11',
        '.sp_choice_type_ACCEPT_ALL',
        '.fc-button.fc-cta-consent.fc-primary-button',
        '.fc-cta-consent',
        '.fc-confirm-choices',
        '#truste-consent-button',
        '.cmpboxbtnyes',
        '#cmpwelcomebtnyes',
        '.osano-cm-accept-all',
        '.osano-cm-accept',
        '#iubenda-cs-accept-btn',
        '.iubenda-cs-accept-btn',
        '.cmplz-btn.cmplz-accept',
        '.fides-accept-all-button',
        '.cky-btn-accept',
        '[data-cky-tag="accept-button"]',
        '.klaro .cm-btn-accept-all',
        '.klaro .cm-btn-success',
        '[data-tid="banner-accept"]',
        'button[data-cookiefirst-action="accept"]',
        '#cookiescript_accept',
        'a[data-cookie-accept-all]',
        '.brlbs-btn-accept-all',
        '#ccc-recommended-settings',
        '#ccc-notify-accept',
        '.coi-banner__accept',
        '#_evidon-accept-button',
        'button#axeptio_btn_acceptAll',
        '#hs-eu-confirmation-button',
        '.moove-gdpr-infobar-allow-all',
        '.cc-nb-okagree',
        '#tarteaucitronPersonalize2',
        '.tarteaucitronAllow',
        '.ch2-allow-all-btn',
        '#cn-accept-cookie',
        '.eu-cookie-compliance-banner .agree-button',
        '.eu-cookie-compliance-banner .accept-all',
        '#gdpr-cookie-consent-bar #cookie_action_accept',
        '[data-cli_action="accept"]',
        '#shopify-pc__banner__btn-accept',
        '[data-hook="ccsu-banner-accept"]',
        '[fs-consent-element="allow"]',
        '#pandectes-banner .cc-allow',
        '#cl-consent [data-role="b_agree"]',
        '.snigel-cmp-framework #accept-choices',
        '.cassie-accept-all',
        '#acceptAllMain',
        '#pt-accept-all',
        '#unic-agree',
        '#ez-accept-all',
        '#s-all-bn',
        '.cm__btn[data-role="all"]',
        '#lm-accept-all',
        '.rcb-banner-cta-accept-all',
        '#bnp_btn_accept',
        '#catapultCookie',
        '.isense-cc-allow',
        '#adopt-accept-all-button',
        'button#acceptAllCookieButton',
        '#kc-acceptAndHide',
        '#ct-ultimate-gdpr-cookie-accept',
    ];

    // Phase 2: Generic attribute-based Accept selectors
    const genericAcceptSelectors = [
        'button[id*="accept" i]',
        'button[class*="accept-all" i]',
        'button[class*="acceptAll" i]',
        'a[id*="accept" i]',
        'button[id*="agree" i]',
        'button[class*="agree" i]',
        'button[class*="allow-all" i]',
        'button[class*="allowAll" i]',
        'button[data-action="accept"]',
        'button[data-action="accept-all"]',
        'button[data-gdpr="accept"]',
        'button[data-consent="accept"]',
    ];

    const clickButton = async (selectors) => {
        for (const selector of selectors) {
            try {
                const btn = document.querySelector(selector);
                if (btn && isVisible(btn)) {
                    btn.click();
                    await new Promise(r => setTimeout(r, 200));
                    return true;
                }
            } catch (e) { /* continue */ }
        }
        return false;
    };

    let accepted = await clickButton(cmpAcceptSelectors);
    if (accepted) return { dismissed: true, method: "cmp_selector" };

    accepted = await clickButton(genericAcceptSelectors);
    if (accepted) return { dismissed: true, method: "generic_selector" };

    // Phase 3: Multilingual text content matching
    const acceptPatterns = [
        /^accept\\s*(all)?(\\s*cookies)?$/i,
        /^allow\\s*(all)?(\\s*cookies)?$/i,
        /^i\\s*agree$/i,
        /^agree(\\s*(and|&)\\s*(close|continue))?$/i,
        /^got\\s*it[!]?$/i,
        /^consent$/i,
        /^(accept|agree)\\s*&?\\s*close$/i,
        // German
        /^alle\\s*akzeptieren$/i,
        /^akzeptieren$/i,
        /^alle\\s*annehmen$/i,
        // French
        /^tout\\s*accepter$/i,
        /^accepter$/i,
        /^j'accepte$/i,
        // Spanish
        /^aceptar\\s*todo$/i,
        /^aceptar$/i,
        // Italian
        /^accetta\\s*tutto$/i,
        /^accetto$/i,
        // Dutch
        /^alles\\s*accepteren$/i,
        /^accepteren$/i,
        // Portuguese
        /^aceitar\\s*tudo$/i,
        /^aceitar$/i,
        // Chinese
        /^全部接受$/,
        /^同意$/,
        /^接受$/,
        /^全部同意$/,
        // Japanese
        /^すべて受け入れる$/,
        /^同意する$/,
        /^すべて許可$/,
        // Korean
        /^모두\\s*수락$/,
        /^동의$/,
        // Polish
        /^zaakceptuj\\s*wszystkie$/i,
        /^akceptuję$/i,
        // Swedish
        /^acceptera\\s*alla$/i,
        // Danish / Norwegian
        /^accepter\\s*alle$/i,
        /^godta\\s*alle$/i,
    ];

    const candidates = document.querySelectorAll(
        'button, a[role="button"], [role="button"], input[type="submit"], input[type="button"]'
    );
    for (const btn of candidates) {
        const text = (btn.textContent || btn.value || '').trim();
        if (text.length > 0 && text.length < 40) {
            for (const pattern of acceptPatterns) {
                if (pattern.test(text) && isVisible(btn)) {
                    btn.click();
                    await new Promise(r => setTimeout(r, 200));
                    return { dismissed: true, method: "text_match" };
                }
            }
        }
    }

    // Phase 4: Shadow DOM CMPs (Usercentrics, Axeptio)
    const shadowRoots = [
        { id: 'usercentrics-root', btn: 'button[data-testid="uc-accept-all-button"]' },
        { cls: 'axeptio_mount', btn: 'button#axeptio_btn_acceptAll' },
    ];
    for (const cfg of shadowRoots) {
        try {
            const host = cfg.id
                ? document.getElementById(cfg.id)
                : document.querySelector('.' + cfg.cls);
            if (host && host.shadowRoot) {
                const btn = host.shadowRoot.querySelector(cfg.btn);
                if (btn) {
                    btn.click();
                    await new Promise(r => setTimeout(r, 200));
                    return { dismissed: true, method: "shadow_dom" };
                }
            }
        } catch (e) { /* continue */ }
    }

    // Phase 5: CMP JavaScript APIs
    try {
        if (typeof window.__tcfapi === 'function') {
            window.__tcfapi('addEventListener', 2, () => {});
        }
        if (typeof window.Didomi !== 'undefined' && window.Didomi.setUserAgreeToAll) {
            window.Didomi.setUserAgreeToAll();
            return { dismissed: true, method: "didomi_api" };
        }
        if (typeof window.Cookiebot !== 'undefined' && window.Cookiebot.submitCustomConsent) {
            window.Cookiebot.submitCustomConsent(true, true, true);
            return { dismissed: true, method: "cookiebot_api" };
        }
        if (typeof window.Osano !== 'undefined' && window.Osano.cm) {
            window.Osano.cm.acceptAll();
            return { dismissed: true, method: "osano_api" };
        }
        if (typeof window.klaro !== 'undefined' && window.klaro.getManager) {
            window.klaro.getManager().acceptAll();
            return { dismissed: true, method: "klaro_api" };
        }
    } catch (e) { /* continue */ }

    // Phase 6: Force-remove CMP containers (last resort when all click attempts fail)
    const cmpContainerSelectors = [
        '#onetrust-consent-sdk', '#onetrust-banner-sdk', '.onetrust-pc-dark-filter',
        '#CybotCookiebotDialog', '#CybotCookiebotDialogBodyUnderlay',
        '#truste-consent-track', '.truste_overlay', '.truste_box_overlay',
        '.qc-cmp2-container', '#qc-cmp2-main',
        '#didomi-host', '#didomi-popup', '#didomi-notice',
        '#usercentrics-root',
        'div[id^="sp_message_container"]', '.sp_message_container',
        '.fc-consent-root', '.fc-dialog-overlay',
        '.klaro',
        '.osano-cm-window', '.osano-cm-dialog',
        '#iubenda-cs-banner',
        '.cmplz-cookiebanner',
        '.cky-consent-container', '.cky-overlay',
        '.cmpbox', '#cmpbox',
        '.fides-overlay', '#fides-banner',
        '#termly-code-snippet-support',
        '#cookiefirst-root',
        '#cookiescript_injected',
        '#BorlabsCookieBox',
        '#ccc', '#ccc-module',
        '#cookie-information-template-wrapper',
        '.axeptio_widget',
        '#hs-eu-cookie-confirmation',
        '#lanyard_root',
        '#tarteaucitronRoot', '#tarteaucitronAlertBig',
        '.ch2-container',
        '#moove_gdpr_cookie_info_bar',
        '.termsfeed-com---nb',
        '#cookie-notice',
        '#cookie-law-info-bar',
        '.eu-cookie-compliance-banner',
        '#gdpr-cookie-consent-bar',
        '#shopify-pc__banner',
        '[data-hook="ccsu-banner-wrapper"]',
        '#pandectes-banner',
        '#cl-consent',
        '.snigel-cmp-framework',
        '#cc--main', '#cc-main',
        '.rcb-banner',
        '#bnp_container', '#bnp_cookie_banner',
        '[class*="cookie-consent" i]', '[id*="cookie-consent" i]',
        '[class*="cookie-banner" i]', '[id*="cookie-banner" i]',
        '[class*="consent-banner" i]', '[id*="consent-banner" i]',
        '[class*="gdpr-banner" i]', '[id*="gdpr-banner" i]',
        '[class*="cookie-notice" i]', '[id*="cookie-notice" i]',
        '[class*="cookie-popup" i]', '[id*="cookie-popup" i]',
        '.cc-banner', '.cc-window',
    ];

    let removed = 0;
    for (const selector of cmpContainerSelectors) {
        try {
            document.querySelectorAll(selector).forEach(el => { el.remove(); removed++; });
        } catch (e) { /* continue */ }
    }

    // Remove CMP iframes
    const cmpIframeSelectors = [
        'iframe[id^="sp_message_iframe"]',
        'iframe[src*="consent" i]',
        'iframe[src*="cookiebot" i]',
        'iframe[src*="trustarc" i]',
        'iframe[title*="consent" i]',
        'iframe[title*="cookie" i]',
        'iframe[name="__tcfapiLocator"]',
    ];
    for (const selector of cmpIframeSelectors) {
        try {
            document.querySelectorAll(selector).forEach(el => { el.remove(); removed++; });
        } catch (e) { /* continue */ }
    }

    // Phase 7: Restore body scroll (after removal or if scroll was locked by CMP)
    const restoreScroll = () => {
        document.body.style.overflow = '';
        document.body.style.overflowY = '';
        document.body.style.position = '';
        document.documentElement.style.overflow = '';
        document.documentElement.style.overflowY = '';
        const cmpClasses = [
            'ot-overflow-hidden', 'sp_message_open', 'didomi-popup-open',
            'cmpbox-show', 'cmplz-blocked', 'qc-cmp2-no-scroll',
            'osano-cm-show', 'cky-modal-open', 'fides-overlay-modal-open',
            'cc-no-scroll', 'fc-consent-root-open', 'cookies-request',
            'eu-cookie-compliance-popup-open', 'has-cookie-bar',
        ];
        for (const cls of cmpClasses) {
            document.body.classList.remove(cls);
            document.documentElement.classList.remove(cls);
        }
    };

    if (removed > 0) {
        restoreScroll();
        return { dismissed: true, method: "container_removal" };
    }

    const scrollLocked = (
        document.body.style.overflow === 'hidden' ||
        document.documentElement.style.overflow === 'hidden'
    );
    if (scrollLocked) restoreScroll();

    return { dismissed: false, method: null };
}
"""


class ConsentDismisser:
    """Auto-accepts cookie consent banners after page navigation.

    Executes a single JS evaluate that attempts to click Accept buttons
    using CMP-specific selectors, generic selectors, multilingual text
    matching, Shadow DOM traversal, and CMP JS API calls.

    Lifecycle:
        1. Constructed with enabled flag
        2. dismiss(page) called after navigate() completes
        3. Returns a description string if consent was dismissed, None otherwise
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    async def dismiss(self, page: Page) -> str | None:
        """Attempt to dismiss cookie consent on the current page.

        Returns:
            A short description if consent was dismissed, None otherwise.
        """
        if not self._enabled:
            return None

        try:
            result = await page.evaluate(_DISMISS_CONSENT_JS)
            if result and result.get("dismissed"):
                method = result.get("method", "unknown")
                logger.info("ConsentDismisser: dismissed via %s", method)
                return f"[Cookie consent auto-accepted via {method}]"
        except Exception as exc:
            logger.debug("ConsentDismisser: JS evaluation failed: %s", exc)

        return None
