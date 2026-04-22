import unittest

from utils import is_question_headline


class QuestionFilterTests(unittest.TestCase):
    def test_detects_question_mark_headline(self):
        self.assertTrue(is_question_headline("Will Trump lift the Hormuz blockade?"))

    def test_detects_english_question_without_question_mark(self):
        self.assertTrue(is_question_headline("Could Trump strike Iran without Congress approval"))

    def test_detects_korean_question_headline(self):
        self.assertTrue(is_question_headline("트럼프가 호르무즈 봉쇄를 해제할까"))

    def test_non_question_statement_is_not_filtered(self):
        self.assertFalse(is_question_headline("Trump refuses to lift Hormuz blockade without Iran deal"))


if __name__ == "__main__":
    unittest.main()
