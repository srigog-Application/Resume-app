import itertools
import re
import threading
from xml.etree.ElementTree import Element

import markdown
import markdown.core


def to_typst_string(elem: Element) -> str:
    """Recursively convert XML Element tree to Typst markup string.

    Why:
        Python Markdown library outputs XML Element tree. Typst requires its
        own markup syntax for bold, italic, links, etc. Recursive traversal
        converts entire element tree including nested formatting.

    Args:
        elem: XML Element from Markdown parser.

    Returns:
        Typst-formatted string.
    """
    result = []

    # Handle the element's text content
    if elem.text:
        result.append(escape_typst_characters(elem.text))

    # Process child elements
    for child in elem:
        match child.tag:
            case "strong":
                # Bold: **text** -> #strong[text]
                inner = to_typst_string(child)
                child_content = f"#strong[{inner}]"

            case "em":
                # Italic: *text* -> #emph[text]
                inner = to_typst_string(child)
                child_content = f"#emph[{inner}]"

            case "code":
                # Inline code: `text` -> #raw("text"). Emitted as a string literal so
                # backticks inside the code span cannot break out into markup.
                child_content = f'#raw("{escape_typst_string_literal(child.text or "")}")'

            case "a":
                # Link: [text](url) -> #link("url")[text]
                href = child.get("href") if child.get("href") else "https://example.com"
                inner = to_typst_string(child)
                child_content = f'#link("{escape_typst_string_literal(href)}")[{inner}]'

            case "div":
                child_content = (
                    "#summary["
                    + to_typst_string(child).strip("\n").replace("\n", " \\ ")
                    + "]"
                )

            case _:
                if getattr(child, "attrib", {}).get("class") == "admonition-title":
                    continue
                child_content = to_typst_string(child)

        result.append(child_content)

        # Handle tail text (text after the closing tag of child)
        if child.tail:
            result.append(escape_typst_characters(child.tail))

    return "".join(result)


# Web-app hardening: upstream passes raw Typst commands (`#foo(...)`) and math
# (`$$...$$`) found in user text straight through to the compiler. That is fine for
# a local CLI but lets one tenant run arbitrary Typst code on a shared server, so it
# is disabled by default. Set to True only for trusted, single-user input.
ALLOW_RAW_TYPST = False


def escape_typst_string_literal(string: str) -> str:
    """Escape text for use inside a double-quoted Typst string literal."""
    return (
        str(string)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )


typst_command_pattern = re.compile(r"#([A-Za-z][^\s()\[]*)(\([^)]*\))?(\[[^\]]*\])?")
math_pattern = re.compile(r"(\$\$.*?\$\$)")


def escape_typst_characters(string: str) -> str:
    """Escape Typst special characters while preserving Typst commands and math.

    Why:
        User content may contain Typst special characters like `#`, `$`, `[` that
        would break compilation. Escaping prevents interpretation as commands.
        Existing Typst commands and math must remain unescaped.

    Args:
        string: Text to escape.

    Returns:
        Escaped string safe for Typst.
    """
    if string == "\n":
        return string

    # Find all the Typst commands, and keep them separate so that nothing is escaped
    # inside the commands.
    typst_command_mapping = {}
    passthrough_matches = (
        itertools.chain(
            math_pattern.finditer(string),
            typst_command_pattern.finditer(string),
        )
        if ALLOW_RAW_TYPST
        else ()
    )
    for i, match in enumerate(passthrough_matches):
        dummy_name = f"CVENGINETYPSTCOMMANDORMATH{i}"
        typst_command_mapping[dummy_name] = match.group(0)
        string = string.replace(typst_command_mapping[dummy_name], dummy_name)
        typst_command_mapping[dummy_name] = typst_command_mapping[dummy_name].replace(
            "$$", "$"
        )

    # Add the tail after the last match
    escape_dictionary = {
        "[": "\\[",
        "]": "\\]",
        "\\": "\\\\",
        '"': '\\"',
        "#": "\\#",
        "$": "\\$",
        "@": "\\@",
        "%": "\\%",
        "~": "\\~",
        "_": "\\_",
        "/": "\\/",
        ">": "\\>",
        "<": "\\<",
    }

    string = string.translate(str.maketrans(escape_dictionary))

    # string.translate() only supports single-character replacements, so we need to
    # handle the longer replacements separately.
    longer_escape_dictionary = {
        "* ": "#sym.ast.basic ",
        "*": "#sym.ast.basic#h(0pt, weak: true) ",
    }
    for key, value in longer_escape_dictionary.items():
        string = string.replace(key, value)

    # Replace the dummy names with the full Typst commands
    for dummy_name, full_command in typst_command_mapping.items():
        string = string.replace(dummy_name, full_command)

    return string


def create_markdown_instance() -> markdown.core.Markdown:
    """Build a Markdown parser configured to emit Typst."""
    instance = markdown.core.Markdown(extensions=["admonition"])
    instance.output_formats["typst"] = to_typst_string  # pyright: ignore[reportArgumentType]
    instance.set_output_format("typst")  # pyright: ignore[reportArgumentType]
    instance.parser.blockprocessors.deregister("hashheader")
    instance.parser.blockprocessors.deregister("setextheader")
    instance.parser.blockprocessors.deregister("olist")
    instance.parser.blockprocessors.deregister("ulist")
    instance.parser.blockprocessors.deregister("quote")
    # Web-app hardening: raw HTML is stashed by python-markdown and pasted back
    # verbatim after serialization, which would bypass Typst escaping.
    instance.preprocessors.deregister("html_block")
    instance.inlinePatterns.deregister("html")
    instance.stripTopLevelTags = False
    return instance


# Markdown instances keep per-conversion state, so each thread gets its own
# (the web server renders resumes concurrently from a thread pool).
_thread_local = threading.local()


def get_markdown_instance() -> markdown.core.Markdown:
    instance = getattr(_thread_local, "md", None)
    if instance is None:
        instance = _thread_local.md = create_markdown_instance()
    return instance


def markdown_to_typst(markdown_string: str) -> str:
    """Convert Markdown string to Typst markup.

    Why:
        Users write content in Markdown for readability. Typst compilation
        requires Typst markup. Lines are processed independently to prevent
        emphasis markers on adjacent lines from interacting in the Markdown
        parser (single-newline-separated lines form one paragraph in Markdown,
        causing cross-line marker interference). Admonition blocks are kept
        together since they span multiple lines by design.

    Args:
        markdown_string: Markdown content.

    Returns:
        Typst-formatted string.
    """
    lines = markdown_string.split("\n")
    result_parts: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("!!!"):
            # Admonition block: collect the !!! line + all following indented lines
            block = [lines[i]]
            i += 1
            while i < len(lines) and lines[i].startswith("    "):
                block.append(lines[i])
                i += 1
            md = get_markdown_instance()
            md.reset()
            result_parts.append(md.convert("\n".join(block)))
        else:
            md = get_markdown_instance()
            md.reset()
            result_parts.append(md.convert(lines[i]))
            i += 1
    return "\n".join(result_parts)


def markdown_to_html(markdown_string: str) -> str:
    """Convert Markdown string to HTML using python-markdown library.

    Args:
        markdown_string: Markdown content.

    Returns:
        HTML-formatted string.
    """
    return markdown.markdown(markdown_string)
