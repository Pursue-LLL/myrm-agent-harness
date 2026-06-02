"""Markdown link handler module.

Protects and restores Markdown links containing newlines during text splitting.

## Problem Scenario

During text splitting, Markdown links with internal newlines may be broken by separators:

```markdown
Original text:
See this [very long
link text](https://example.com)

If split by \\n:
chunk1: "See this [very long"
chunk2: "link text](https://example.com)"
```

The link is broken!

## Solution

This module uses a protect-split-restore approach:

### Step 1: Protect (protect_markdown_links)
Replace newline-containing links with equal-length placeholders:
```
Original: [long\\nlink](url)  # assume 30 tokens
Replaced: __MDLINK_0__xxxxxxxxx  # same 30 tokens
```

### Step 2: Split
Split the protected text normally; placeholders will not be broken.

### Step 3: Restore (restore_markdown_links)
Replace placeholders with original links:
```
__MDLINK_0__xxxxxxxxx -> [long\\nlink](url)
```

## Usage Example

```python
handler = MarkdownLinkHandler()

# Original text
text = '''
See this [very long
link text](https://example.com) for details.
'''

# Step 1: Protect links
protected_text, link_map = handler.protect_markdown_links(text)
# protected_text: "See this __MDLINK_0__xxxxx for details."
# link_map: {0: "[very long\\nlink text](https://example.com)"}

# Step 2: Split protected_text (done by splitter)
chunks = split_text(protected_text)

# Step 3: Restore links
restored_chunks = [handler.restore_markdown_links(chunk, link_map) for chunk in chunks]
```

## Technical Details

- Only protects links containing newlines (newline-free links need no protection)
- Uses negative lookbehind to exclude Markdown image syntax (`![alt](url)`), only handles links (`[text](url)`)
- Placeholder length matches original link token count for accurate split positions
- Uses padding char 'x' to match token counts

[INPUT]
- (none)

[OUTPUT]
- MarkdownLinkHandler: Markdown link handler.

[POS]
Markdown link handler module.
"""

import logging
import re
from collections.abc import Callable

from myrm_agent_harness.utils.text_utils import get_token_count

logger = logging.getLogger(__name__)


class MarkdownLinkHandler:
    """Markdown link handler."""

    # Padding character and token ratio constants
    FILL_CHAR = "x"
    FILL_TOKEN_RATIO = 0.27

    def __init__(self):
        # Pre-compiled regex patterns
        # Negative lookbehind (?<!\!) excludes image syntax ![alt](url), only matches links [text](url)
        self._link_pattern = re.compile(r"(?<!\!)\[(.+?)\]\(([^)]+)\)", re.MULTILINE | re.DOTALL)
        self._placeholder_pattern = re.compile(r"__MDLINK_(\d+)__x*")

    def protect_markdown_links(self, text: str) -> tuple[str, dict[int, str]]:
        """Protect Markdown links containing newlines.

        Replaces newline-containing links with placeholders of equal token count.

        Args:
            text: Text to process

        Returns:
            (protected_text, link_map)
        """
        link_map = {}

        def replace_link(match):
            link_text = match.group(1)
            link_url = match.group(2)
            original_link = f"[{link_text}]({link_url})"

            # Only protect links containing newlines
            if "\n" not in original_link:
                return original_link

            original_tokens = get_token_count(original_link)

            link_id = len(link_map)
            base_placeholder = f"__MDLINK_{link_id}__"
            base_tokens = get_token_count(base_placeholder)

            tokens_needed = max(0, original_tokens - base_tokens)

            if tokens_needed == 0:
                link_map[link_id] = original_link
                return base_placeholder

            # Estimate required padding character count
            estimated_chars = int(tokens_needed / self.FILL_TOKEN_RATIO * 1.2)
            padding = self.FILL_CHAR * estimated_chars
            placeholder = f"{base_placeholder}{padding}"

            placeholder_tokens = get_token_count(placeholder)

            # If token count insufficient, add more padding
            if placeholder_tokens < original_tokens:
                gap = original_tokens - placeholder_tokens
                additional_chars = int(gap / self.FILL_TOKEN_RATIO * 1.05) + 10
                padding += self.FILL_CHAR * additional_chars
                placeholder = f"{base_placeholder}{padding}"

            link_map[link_id] = original_link
            return placeholder

        protected_text = self._link_pattern.sub(replace_link, text)
        return protected_text, link_map

    def restore_markdown_links(self, text: str, link_map: dict[int, str]) -> str:
        """Restore protected Markdown links.

        Args:
            text: Text containing placeholders
            link_map: Link mapping table

        Returns:
            Text with links restored
        """

        def restore_link(match: re.Match) -> str:
            link_id = int(match.group(1))
            if link_id in link_map:
                return link_map[link_id]
            return match.group(0)

        return self._placeholder_pattern.sub(restore_link, text)

    def restore_and_check_links(
        self,
        chunks: list[str],
        link_map: dict[int, str],
        max_with_special: int,
        length_function: Callable[[str], int],
        resplit_callback: Callable[[str], list[str]],
    ) -> list[str]:
        """Restore Markdown links and check for oversized chunks.

        Args:
            chunks: Chunk list
            link_map: Link mapping table
            max_with_special: Maximum allowed size for special blocks
            length_function: Token counting function
            resplit_callback: Re-split callback function

        Returns:
            Chunk list with links restored
        """
        restored_chunks = [self.restore_markdown_links(chunk, link_map) for chunk in chunks]

        oversized_indices = []
        for i, chunk in enumerate(restored_chunks):
            tokens = length_function(chunk)
            if tokens > max_with_special:
                oversized_indices.append((i, tokens))

        if oversized_indices:
            new_chunks = list(restored_chunks)
            offset = 0

            for chunk_idx, tokens in oversized_indices:
                adjusted_idx = chunk_idx + offset
                logger.warning(f"  chunk {chunk_idx + 1}: {tokens} tokens > {max_with_special} tokens, re-splitting")

                oversized_content = new_chunks[adjusted_idx]

                # Use callback to re-split
                resplit_chunks = resplit_callback(oversized_content)

                new_chunks = new_chunks[:adjusted_idx] + resplit_chunks + new_chunks[adjusted_idx + 1 :]

                offset += len(resplit_chunks) - 1
                logger.warning(f"    Re-split into {len(resplit_chunks)} chunks (links protected)")

            restored_chunks = new_chunks

        return restored_chunks
