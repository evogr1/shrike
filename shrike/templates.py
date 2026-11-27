"""Card wording per opportunity type (design C5). Plain templates, no AI."""

from urllib.parse import urlsplit

FIX = {
    "striking_distance": (
        "People see this page for the query, but it ranks just below the clicks.",
        "1. Put the query (in natural words) in the title and the H1.\n"
        "2. Answer it directly in the first paragraph.\n"
        "3. Add a section that covers it properly.\n"
        "4. Link to this page from 2-3 related pages using the query as link text."),
    "low_ctr": (
        "The page is shown often but clicked far less than expected for its position.",
        "1. Rewrite the title: the searcher's words first, then a concrete benefit.\n"
        "2. Rewrite the meta description to say what they get.\n"
        "3. Check the live result looks right (no truncation, correct page)."),
    "decaying": (
        "The page lost clicks compared with the 28 days before.",
        "1. Search its main queries and see what now ranks above it.\n"
        "2. Check the page still loads, is indexable and wasn't changed or redirected.\n"
        "3. Update outdated content, then request indexing in Search Console."),
}


def _path(url):
    p = urlsplit(url).path or "/"
    return p if len(p) <= 60 else p[:57] + "..."


def title(o):
    m = o["metrics"]
    if o["type"] == "striking_distance":
        return f'[{o["site"]}] Striking distance: "{o["query"]}" (pos {m["position"]:.1f})'
    if o["type"] == "low_ctr":
        return f'[{o["site"]}] Low CTR: {_path(o["page"])} ({m["ctr"]:.1%} vs {m["expected_ctr"]:.1%})'
    return f'[{o["site"]}] Decaying: {_path(o["page"])} (-{m["drop"]:.0%} clicks)'


def render_card(o):
    m = o["metrics"]
    why, fix = FIX[o["type"]]
    lines = [f"Page: {o['page']}"]
    if o["query"]:
        lines.append(f"Query: {o['query']}")
    if o["type"] == "decaying":
        lines.append(f"Clicks, last 28 days: {m['clicks']} (before: {m['clicks_prev']})")
    else:
        lines.append(f"Last 28 days: {m['impressions']} impressions, {m['clicks']} clicks, "
                     f"CTR {m['ctr']:.1%}, position {m['position']:.1f}")
        lines.append(f"Compared with {m['expected_ctr']:.1%} CTR from {m['benchmark']}.")
    lines += [f"Data up to {m['window_end']}.", "", f"Why: {why}", "", "Fix:", fix, "",
              "When shipped, move this card to Done. If it went live on another day, add a line: "
              "shipped: YYYY-MM-DD"]
    return title(o), "\n".join(lines)
