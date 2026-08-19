from app.ebay.classifier import (
    CLASS_OTHER_GRADED,
    CLASS_PSA,
    CLASS_RAW,
    CLASS_REJECTED,
    classify_listing,
)


def test_raw_mp_overrides_non_specific_ebay_condition():
    result = classify_listing(
        "1999 Pokemon Game Base Set Charizard 4/102 Holo Foil MP Unlimited WOTC Rare",
        "New",
    )

    assert result["classification"] == CLASS_RAW
    assert result["raw_condition"] == "MP"
    assert result["analytics_bucket"] == "RAW"
    assert result["signals"]["card_numbers"] == ["4/102"]
    assert "unlimited" in result["signals"]["variant_flags"]


def test_psa_grade_is_extracted():
    result = classify_listing(
        "1999 Pokemon Base Set Charizard #4/102 Holo Rare PSA 2 GOOD WOTC Unlimited",
        "Graded",
    )

    assert result["classification"] == CLASS_PSA
    assert result["grading_company"] == "PSA"
    assert result["grade"] == 2
    assert result["analytics_bucket"] == "PSA_2"
    assert result["include"] is True


def test_cgc_is_other_graded():
    result = classify_listing(
        "1999 Pokemon Base Set Charizard Holo CGC 7.5 #4/102",
        "Graded",
    )

    assert result["classification"] == CLASS_OTHER_GRADED
    assert result["grading_company"] == "CGC"
    assert result["grade"] == 7.5
    assert result["include"] is True


def test_big_three_set_is_rejected():
    result = classify_listing(
        "charizard base set 4/102 Pokemon Big 3 Set",
        "Ungraded",
    )

    assert result["classification"] == CLASS_REJECTED
    assert result["include"] is False
    assert "multi_card_bundle" in result["reasons"]


def test_restored_card_is_rejected():
    result = classify_listing(
        "Pokemon Charizard Base Set Holo Unlimited 4/102 RESTORED READ DESC",
        "Ungraded",
    )

    assert result["classification"] == CLASS_REJECTED
    assert "altered_or_restored" in result["reasons"]


def test_psa_10_candidate_is_raw_when_ungraded():
    result = classify_listing(
        "Charizard Base Set 4/102 NM PSA 10 Candidate",
        "Ungraded",
    )

    assert result["classification"] == CLASS_RAW
    assert result["grade"] is None
    assert result["raw_condition"] == "NM"
    assert "speculative_grading_language" in result["reasons"]


def test_unknown_graded_company_is_not_treated_as_raw():
    result = classify_listing(
        "1999 Pokemon Charizard Base Set 4/102 Holo",
        "Graded",
    )

    assert result["classification"] == CLASS_OTHER_GRADED
    assert result["include"] is False
    assert result["needs_review"] is True


def test_reprint_is_flagged_for_card_match_instead_of_hard_rejected():
    result = classify_listing(
        "Pokemon Charizard Base Set 4/102 Reprint NM",
        "Ungraded",
    )

    assert result["classification"] == CLASS_RAW
    assert result["include"] is True
    assert result["needs_review"] is True
    assert "reprint" in result["signals"]["variant_flags"]


def test_mojibake_title_still_classifies():
    result = classify_listing(
        "PokÃ©mon Charizard Base Set Holo Unlimited Rare Card 4/102",
        "Ungraded",
    )

    assert result["classification"] == CLASS_RAW
    assert result["signals"]["card_numbers"] == ["4/102"]


def test_language_and_variant_signals_are_extracted():
    result = classify_listing(
        "1999 Japanese Charizard Base Set 4/102 1st Edition Holo PSA 9",
        "Graded",
    )

    assert result["signals"]["language"] == "Japanese"
    assert "first_edition" in result["signals"]["variant_flags"]
    assert "holo" in result["signals"]["variant_flags"]
    assert result["analytics_bucket"] == "PSA_9"
