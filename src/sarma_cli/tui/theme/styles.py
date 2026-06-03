"""Shared Textual CSS for Sarma TUI screens."""

BASE_CSS = """
Screen {
    background: #0d1117;
    color: #e6edf3;
}

Header {
    background: #161b22;
    color: #e6edf3;
    border-bottom: solid #30363d;
}

Footer {
    background: #161b22;
    color: #7d8590;
    border-top: solid #30363d;
}

#shell {
    height: 1fr;
    background: #0d1117;
}

#items {
    width: 34;
    border: solid #30363d;
    background: #161b22;
    padding: 1 2;
}

#items:focus {
    border: tall #58a6ff;
}

ListView {
    background: #161b22;
    color: #e6edf3;
    scrollbar-background: #0d1117;
    scrollbar-color: #30363d;
    scrollbar-color-hover: #58a6ff;
}

ListView:focus {
    border: tall #58a6ff;
}

ListItem {
    padding: 0 1;
    margin-bottom: 1;
    background: #161b22;
    color: #e6edf3;
}

ListItem:hover {
    background: #21262d;
    color: #e6edf3;
}

ListItem.--highlight {
    background: #1f6feb 20%;
    color: #e6edf3;
}

ListView:focus ListItem.--highlight {
    background: #58a6ff 25%;
    color: #ffffff;
}

#buttons {
    height: auto;
    margin-top: 1;
}

#button-spacer {
    width: 1fr;
}

#status {
    height: 1;
    background: #161b22;
    color: #e6edf3;
    padding: 0 2;
    border-top: solid #30363d;
}

.hint {
    color: #7d8590;
}

.field-label {
    color: #7d8590;
    margin-top: 1;
    margin-bottom: 1;
}

Input {
    margin-bottom: 1;
    padding: 0 1;
    background: #0d1117;
    color: #e6edf3;
    border: tall #30363d;
    transition: border 150ms, background 150ms;
}

Input:focus {
    border: tall #58a6ff;
    background: #161b22;
}

Input:hover {
    border: tall #7d8590;
}

Button {
    margin-right: 1;
    min-width: 10;
    background: #21262d;
    color: #e6edf3;
    border: tall #30363d;
    transition: background 150ms, color 150ms, border 150ms;
}

Button:hover {
    background: #30363d;
    border: tall #58a6ff;
    color: #ffffff;
}

Button:focus {
    border: tall #58a6ff;
}

Button.success {
    background: #238636;
    color: #ffffff;
    border: tall #3fb950;
}

Button.success:hover {
    background: #2ea043;
    border: tall #3fb950;
}

Button.error {
    background: #da3633;
    color: #ffffff;
    border: tall #f85149;
}

Button.error:hover {
    background: #f85149;
    border: tall #ff7b72;
}

Button.warning {
    background: #9e6a03;
    color: #ffffff;
    border: tall #d29922;
}

Button.warning:hover {
    background: #bb8009;
    border: tall #d29922;
}

Button.primary {
    background: #1f6feb;
    color: #ffffff;
    border: tall #58a6ff;
}

Button.primary:hover {
    background: #388bfd;
    border: tall #79c0ff;
}
"""


def _pane_css(*, sections_width: int, detail_selector: str) -> str:
    return f"""
#sections {{
    width: {sections_width};
    border: solid #30363d;
    background: #161b22;
    padding: 1 2;
}}

#sections:focus {{
    border: tall #58a6ff;
}}

{detail_selector} {{
    width: 1fr;
    border: solid #30363d;
    background: #0d1117;
    padding: 1 2;
}}

{detail_selector}:focus-within {{
    border: tall #58a6ff;
}}
"""


CONFIG_APP_CSS = BASE_CSS + _pane_css(
    sections_width=18,
    detail_selector="#form",
) + """
#form-fields {
    height: 1fr;
    overflow-y: auto;
    padding-right: 1;
    scrollbar-background: #0d1117;
    scrollbar-color: #30363d;
    scrollbar-color-hover: #58a6ff;
}
"""


PLUGIN_APP_CSS = BASE_CSS + _pane_css(
    sections_width=16,
    detail_selector="#detail",
) + """
#detail-fields {
    height: 1fr;
    overflow-y: auto;
    padding-right: 1;
    scrollbar-background: #0d1117;
    scrollbar-color: #30363d;
    scrollbar-color-hover: #58a6ff;
}

#skill-results {
    height: auto;
    margin-top: 1;
    padding-top: 1;
    border-top: solid #30363d;
}

.skill-result {
    height: auto;
    margin-top: 1;
    padding: 1;
    background: #161b22;
    border: solid #30363d;
}

.skill-result:hover {
    background: #21262d;
    border: solid #a371f7;
}

.skill-result-info {
    width: 1fr;
    padding-right: 1;
    color: #e6edf3;
}
"""
