"""Generate the design-system styleframe from the live UI code (pure logic).

`render_styleframe()` renders every operator page through the *same* functions
the app serves — ``render_dashboard_html``, ``render_drafts_html``,
``render_draft_html``, ``render_queue_html``, ``render_publish_html``,
``render_status_html``, ``render_feed_html`` — and wraps them in one tabbed
document that also documents the foundations (tokens, components). Because it
embeds ``ui._CSS`` and calls the real renderers, the styleframe can never
describe a look the app doesn't have.

It is a generated artifact: never hand-edit ``docs/design/styleframe.html``.
``tests/test_design_system.py`` asserts the committed file matches this function
byte for byte, so regenerate it whenever the UI changes:

    .venv/bin/python scripts/build_styleframe.py

The output is deterministic (fixed sample data, fixed timestamps, and a
normalized timezone token) so the byte-for-byte check is stable on any machine.
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import pathlib
import re

from .dashboard_html import (
    render_dashboard_html,
    render_publish_html,
    render_queue_html,
    render_status_html,
)
from .destinations.facebook.feed import FeedItem
from .destinations.facebook.feed_html import render_feed_html, render_feed_section
from .draft_html import render_draft_html, render_drafts_html
from .drafts import Draft
from .ui import _CSS, badge, nav_html, notice_html

# Where the generated styleframe lives, relative to this module (src/social_bot).
STYLEFRAME_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "design" / "styleframe.html"
)

# A fixed wall-clock for every rendered stamp. Naive on purpose: astimezone()
# then keeps the same wall time on any machine, and the trailing zone token is
# normalized below so the generated file is byte-stable.
_AT = dt.datetime(2026, 9, 10, 12, 0)
# The zone token is the last thing on a full minute-precision stamp; stop at "<"
# so a trailing tag (`+07</div>`) is never swallowed.
_STAMP_TZ_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) [^\s<]+")

# A self-contained 16:9 placeholder so the styleframe needs no network and no
# external asset. Base64 of a gradient SVG with a couple of shapes.
_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#dcece9"/><stop offset="1" stop-color="#0e6b64"/>'
    "</linearGradient></defs>"
    '<rect width="640" height="360" fill="url(#g)"/>'
    '<circle cx="150" cy="130" r="72" fill="#ffffff" opacity="0.30"/>'
    '<rect x="270" y="196" width="250" height="16" rx="8" fill="#ffffff" opacity="0.40"/>'
    '<rect x="270" y="228" width="180" height="16" rx="8" fill="#ffffff" opacity="0.28"/>'
    "</svg>"
)
_THUMB = "data:image/svg+xml;base64," + base64.b64encode(_SVG.encode("utf-8")).decode("ascii")

_DNA = (
    "# Atento DNA — brand voice & content playbook\n"
    "The single source of truth for how Atento sounds.\n\n"
    "- Masthead on line 1, one register per post, technical terms in English.\n"
    "- Format D (the crowd, then the turn): open on a shared belief, then complicate it.\n"
    "- No engagement bait, no hype numbers, name the trade-off.\n"
)

_VOICE_HINTS = {
    "technical": "a calm, two-sided engineer (the Dũng register). System Design / architecture.",
    "essay": "a personal, self-deprecating first person (the Đạt register). Essays / mindset.",
    "announcement": "Atento's warm, low-drama page voice. Khai giảng, seminar, community.",
    "funny": "a deadpan, mock-serious satirist. A platform in-joke told with a straight face.",
}

_VOICE = (
    '# technical — the "DW" register\n'
    "Voice: a calm, two-sided engineer (the Dũng register).\n\n"
    "Open on a concrete moment; keep the thesis for the payoff.\n"
    "Give every claim its cost — the trade-off is the credibility.\n"
)

# --- sample pipeline state (shaped exactly like draft_pipeline.status) --------

_STATS = {
    "sources": [
        {"name": "atento-blog", "type": "index", "url": "https://atento.vn/blog", "lang": "vi"},
        {
            "name": "bytebytego",
            "type": "rss",
            "url": "https://blog.bytebytego.com/feed",
            "lang": "en",
        },
        {
            "name": "martinfowler",
            "type": "rss",
            "url": "https://martinfowler.com/feed.atom",
            "lang": "en",
        },
        {
            "name": "seangoedecke",
            "type": "rss",
            "url": "https://www.seangoedecke.com/rss.xml",
            "lang": "en",
        },
        {
            "name": "netflix-tech-blog",
            "type": "rss",
            "url": "https://netflixtechblog.com/feed",
            "lang": "en",
        },
    ],
    "drafts": {
        "total": 62,
        "open": 61,
        "by_state": {"extracted": 0, "ai_draft": 59, "approved": 2, "posted": 1, "rejected": 0},
    },
    "seen": 62,
    "published": {"total": 1, "private": 0, "recent": []},
    "publish": {
        "enabled": True,
        "private": False,
        "destinations": ["facebook", "linkedin"],
        "destination_state": [
            {"name": "facebook", "label": "Facebook", "enabled": True, "configured": True},
            {"name": "linkedin", "label": "LinkedIn", "enabled": True, "configured": True},
        ],
        "post_at": ["19:30-21:00"],
        "post_per_slot": 1,
        "interval_days": 2,
        "interval_remaining": 0,
        "approved": 2,
        "next_draft": {
            "id": "a-guide-to-application-networking-basics",
            "title": "A Guide to Application Networking Basics",
            "source": "bytebytego",
            "has_image": False,
        },
        "dna_file_set": True,
        "voices_set": True,
        "voice_choices": ["technical", "essay", "announcement", "funny"],
        "default_voice": "technical",
    },
    "images": {"with_image": 3},
}

_REFRESH = {
    "busy": False,
    "ok": True,
    "error": None,
    "last_finished": "2026-09-10 07:00:00",
    "schedule": ["07:00", "19:00"],
    "next": "2026-09-10 19:00",
}
_SCAN = {
    "busy": False,
    "ok": True,
    "error": None,
    "last_added": 12,
    "last_finished": "2026-09-10 06:00:00",
    "schedule": ["06:00"],
    "next": "2026-09-11 06:00",
}
_POST = {
    "busy": False,
    "ok": None,
    "error": None,
    "last_posted": None,
    "last_finished": None,
    "schedule": ["19:30-21:00"],
    "next": "2026-09-10 19:51",
    "next_post": "2026-09-10 19:51",
}
_TOKEN = {
    "valid": True,
    "type": "PAGE",
    "expires_at": "2026-11-09T21:12:21+00:00",
    "never_expires": False,
    "expires_in_days": 59,
    "scopes": ["pages_read_engagement", "pages_manage_posts", "pages_show_list"],
    "checked_at": "2026-09-10 07:00:00",
}
_LINKEDIN = {
    "configured": True,
    "ok": True,
    "base_url": "http://host.docker.internal:8082",
    "checked_at": "2026-09-10 07:00:00",
    "error": "",
    "status": "ok",
    "connected": True,
    "oauth_summary": "oauth token: expires 2026-12-12 10:39 (59 day(s) left)",
    "kill_switch": False,
    "caps": [
        {
            "kind": "connect",
            "sent_today": 0,
            "day_remaining": 30,
            "week_remaining": 20,
            "remaining": 20,
        },
        {
            "kind": "follow",
            "sent_today": 0,
            "day_remaining": 10,
            "week_remaining": 50,
            "remaining": 10,
        },
    ],
    "schedule": {"connect": ["09:30"], "follow": ["10:00"]},
    "next_run": {"connect": "2026-09-10 09:30", "follow": "2026-09-10 10:00"},
}

_RECORDS = [
    {
        "id": "a-guide-to-application-networking-basics",
        "source": "bytebytego",
        "url": "https://blog.bytebytego.com/p/a-guide-to-application-networking",
        "destination": "facebook",
        "post_id": "1148652808337860_122135960000000001",
        "permalink": "https://www.facebook.com/1148652808337860_122135960000000001",
        "posted_at": "2026-09-09 19:51",
    },
    {
        "id": "do-you-even-need-a-presentation",
        "source": "martinfowler",
        "url": "",
        "destination": "facebook",
        "post_id": "122131563729359840",
        "permalink": "",
        "posted_at": "2026-09-07 20:04",
        "private": True,
    },
]

_ITEMS = [
    FeedItem(
        id="1148652808337860_122135960000000001",
        created=dt.datetime(2026, 9, 9, 12, 51, tzinfo=dt.UTC),
        message=(
            "[Học cùng Atento]\n\n"
            "Ai cũng nói: muốn làm tốt thì phải hiểu hết codebase của mình. Ở codebase nhỏ, "
            "điều đó đúng. Nhưng ở hệ thống hàng chục triệu dòng với team thay máu liên tục, "
            "hiểu hết là chuyện không tưởng — và cố hiểu hết không phải là mục tiêu đúng."
        ),
        status_type="mobile_status_update",
        permalink_url="https://www.facebook.com/1148652808337860_122135960000000001",
        from_name="Atento Education",
        image=_THUMB,
    ),
    FeedItem(
        id="1148652808337860_122135000000000002",
        created=dt.datetime(2026, 9, 4, 8, 1, tzinfo=dt.UTC),
        message=(
            "[Đọc báo cùng Atento]\n\n"
            "Giờ này chiều mai là seminar “Agentic AI for business: from idea to product” đã đi "
            "được đến đoạn demo xong sản phẩm rồi đấy mấy ní ạ. Ai lỡ quên thì nhớ set báo thức nha."
        ),
        status_type="mobile_status_update",
        permalink_url="https://www.facebook.com/1148652808337860_122135000000000002",
        from_name="Atento Education",
    ),
    FeedItem(
        id="1148652808337860_122135000000000003",
        created=dt.datetime(2026, 8, 28, 4, 47, tzinfo=dt.UTC),
        status_type="added_photos",
        permalink_url="https://www.facebook.com/1148652808337860_122135000000000003",
        from_name="Atento Education",
    ),
]

_QUEUE = [
    Draft(
        id="a-guide-to-application-networking-basics",
        source="bytebytego",
        title="A Guide to Application Networking Basics",
        excerpt="From DNS to load balancers: the path a request takes before it reaches your code.",
        published="Thu, 10 Sep 2026 00:00:00 GMT",
        created_at="2026-09-10T07:28:25+00:00",
        state="approved",
        destinations=["facebook", "linkedin"],
        queue_order=1,
    ),
    Draft(
        id="how-smart-model-routing-can-cut-llm",
        source="bytebytego",
        title="How Smart Model Routing Can Cut LLM Costs by 10X",
        excerpt="Ứng dụng nào gắn LLM cũng có một thói quen: chọn model mạnh nhất rồi tống mọi request vào đó.",
        image=_THUMB,
        published="Wed, 09 Sep 2026 15:30:26 GMT",
        created_at="2026-09-10T07:28:25+00:00",
        state="approved",
        destinations=["facebook", "linkedin"],
        queue_order=2,
    ),
    Draft(
        id="social-media-engagement-summer-2026",
        source="martinfowler",
        title="Social Media Engagement: summer 2026",
        excerpt="LinkedIn cho engagement cao nhất. X đứng thứ hai. Bluesky và Mastodon gần như im lặng.",
        image=_THUMB,
        published="Tue, 09 Sep 2026 16:21:00 GMT",
        created_at="2026-09-10T07:28:25+00:00",
        state="ai_draft",
    ),
    Draft(
        id="fragments-september-8",
        source="martinfowler",
        title="Fragments: September 8",
        excerpt="dealing with AI's counterfeit utility, exasperated readers of LLMs, missing Creating Passionate Users",
        published="Mon, 08 Sep 2026 15:22:00 GMT",
        created_at="2026-09-09T06:00:00+00:00",
        state="ai_draft",
    ),
    Draft(
        id="do-you-even-need-a-presentation",
        source="martinfowler",
        title="Do you even need a presentation?",
        excerpt="Most of the time, we shouldn't use a presentation.",
        published="Mon, 08 Sep 2026 13:42:00 GMT",
        created_at="2026-09-09T06:00:00+00:00",
        state="ai_draft",
    ),
    Draft(
        id="automatically-detecting-ai-text",
        source="seangoedecke",
        title="Automatically detecting AI text in my browser",
        excerpt="Automated AI text detection is currently an underserved niche.",
        published="Mon, 08 Sep 2026 00:00:00 GMT",
        created_at="2026-09-09T06:00:00+00:00",
        state="ai_draft",
    ),
    Draft(
        id="nen-tang-hoc-tap-nao-cho-nguoi-di-lam",
        source="atento-blog",
        title="Nền tảng học tập nào cho người đi làm bận rộn?",
        excerpt="Ba tiêu chí để chọn một khoá học không phí thời gian: mật độ, phản hồi, và ứng dụng được ngay.",
        published="2026-09-06T02:15:38Z",
        created_at="2026-09-08T06:00:00+00:00",
        state="ai_draft",
    ),
]

_DETAIL = Draft(
    id="how-smart-model-routing-can-cut-llm",
    source="bytebytego",
    url="https://blog.bytebytego.com/p/how-smart-model-routing-can-cut-llm",
    title="How Smart Model Routing Can Cut LLM Costs by 10X",
    excerpt=(
        "Cost reduction isn't a given. It also depends on the types of requests the application "
        "receives and how well the routing system performs."
    ),
    image=_THUMB,
    published="Wed, 09 Sep 2026 15:30:26 GMT",
    lang="en",
    destinations=["facebook", "linkedin"],
    state="ai_draft",
    caption=(
        "[Học cùng Atento]\n\n"
        "Ứng dụng nào gắn LLM cũng có một thói quen: chọn model mạnh nhất rồi tống mọi request "
        "vào đó.\n\n"
        "Một request kiểu “phân loại ticket này là billing hay technical” và một request kiểu "
        "“soát đống sổ sách tài chính lệch nhau” cần hai mức reasoning rất khác. Nhưng cả hai đều "
        "bay vào cùng một model đắt nhất — chẳng khác nào thuê một kiến trúc sư senior đi đổi tên "
        "file.\n\n"
        "Model routing đặt một router trước vài model: việc dễ đẩy sang model nhỏ, việc khó mới "
        "tới model mạnh. Trong ví dụ của bài, nếu 85% request chỉ cần model nhỏ, 10% cần model "
        "vừa và 5% cần model mạnh, chi phí trung bình có thể rơi xuống quanh mức 1/10.\n\n"
        "Nhưng tiết kiệm không phải chuyện đương nhiên. Nó phụ thuộc vào loại traffic, mức chênh "
        "giá giữa các model, và quan trọng nhất là router đoán đúng tới đâu.\n\n"
        "Routing tốt không phải chọn model mạnh nhất. Là chọn model rẻ nhất còn đủ sức làm đúng "
        "việc, và biết khi nào cần nâng cấp."
    ),
    hashtags=["#Atento", "#fromfoundationtoexcellence", "#systemdesign"],
    cta="Đọc bài gốc đầy đủ tại comment.",
    commentary=(
        "Register technical (giọng Dũng), format D (đám đông rồi lật), drama vừa. Có nêu trade-off "
        "under/over-routing để không hype con số 10x."
    ),
    lint=[
        {
            "code": "antithesis",
            "message": "Câu đối lập “không phải X mà là Y” xuất hiện nhiều lần — giữ lại một lần cho đắt.",
        },
        {
            "code": "repeated-closer",
            "message": "Câu chốt trùng với một caption gần đây: “Routing tốt không phải chọn model mạnh nhất.” Đổi câu kết.",
        },
    ],
    created_at="2026-09-10T07:28:25+00:00",
    updated_at="2026-09-10T10:00:00+00:00",
)

# The approved drafts of _QUEUE, in the order the poster drains them — what the
# Post queue tab renders (and reorders).
_SCHEDULED = [draft for draft in _QUEUE if draft.state == "approved"]


def render_pages() -> list[tuple[str, str]]:
    """Every operator page as a full document, rendered by the app's own code.

    Returned as an ordered list of (tab label, HTML document). This is the single
    source both `render_styleframe` and the design-system tests read from, so a
    page can never be missed.
    """
    return [
        (
            "Factory",
            render_dashboard_html(
                stats=_STATS,
                refresh=_REFRESH,
                scan=_SCAN,
                post=_POST,
                token=_TOKEN,
                feed_section=render_feed_section(_ITEMS),
                feed_label="Facebook feed",
                feed_count=len(_ITEMS),
                account_label="Atento Education",
                generated_at=_AT,
            ),
        ),
        (
            "Review queue",
            render_drafts_html(
                _QUEUE,
                total=62,
                matched=61,
                sources=[
                    ("atento-blog", 8),
                    ("bytebytego", 12),
                    ("martinfowler", 12),
                    ("seangoedecke", 29),
                ],
                statuses=[("extracted", 0), ("ai_draft", 59), ("approved", 2)],
                selected_source="",
                selected_status="",
                page={
                    "page": 1,
                    "per_page": 7,
                    "pages": 9,
                    "total": 61,
                    "has_prev": False,
                    "has_next": True,
                },
                generated_at=_AT,
            ),
        ),
        (
            "Draft",
            render_draft_html(
                _DETAIL,
                dna=_DNA,
                # The rewriter is on in the sample so the Draft tab shows the
                # whole Compose panel: the image tools *and* the caption rewrite,
                # both grouped above the terminal-only action bar.
                rewrite_enabled=True,
                # The sample's picture is a stand-in for a diagram, so the
                # "Restore source image" control the detail page shows for a post
                # whose own cover was replaced is part of the preview too.
                image_generated=True,
                voices=["technical", "essay", "announcement", "funny"],
                default_voice="technical",
                voice_hints=_VOICE_HINTS,
                voice_text=_VOICE,
                next_id="do-you-even-need-a-presentation",
                scheduling=True,
                next_post="2026-09-10 19:51",
                generated_at=_AT,
            ),
        ),
        (
            "Post queue",
            # What the poster will drain, in order, with the first row marked as
            # the one that goes out next.
            render_queue_html(_SCHEDULED, post=_POST, generated_at=_AT),
        ),
        ("Published", render_publish_html(_RECORDS, generated_at=_AT)),
        (
            "Status",
            render_status_html(
                _STATS,
                refresh=_REFRESH,
                scan=_SCAN,
                post=_POST,
                token=_TOKEN,
                linkedin=_LINKEDIN,
                generated_at=_AT,
            ),
        ),
        (
            "Feed",
            render_feed_html(
                _ITEMS,
                page_name="Atento Education",
                page_id="1148652808337860",
                generated_at=_AT,
            ),
        ),
    ]


def _extract_body(document: str) -> str:
    """The page's own content, without the shared document shell or top nav.

    The styleframe shows the nav once and the page bodies inside its own tabs,
    so the per-page copy is dropped. Page scripts are dropped too: the detail
    page's client-side enhancement is meaningless out of the app (and its form
    ids would collide across tabs).
    """
    inner = document.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    inner = inner.split("</nav>", 1)[-1]
    inner = re.sub(r"<script>.*?</script>", "", inner, flags=re.S)
    return inner.strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _normalize_tz(markup: str) -> str:
    """Pin the timezone token in rendered stamps so output is machine-stable."""
    return _STAMP_TZ_RE.sub(r"\1 +07", markup)


# --- foundations tab ----------------------------------------------------------

_COLOR_TOKENS = (
    ("--bg", "App background"),
    ("--surface", "Panel / card surface"),
    ("--surface-2", "Inset surface, hover"),
    ("--border", "Hairline divider"),
    ("--border-strong", "Control edge, emphasis"),
    ("--fg", "Primary ink"),
    ("--ink-2", "Secondary ink"),
    ("--muted", "Muted ink / captions"),
    ("--accent", "Signal: primary action + focus"),
    ("--accent-2", "Signal hover"),
    ("--accent-soft", "Signal tint surface"),
    ("--accent-fg", "Text on the signal"),
    ("--ok", "Success state"),
    ("--warn", "Warning state"),
    ("--danger", "Danger state"),
)

_BADGE_LABELS = (
    "extracted",
    "ai_draft",
    "approved",
    "posted",
    "rejected",
    "valid",
    "invalid",
    "unknown",
    "running",
    "done",
    "no change",
    "skipped",
    "failed",
    "public",
    "private",
)


def _fpanel(label: str, body: str) -> str:
    return (
        '<section class="panel">'
        f'<div class="panel-head"><span class="label">{html.escape(label)}</span></div>'
        f"{body}</section>"
    )


def _foundations() -> str:
    """The tokens and components the design system is built from."""
    swatches = "".join(
        '<div class="sf-swatch">'
        f'<span class="sf-chip" style="background: var({token})"></span>'
        '<span class="sf-swatch-text">'
        f'<span class="sf-token">{html.escape(token)}</span>'
        f'<span class="sf-desc">{html.escape(label)}</span>'
        "</span></div>"
        for token, label in _COLOR_TOKENS
    )
    badges = "".join(badge(label) for label in _BADGE_LABELS)
    notices = "".join(
        notice_html(text, kind=kind)
        for kind, text in (
            ("info", "Informational — a neutral update."),
            ("success", "Success — the action completed."),
            ("warning", "Warning — proceed with care."),
            ("error", "Error — the action failed."),
        )
    ) + notice_html(private=True)
    buttons = (
        '<div class="sf-row">'
        '<button type="button" class="btn btn-primary">Primary action</button>'
        '<button type="button" class="btn">Secondary</button>'
        '<button type="button" class="btn btn-quiet">Quiet</button>'
        '<button type="button" class="btn btn-danger">Danger</button>'
        '<button type="button" class="btn btn-sm">Small</button>'
        '<button type="button" class="btn" disabled>Disabled</button>'
        "</div>"
    )
    pills = (
        '<div class="sf-row">'
        '<span class="pill"><span class="dot dot-ok"></span>ok</span>'
        '<span class="pill"><span class="dot dot-warn"></span>warning</span>'
        '<span class="pill"><span class="dot dot-danger"></span>failed</span>'
        '<span class="pill">3 items</span>'
        "</div>"
    )
    fields = (
        '<div class="field"><label for="sf-caption">Caption · Vietnamese</label>'
        '<textarea id="sf-caption" lang="vi">Một caption mẫu để xem kiểu chữ và khoảng cách '
        "trong ô nhập liệu.</textarea>"
        '<div class="field-hint">Helper text under a field, muted and small.</div></div>'
        '<div class="field"><label for="sf-tags">Hashtags</label>'
        '<input type="text" id="sf-tags" value="#Atento #systemdesign"></div>'
        '<div class="countbar"><span>1,270</span> characters posted (caption + hashtags)</div>'
    )
    controls = (
        '<div class="filters">'
        '<div class="filter-row"><span class="filter-label">Status</span><span class="seg">'
        '<a class="seg-item" href="#sf-review">All <span class="count">61</span></a>'
        '<a class="seg-item" href="#sf-review" aria-current="true">AI draft '
        '<span class="count">60</span></a>'
        '<a class="seg-item" href="#sf-review">Approved <span class="count">1</span></a>'
        "</span></div>"
        '<div class="filter-row"><span class="filter-label">Source</span>'
        '<a class="chip chip-active" href="#sf-review">All <span class="count">61</span></a>'
        '<a class="chip" href="#sf-review">bytebytego <span class="count">12</span></a>'
        '<a class="chip" href="#sf-review">seangoedecke <span class="count">29</span></a>'
        "</div></div>"
    )
    pipeline = (
        '<div class="pipeline" role="group" aria-label="Pipeline stages">'
        '<div class="stage"><div class="stage-name"><span class="dot dot-ok"></span>Sources</div>'
        '<div class="stage-num">5</div><div class="stage-sub">feeds watched</div></div>'
        '<div class="stage is-focus"><div class="stage-name"><span class="dot dot-warn"></span>'
        'Queue</div><div class="stage-num">61</div>'
        '<div class="stage-sub">waiting for review</div></div>'
        '<div class="stage"><div class="stage-name"><span class="dot dot-ok"></span>Approved</div>'
        '<div class="stage-num">1</div><div class="stage-sub">ready</div></div>'
        '<div class="stage"><div class="stage-name"><span class="dot dot-ok"></span>Published</div>'
        '<div class="stage-num">1</div><div class="stage-sub">all time</div></div>'
        "</div>"
    )
    stepper = (
        '<div class="stepper">'
        '<div class="step is-done"><span class="step-dot" aria-hidden="true">✓</span>'
        '<span class="step-name">Extracted<span class="small">queued from bytebytego</span></span>'
        "</div>"
        '<div class="step is-now"><span class="step-dot" aria-hidden="true">●</span>'
        '<span class="step-name">AI draft<span class="small">rewritten · waiting on you</span></span>'
        "</div>"
        '<div class="step"><span class="step-dot" aria-hidden="true">·</span>'
        '<span class="step-name">Approved<span class="small">not yet</span></span></div>'
        '<div class="step"><span class="step-dot" aria-hidden="true">·</span>'
        '<span class="step-name">Posted<span class="small">not yet</span></span></div>'
        "</div>"
    )
    table = (
        "<table><thead><tr><th>When</th><th>Source</th><th>Destination</th></tr></thead>"
        "<tbody>"
        "<tr><td>2026-09-09 19:51</td><td>bytebytego</td><td>facebook</td></tr>"
        "<tr><td>2026-09-07 20:04</td><td>martinfowler</td><td>facebook</td></tr>"
        "</tbody></table>"
    )
    kv = (
        '<dl class="kv">'
        '<div class="kv-row"><dt>Seen items</dt><dd>62</dd></div>'
        '<div class="kv-row"><dt>Open drafts</dt><dd>61</dd></div>'
        '<div class="kv-row"><dt>Published</dt><dd>1</dd></div>'
        "</dl>"
    )
    sched = (
        '<div class="sched">'
        '<div class="sched-row"><span class="dot dot-ok" aria-hidden="true"></span>'
        '<span class="sched-name">Feed refresh<span class="small">last run ok</span></span>'
        '<span class="sched-when">next 19:00</span></div>'
        '<div class="sched-row"><span class="dot dot-warn" aria-hidden="true"></span>'
        '<span class="sched-name">Post schedule<span class="small">not run yet</span></span>'
        '<span class="sched-when">next 19:51</span></div>'
        "</div>"
    )

    left = (
        '<div class="stack">'
        + _fpanel(
            "Colour tokens",
            f'<div class="panel-body"><div class="sf-swatches">{swatches}</div></div>',
        )
        + _fpanel("Badges", f'<div class="panel-body"><div class="sf-row">{badges}</div></div>')
        + _fpanel("Buttons", f'<div class="panel-body">{buttons}</div>')
        + _fpanel("Form fields", f'<div class="panel-body">{fields}</div>')
        + _fpanel("Pipeline strip", f'<div class="panel-body">{pipeline}</div>')
        + "</div>"
    )
    right = (
        '<div class="stack">'
        + _fpanel("Notices", f'<div class="panel-body">{notices}</div>')
        + _fpanel("Dots &amp; pills", f'<div class="panel-body">{pills}</div>')
        + _fpanel("Segmented control &amp; chips", f'<div class="panel-body">{controls}</div>')
        + _fpanel("Table", f'<div class="panel-body">{table}</div>')
        + _fpanel("Stepper", f'<div class="panel-body">{stepper}</div>')
        + _fpanel("Scheduler rows &amp; key / value", f'<div class="panel-body">{sched}{kv}</div>')
        + "</div>"
    )
    return '<div class="sf-grid">' + left + right + "</div>"


# --- styleframe chrome (docs artifact only; never shipped in the app) ---------

_SF_CSS = """
/* ---------- styleframe chrome (docs only) ---------- */
.sf-note { color: var(--muted); font-size: .85rem; margin: .25rem 0 1rem; }
.sf-note code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: var(--surface-2); padding: .1rem .35rem; border-radius: var(--radius-sm); }
.sf-bar { display: flex; flex-wrap: wrap; align-items: center; gap: .25rem;
  margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); }
.sf-tab { font: inherit; font-weight: 600; color: var(--ink-2); background: transparent;
  border: 0; border-bottom: 2px solid transparent; border-radius: 0; padding: .6rem .85rem;
  min-height: 44px; cursor: pointer; }
.sf-tab:hover { color: var(--fg); background: var(--surface-2); }
.sf-tab[aria-current="true"] { color: var(--accent); border-bottom-color: var(--accent); }
.sf-view { display: none; }
.sf-view.is-active { display: block; }
.sf-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1.5rem;
  align-items: start; }
.sf-swatches { display: grid; grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
  gap: .75rem; }
.sf-swatch { display: flex; align-items: center; gap: .6rem; min-width: 0; }
.sf-chip { width: 34px; height: 34px; border-radius: var(--radius); flex: 0 0 auto;
  border: 1px solid var(--border-strong); }
.sf-swatch-text { display: flex; flex-direction: column; min-width: 0; }
.sf-token { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .78rem; }
.sf-desc { color: var(--muted); font-size: .78rem; }
.sf-row { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
@media (max-width: 1040px) { .sf-grid { grid-template-columns: 1fr; } }
"""

_SF_SCRIPT = """<script>
(function () {
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".sf-tab"));
  var views = Array.prototype.slice.call(document.querySelectorAll(".sf-view"));
  function show(key) {
    views.forEach(function (view) {
      view.classList.toggle("is-active", view.id === "sf-" + key);
    });
    tabs.forEach(function (tab) {
      tab.setAttribute("aria-current", tab.dataset.view === key ? "true" : "false");
    });
    window.scrollTo({ top: 0 });
  }
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () { show(tab.dataset.view); });
  });
})();
</script>"""


def render_styleframe() -> str:
    """The whole styleframe as one deterministic HTML document."""
    tabs: list[str] = []
    views: list[str] = []
    pages = render_pages()
    for index, (name, document) in enumerate(pages):
        key = _slug(name)
        current = "true" if index == 0 else "false"
        tabs.append(
            f'<button class="sf-tab" type="button" data-view="{key}" '
            f'aria-current="{current}">{html.escape(name)}</button>'
        )
        cls = "sf-view is-active" if index == 0 else "sf-view"
        views.append(f'<section class="{cls}" id="sf-{key}">{_extract_body(document)}</section>')
    tabs.append(
        '<button class="sf-tab" type="button" data-view="foundations" '
        'aria-current="false">Foundations</button>'
    )
    views.append('<section class="sf-view" id="sf-foundations">' + _foundations() + "</section>")

    document = (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Social Content Factory — styleframe</title>\n"
        f"<style>{_CSS}{_SF_CSS}</style>\n</head>\n<body>\n"
        f"{nav_html('')}\n"
        '<p class="sf-note">Styleframe — every operator page rendered by the app\'s own code, '
        "plus the design foundations. Generated by <code>scripts/build_styleframe.py</code>; "
        "do not edit by hand.</p>\n"
        f'<nav class="sf-bar" aria-label="Styleframe sections">{"".join(tabs)}</nav>\n'
        + "".join(views)
        + "\n"
        + _SF_SCRIPT
        + "\n</body>\n</html>\n"
    )
    return _normalize_tz(document)
