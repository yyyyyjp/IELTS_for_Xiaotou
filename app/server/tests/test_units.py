from __future__ import annotations

from services import dictation, grading, srs


def test_normalize_case_space_and_punctuation():
    assert grading.normalize("  Deposit. ") == "deposit"
    assert grading.normalize("The deposit, is refundable!") == "the deposit is refundable"
    assert grading.normalize("Don’t cancel") == "don't cancel"
    assert grading.normalize("mixed—ability") == "mixed ability"
    assert grading.normalize("mixed - ability") == "mixed ability"


def test_compare_single_blank():
    assert grading.compare(["deposit"], "Deposit.")["ok"] is True
    assert grading.compare(["deposit"], "deposite")["ok"] is False
    assert grading.compare(["15-year-olds"], "15 year olds")["ok"] is True


def test_compare_multi_blank_pads_missing():
    r = grading.compare(["deposit", "refundable"], ["deposit"])
    assert r["ok"] is False
    assert r["parts"] == [True, False]


def test_compare_ignores_extra_input():
    r = grading.compare(["deposit"], ["deposit", "extra"])
    assert r["ok"] is True
    assert len(r["parts"]) == 1


def test_srs_first_good_is_one_day():
    now = 1_700_000_000
    out = srs.review({"ease": 2.4, "interval_days": 0, "reps": 0, "lapses": 0}, "good", now)
    assert out["interval_days"] == 1
    assert out["due_at"] == now + srs.DAY
    assert out["state"] == "review"


def test_srs_second_good_is_three_days_then_grows():
    now = 1_700_000_000
    second = srs.review({"ease": 2.4, "interval_days": 1, "reps": 1, "lapses": 0}, "good", now)
    assert second["interval_days"] == 3

    third = srs.review({"ease": 2.4, "interval_days": 3, "reps": 2, "lapses": 0}, "good", now)
    assert third["interval_days"] == 7.2


def test_srs_again_returns_to_learning():
    now = 1_700_000_000
    out = srs.review({"ease": 2.4, "interval_days": 10, "reps": 4, "lapses": 0}, "again", now)
    assert out["state"] == "learning"
    assert out["lapses"] == 1
    assert out["ease"] == 2.2
    assert out["due_at"] == now + srs.RELEARN_SECONDS


def test_srs_interval_is_capped_and_due_matches():
    now = 1_700_000_000
    out = srs.review({"ease": 2.5, "interval_days": 300, "reps": 9, "lapses": 0}, "good", now)
    assert out["interval_days"] == srs.MAX_INTERVAL
    assert out["due_at"] == now + int(srs.MAX_INTERVAL * srs.DAY)


def test_srs_easy_bonus_and_ease_floor():
    now = 1_700_000_000
    easy = srs.review({"ease": 2.4, "interval_days": 10, "reps": 3, "lapses": 0}, "easy", now)
    assert easy["interval_days"] == 31.2
    assert easy["ease"] == 2.5

    floor = srs.review({"ease": 1.35, "interval_days": 5, "reps": 2, "lapses": 3}, "again", now)
    assert floor["ease"] == srs.MIN_EASE


def test_srs_rejects_unknown_grade():
    try:
        srs.review({"ease": 2.4, "interval_days": 1, "reps": 1, "lapses": 0}, "perfect", 0)
    except ValueError:
        return
    raise AssertionError("应当拒绝未知档位")


def test_blank_picker_skips_proper_nouns_digits_and_function_words():
    spans = dictation.pick_blanks(
        "Shakespeare's play was published in 1623 with great success.", set(), 1
    )
    assert [s.word for s in spans] == ["published"]


def test_public_item_hides_answers_in_text_and_hint():
    item = dictation.sentence_item(
        "p", "s1", "The deposit is refundable if you cancel early.", "", set()
    )
    public = item.public()
    assert public["blankLengths"] == [10]
    assert "refundable" not in public["text"]
    assert public["text"].count("{{}}") == 1


def test_word_item_hint_context_is_masked():
    row = {
        "word": "deposit",
        "lemma": "deposit",
        "gloss": "押金",
        "pos": "n.",
        "phonetic": "",
    }
    item = dictation.vocab_word_item(
        "p", row, "word", "The landlord kept the deposit.", "房东留下了押金。"
    )
    public = item.public()
    assert "deposit" not in public["hint"]["context"]
    assert "{{}}" in public["hint"]["context"]
