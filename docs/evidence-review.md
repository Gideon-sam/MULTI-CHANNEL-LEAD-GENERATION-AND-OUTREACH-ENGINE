# Creator-specific evidence review

Every item in `config/reviews.json` is an explicit review decision. The file begins empty because automated research is insufficient to certify every requirement. Use `schema_version: 1` and a `reviews` array. Do not create approval records merely to make validation green.

Required fields for each review:

| Field | Evidence needed |
|---|---|
| `stable_creator_id` | Exact `apple-podcast:<actual ID>` from the research queue |
| `creator_identity_key` | A stable canonical public URL shared across all of that creator's shows (normally the official creator site/profile) |
| `creator_name`, `country_iso2` | Creator's identity and actual base; storefront country and ccTLD alone are insufficient |
| `reviewer`, `reviewed_at`, `rationale` | Who performed the review, ISO date/time, and why these sources establish the claims |
| `best_channel`, `channel_handle_or_url` | Exact business contact copied from a public source; no address guessing or SMTP probing |
| `backup_channel`, `backup_handle_or_url` | A second verified contact route; a generic platform name is not enough |
| `contact_active_date` | Actual dated public evidence within 60 days tying the creator to the contact channel |
| `need_description` | A concrete content workflow need supported by the source; distinguish observed workload from a stated pain point |
| `proofs` | The evidence map described below |

`proofs` requires `identity`, `country`, `language`, `commercial`, `need`, `contact`, `contact_activity` and `backup`. Each value has `url` and `quote` fields. Quotes must be exact short excerpts (at most 400 characters per entry); use only as much as necessary and respect each source's quotation limits. The email contact excerpt must include the exact email. Review the surrounding context as well as the snippet.

The engine fetches all cited pages plus the official profile and recent-content URL. It checks excerpt presence, HTTP success, freshness and degraded-cache state; it stores retrieval times and body hashes. A page returning 200 is not proof of semantics: login walls, soft 404s, guest bios, comments, addresses for another entity, and hosting-provider emails must fail the review.

Additional reviewer checks:

1. Confirm the person is the actual creator, not their network, agency, directory or guest.
2. Open recent content and confirm it belongs to the same creator, is mainly English and satisfies the activity threshold.
3. Confirm commercial activity belongs to that creator; an interview merely mentioning a course does not prove the creator sells one.
4. Explain the specific editing, repurposing, publishing or team workflow evidence. Publishing often alone does not prove dissatisfaction.
5. Confirm the business contact is intentionally published for the proposed purpose and has a dated public activity signal. A feed-owner technical mailbox alone is insufficient.
6. Check the backup route and creator identity across other shows to prevent duplicates.
7. Review all three messages for accurate content claims, sender identity and opt-out.

If a page blocks automated access, record the restriction. Do not bypass it. An unavailable source cannot pass this automated evidence check. You may choose another independently sufficient public or consented source and document that choice.

The review contract is intentionally stricter than extracting a possible email from a feed. This protects the assessment's random-audit quality threshold.
