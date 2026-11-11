from research_desk.examiner.letters import classify, parse_references, split_comments

# layout of the SEC's text extracts: indented headings, comment numbers padded with spaces,
# page breaks that repeat the addressee and date
LETTER = """<TEXT>
                                                        Re: Example Corp
                                                            Form 10-K for the Fiscal Year Ended
December 31, 2023
                                                            Filed February 20, 2024
                                                            File No. 001-12345

       Dear Jane Doe:

              We have reviewed your filing and have the following comments.

       Form 10-K for the Fiscal Year Ended December 31, 2023

       Non-GAAP Financial Measures, page 43

   1.                                                   You present Adjusted EBITDA
before net income. Please present the most directly comparable GAAP measure
with equal or greater prominence.
   2.                                                   We note your response to prior
comment 4. Please revise your reconciliation.
 Jane Doe
Example Corp
April 18, 2024
Page 2

Item 7. Management's Discussion and Analysis, page 51

3.       Please quantify the price and volume drivers of revenue growth.

       We remind you that the company and its management are responsible for the accuracy.
"""


def test_classify():
    assert classify(LETTER) == "substantive"
    assert classify("We have completed our review of your filing.") == "closing"
    assert classify("We have not reviewed and will not review your registration statement.") \
        == "no_review"


def test_references_span_wrapped_lines():
    assert parse_references(LETTER) == [
        {"form": "10-K", "period": "2023-12-31", "filed": "2024-02-20"}]


def test_comments_sections_and_follow_ups():
    cs = split_comments(LETTER)
    assert [c.number for c in cs] == [1, 2, 3]
    assert cs[0].section == "Non-GAAP Financial Measures, page 43"
    assert cs[2].section == "Item 7. Management's Discussion and Analysis, page 51"
    assert [c.follow_up for c in cs] == [False, True, False]
    assert "Page 2" not in cs[1].text and "Jane Doe" not in cs[1].text
    assert cs[2].text.startswith("Please quantify") and "remind you" not in cs[2].text
