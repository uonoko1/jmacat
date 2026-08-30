"""The Japanese README must not drift out of sync with the English one.

`README.ja.md` is not a courtesy translation: it is what this project's first
users will actually read, so a fact that is fixed in one README and left stale
in the other is a defect, not an inconsistency of style.

What this file does *not* do is compare the two documents as prose. They are
deliberately not sentence-for-sentence parallel — the Japanese version quotes
JMA's own attribution wording, which exists only in Japanese, while the English
version has to say that its examples are the author's rendering. A test that
demanded structural equality would fail on exactly the difference that makes
the Japanese version correct, and the only way to keep it green would be to
make one of the two documents worse.

So the guard is scoped to the claims where drift is silently harmful:

* the **safety statement** issue #12 requires in both READMEs;
* the **numbers and identifiers** that a reader might act on — the newest
  published year, the record count, the decoded coordinates of the worked
  example, the JMA attribution obligations;
* the **cross-links**, which a reader uses to get from one document to the
  other and which no other test would catch once broken.

Each check names the fact it is protecting, so a failure says what to fix
rather than "the READMEs differ".
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
README_EN = _ROOT / "README.md"
README_JA = _ROOT / "README.ja.md"


def _en() -> str:
    return README_EN.read_text("utf-8")


def _ja() -> str:
    return README_JA.read_text("utf-8")


def test_the_two_readmes_link_to_each_other() -> None:
    """A reader who lands on the wrong one must be one click from the right one.

    The link must be a real markdown link to the top of the other document, so
    the check matches the link target rather than the bare filename. A
    substring test for "README.md" passed with the language switcher deleted:
    the Japanese README also mentions README.md in its deep links to the
    schema sections, so the name is present whether or not the switcher is.
    """
    assert "](README.ja.md)" in _en(), "the English README has no link to README.ja.md"
    assert "](README.md)" in _ja(), (
        "the Japanese README has no link to the top of README.md"
    )


def test_both_readmes_carry_the_safety_statement() -> None:
    """Issue #12's definition of done, in both languages.

    The English sentence and its Japanese counterpart are checked by their
    load-bearing clauses rather than in full, so that rewording the surrounding
    paragraph does not fail the test while deleting the prohibition does.
    """
    english = _en()
    assert "not a substitute for" in english
    assert "official disaster information" in english
    for clause in ("evacuation decisions", "real-time alerting"):
        assert clause in english, f"the English safety statement lost {clause!r}"

    japanese = _ja()
    assert "公式の防災情報に" in japanese, (
        "the Japanese safety statement lost its subject"
    )
    assert "代わるものではなく" in japanese, (
        "the Japanese safety statement lost its claim"
    )
    for clause in ("避難の判断", "リアルタイムの警報", "使用してはなりません"):
        assert clause in japanese, f"the Japanese safety statement lost {clause!r}"


def test_both_readmes_name_the_same_newest_published_year() -> None:
    """The publication lag is the fact readers most often get wrong.

    If one README is updated when JMA publishes a new year and the other is
    not, a Japanese reader is told the catalog reaches a year it does not.
    """
    assert "2023" in _en()
    assert "2023" in _ja()
    assert "2024" in _en(), "the English README no longer names the absent year"
    assert "2024" in _ja(), "the Japanese README no longer names the absent year"


def test_both_readmes_agree_on_the_worked_example() -> None:
    """The Before/After decoding is the core demonstration of both documents.

    These are the numbers a reader checks the tool against by hand, so a
    typo in either copy discredits it.
    """
    raw_record = "J2023010100080150 012 354059 100 1403927 136 50"
    for name, text in (("English", _en()), ("Japanese", _ja())):
        assert raw_record in text, f"the {name} README lost the raw example record"
        for value in ("35.6765", "140.6545", "257,020"):
            assert value in text, f"the {name} README lost the decoded value {value}"


def test_both_readmes_state_both_attribution_obligations() -> None:
    """Source credit *and* a separate statement that the data was modified.

    Citing the source alone does not satisfy JMA's terms, and this is the part
    most easily dropped when either document is edited. The Japanese README
    must carry JMA's own wording, since that is the text users will copy.
    """
    english = _en()
    assert "PDL1.0" in english or "Public Data License" in english
    assert "processed" in english, "the English README lost the processing obligation"

    japanese = _ja()
    assert "公共データ利用規約" in japanese
    # JMA's own sentence, quoted verbatim from
    # https://www.jma.go.jp/jma/kishou/info/coment.html (read 2026-08-30).
    # It is the sentence that makes the second obligation separate from the
    # first, so it is checked in full rather than by keyword.
    assert (
        "コンテンツを編集・加工等して利用する場合は、上記出典とは別に、"
        "編集・加工等を行ったことを記載してください。"
    ) in japanese, "the Japanese README lost JMA's own processing-disclosure wording"


def test_the_japanese_readme_quotes_jma_rather_than_translating_it() -> None:
    """The copyable examples must be JMA's Japanese, not a back-translation.

    A user pastes these into a paper or a dataset record. A rendering of our
    own would be wrong in a way neither we nor they could see.
    """
    japanese = _ja()
    # RUF001 flags the fullwidth colon and parentheses below as "ambiguous" and
    # would have them replaced with ASCII. They are JMA's own characters,
    # copied from its terms page, and substituting ASCII would make this test
    # assert a string JMA does not publish — which is the exact failure the
    # test exists to prevent. Suppressed deliberately, not for tidiness.
    for example in (
        "出典：気象庁ホームページ　（当該ページのURL）",  # noqa: RUF001
        "気象庁「図・写真等の名称」 （当該ページのURL）を加工して作成",  # noqa: RUF001
        "気象庁「○○調査」をもとに△△株式会社作成",
    ):
        assert example in japanese, (
            f"the Japanese README lost JMA's example {example!r}"
        )


def test_the_japanese_readme_points_at_sections_the_english_one_has() -> None:
    """The Japanese README defers to the English one for the schema.

    It links by anchor, and a renamed English heading would leave those links
    pointing at nothing. GitHub derives an anchor from the heading text, so the
    check reconstructs the anchors the English headings actually produce.
    """
    headings = re.findall(r"^## (.+)$", _en(), re.M)
    anchors = {
        re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
        for heading in headings
    }
    for target in re.findall(r"\(README\.md#([^)]+)\)", _ja()):
        assert target in anchors, (
            f"README.ja.md links to README.md#{target}, "
            f"which no English heading produces (have: {sorted(anchors)})"
        )
