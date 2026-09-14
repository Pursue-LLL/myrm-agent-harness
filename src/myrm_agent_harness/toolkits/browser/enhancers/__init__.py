"""DOM Enhancers for the browser toolkit."""

from .dom_enhancer_loader import get_dom_enhancer_script
from .inject_route import install_document_script_injection

__all__ = ["get_dom_enhancer_script", "install_document_script_injection"]
