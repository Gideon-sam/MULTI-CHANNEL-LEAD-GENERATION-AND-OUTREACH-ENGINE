from incubrix_engine.contact_evidence import publisher_contact_hints


def feed(description, published="Wed, 28 Oct 2026 18:00:00 +0000"):
    return (
        '<rss><channel><owner>owner@creator.test</owner><item><title>Making episodes</title>'
        f'<pubDate>{published}</pubDate><description><![CDATA[{description}]]></description>'
        '</item></channel></rss>'
    )


def test_dated_owned_business_invitation_is_extracted_without_approval():
    rows = publisher_contact_hints(
        feed('<p>Business inquiries: hello@creator.test</p>'),
        'https://creator.test/', set(), '2026-10-29',
    )
    assert len(rows) == 1
    assert rows[0]['contact_active_date'] == '2026-10-28'
    assert rows[0]['contact'] == 'hello@creator.test'
    assert rows[0]['contact_quote'] in feed('<p>Business inquiries: hello@creator.test</p>')
    assert rows[0]['status'] == 'HINT_REQUIRES_CREATOR_SPECIFIC_REVIEW'


def test_owner_guest_provider_future_and_old_contact_do_not_pass():
    examples = [
        feed('A recent episode without a business invitation.'),
        feed('Business inquiries: guest@unrelated.test'),
        feed('Contact us: mailbox@mg-eu.acast.com'),
        feed('Contact us: hello@creator.test', 'Wed, 28 Oct 2020 18:00:00 +0000'),
        feed('Contact us: hello@creator.test', 'Wed, 28 Oct 2030 18:00:00 +0000'),
        feed('Guest contact us: hello@creator.test'),
    ]
    for raw in examples:
        assert not publisher_contact_hints(raw, 'https://creator.test', set(), '2026-10-29')


def test_external_email_requires_existing_official_website_association():
    raw = feed('For sponsorship inquiries email creator@gmail.com')
    assert not publisher_contact_hints(raw, 'https://creator.test', set(), '2026-10-29')
    assert publisher_contact_hints(
        raw, 'https://creator.test', {'creator@gmail.com'}, '2026-10-29'
    )


def test_missing_or_invalid_review_date_produces_no_dated_claim():
    raw = feed('Business inquiries: hello@creator.test')
    for value in ('', 'not-a-date', None):
        assert publisher_contact_hints(raw, 'https://creator.test', set(), value) == []
