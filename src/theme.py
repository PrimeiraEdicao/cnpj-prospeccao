"""Paletas da interface, selecionadas por sessão sem alterar o servidor."""

PALETTES = {
    "Claro": {"scheme": "light", "bg": "#FFFFFF", "surface": "#F6F8FC",
              "text": "#0F2D5B", "muted": "#52647E", "line": "#E0E7F1",
              "accent": "#315FC3", "hover": "#EEF3FB", "action": "#0F2D5B"},
    "Escuro": {"scheme": "dark", "bg": "#0B1220", "surface": "#142136",
               "text": "#E8EEF8", "muted": "#B5C3D8", "line": "#546887",
               "accent": "#8AB4FF", "hover": "#1D2E48", "action": "#315FC3"},
}


def theme_css(mode: str) -> str:
    palette = PALETTES[mode]
    variables = ";".join(f"--al-{key}:{value}" for key, value in palette.items())
    return f":root{{{variables};color-scheme:{palette['scheme']};}}" + r"""
[data-testid="stApp"], [data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stHeader"], [data-testid="stToolbar"] {
    background-color:var(--al-bg)!important;color:var(--al-text)!important;
}
[data-testid="stSidebar"] {background-color:var(--al-surface)!important;border-right:1px solid var(--al-line);}
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"],
[data-testid="stMetricValue"], [data-testid="stMetricLabel"],
[data-testid="stIconMaterial"], [data-testid="stSidebarCollapseButton"] button {
    color:var(--al-text)!important;
}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color:var(--al-muted)!important;}
[data-testid="stHeader"] button, [data-testid="stHeader"] svg,
[data-testid="stToolbar"] button, [data-testid="stToolbar"] svg,
[data-testid="stTooltipIcon"] {color:var(--al-text)!important;}
[data-testid="stMarkdownContainer"] a:not(.contact-action) {color:var(--al-accent)!important;}
input, textarea {background-color:var(--al-surface)!important;color:var(--al-text)!important;caret-color:var(--al-text);}
input::placeholder, textarea::placeholder {color:var(--al-muted)!important;opacity:1;}
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"],
[data-baseweb="select"]>div {background-color:var(--al-surface)!important;border-color:var(--al-line)!important;color:var(--al-text)!important;}
[data-baseweb="select"] span, [data-baseweb="select"] svg, [data-baseweb="select"]>div * {color:var(--al-text)!important;}
[data-baseweb="tag"] {background-color:var(--al-hover)!important;color:var(--al-text)!important;}
[data-baseweb="popover"]>div, [data-baseweb="tooltip"], [role="listbox"], [role="option"] {
    background-color:var(--al-surface)!important;color:var(--al-text)!important;
}
[role="option"]:hover, [role="option"][aria-selected="true"] {background-color:var(--al-hover)!important;}
[role="option"] *, [data-baseweb="tooltip"] * {color:var(--al-text)!important;}
[data-testid="stButton"] button, [data-testid="stLinkButton"] a,
[data-testid="stNumberInput"] button, [data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] {
    background-color:var(--al-surface)!important;color:var(--al-text)!important;border-color:var(--al-line)!important;
}
[data-testid="stButton"] button:hover {border-color:var(--al-accent)!important;}
[data-testid="stButton"] button:disabled {color:var(--al-muted)!important;opacity:.6;}
[data-testid="stExpander"] details, [data-testid="stExpander"] summary {
    background-color:var(--al-bg)!important;color:var(--al-text)!important;border-color:var(--al-line)!important;
}
[data-testid="stAlert"]>div {background-color:var(--al-surface)!important;color:var(--al-text)!important;border:1px solid var(--al-line);}
[data-testid="stCode"], [data-testid="stCode"] pre, [data-testid="stCode"] code {
    background-color:var(--al-surface)!important;color:var(--al-text)!important;
}
hr {border-color:var(--al-line)!important;}
.block-container{padding-top:2.1rem;max-width:1550px;padding-bottom:3rem}
h1,h2,h3{color:var(--al-text)!important;letter-spacing:-.035em}
h1{font-size:2.8rem!important;font-weight:500!important}
.brand-header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--al-line);padding:0 0 1rem;margin-bottom:1.7rem;gap:1rem}
.brand-header img{width:175px;height:auto}.brand-header span{font-size:.72rem;color:var(--al-muted);letter-spacing:.15em;text-transform:uppercase}
.eyebrow{color:var(--al-accent);font-size:.72rem;letter-spacing:.15em;margin-bottom:.45rem;font-weight:700}
[data-testid="stMetric"]{padding:1.2rem;border:1px solid var(--al-line);background:var(--al-surface);border-radius:10px}
.prospect-table{width:100%;overflow-x:auto;border:1px solid var(--al-line);border-radius:10px;margin:1rem 0 1.3rem}
.prospect-table table{width:100%;border-collapse:collapse;font-size:.8rem;min-width:940px}
.prospect-table th{background:var(--al-surface);color:var(--al-muted);text-align:left;padding:.85rem 1rem;font-weight:600;white-space:nowrap}
.prospect-table td{background:var(--al-bg);padding:1rem;border-top:1px solid var(--al-line);vertical-align:middle;color:var(--al-text)}
.prospect-table tr:hover td{background:var(--al-hover)}.prospect-table small{display:block;color:var(--al-muted);font-size:.71rem;margin-top:.35rem}
.prospect-table .company{min-width:230px;max-width:330px}.prospect-table .activity{max-width:250px;min-width:150px}
.contact-action{display:inline-block;background:var(--al-action);color:white!important;padding:.55rem .7rem;border:1px solid var(--al-action);border-radius:5px;text-decoration:none!important;font-size:.74rem;white-space:nowrap;margin:2px 0}
.contact-action:hover{border-color:var(--al-accent)}.actions{min-width:106px}.muted{color:var(--al-muted);font-size:.75rem}
"""
