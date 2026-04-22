import unittest

from sources.translation import (
    count_negation_signals,
    is_high_risk_headline,
    normalize_title_for_translation,
    translation_preserves_conditionals,
    translation_preserves_core_meaning,
    translation_preserves_negation,
)


class TranslationTests(unittest.TestCase):
    def test_normalize_title_removes_known_publisher_suffix(self):
        self.assertEqual(
            normalize_title_for_translation("Trump denies ceasefire deal - Reuters"),
            "Trump denies ceasefire deal",
        )

    def test_normalize_title_keeps_meaningful_tail_clause(self):
        self.assertEqual(
            normalize_title_for_translation("Trump says he will not strike Iran - if talks continue"),
            "Trump says he will not strike Iran - if talks continue",
        )

    def test_count_negation_signals_detects_english_negation(self):
        self.assertGreaterEqual(count_negation_signals("Trump will not sign the deal"), 1)

    def test_translation_guard_rejects_lost_negation(self):
        self.assertFalse(
            translation_preserves_negation(
                "Trump will not strike Iran",
                "트럼프가 이란을 타격할 것이다",
            )
        )

    def test_translation_guard_accepts_preserved_negation(self):
        self.assertTrue(
            translation_preserves_negation(
                "Trump denies reports of a ceasefire",
                "트럼프는 휴전 보도를 부인했다",
            )
        )

    def test_translation_guard_rejects_lost_condition(self):
        self.assertFalse(
            translation_preserves_conditionals(
                "Trump refuses to lift blockade without Iran deal",
                "트럼프가 봉쇄 해제로 이란 협상을 끝낸다",
            )
        )

    def test_high_risk_headline_detects_without_condition(self):
        self.assertTrue(
            is_high_risk_headline("Trump refuses to lift blockade without Iran deal")
        )

    def test_core_meaning_guard_accepts_preserved_condition(self):
        self.assertTrue(
            translation_preserves_core_meaning(
                "Trump refuses to lift blockade without Iran deal",
                "트럼프는 이란 합의 없이는 봉쇄를 해제하지 않겠다고 밝혔다",
            )
        )

    def test_core_meaning_guard_rejects_reversed_meaning(self):
        self.assertFalse(
            translation_preserves_core_meaning(
                "Trump refuses to lift blockade without Iran deal",
                "트럼프: 호르무즈 봉쇄 해제로 이란 협상 종료",
            )
        )


if __name__ == "__main__":
    unittest.main()
