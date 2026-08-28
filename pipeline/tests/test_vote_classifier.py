"""
Testy klasifikátoru hlasování (Pilíř A: Ochrana před procedurálními hlasováními).
"""

from psp.vote_classifier import classify_vote, is_valid_vote_mismatch


def test_classify_final_law_reading():
    c1 = classify_vote("Novela z. - trestní zákoník**")
    assert c1.vote_type == "SUBSTANTIVE_FINAL"
    assert c1.is_substantive is True
    assert c1.is_procedural is False

    c2 = classify_vote("Návrh zákona o podpoře bydlení - hlasování jako celek")
    assert c2.vote_type == "SUBSTANTIVE_FINAL"
    assert c2.is_substantive is True

    c3 = classify_vote("Projednání návrhu na vyslovení nedůvěry vládě České republiky")
    assert c3.vote_type == "SUBSTANTIVE_FINAL"
    assert c3.is_substantive is True


def test_classify_amendments():
    c1 = classify_vote("Pozměňovací návrh poslance Nováka k tisku 123")
    assert c1.vote_type == "SUBSTANTIVE_AMENDMENT"
    assert c1.is_substantive is True
    assert c1.is_procedural is False

    c2 = classify_vote("Návrh na zamítnutí předlohy")
    assert c2.vote_type == "SUBSTANTIVE_AMENDMENT"
    assert c2.is_substantive is True


def test_classify_procedural_agenda():
    c1 = classify_vote("Pořad schůze")
    assert c1.vote_type == "PROCEDURAL_AGENDA"
    assert c1.is_procedural is True
    assert c1.is_substantive is False

    c2 = classify_vote("Změna pořadu 10. schůze")
    assert c2.vote_type == "PROCEDURAL_AGENDA"
    assert c2.is_procedural is True

    c3 = classify_vote("Zařazení nového bodu do programu")
    assert c3.vote_type == "PROCEDURAL_AGENDA"
    assert c3.is_procedural is True


def test_classify_procedural_adjournment_and_time():
    c1 = classify_vote("Přerušení schůze do 14:00")
    assert c1.vote_type == "PROCEDURAL_ADJOURNMENT"
    assert c1.is_procedural is True

    c2 = classify_vote("Návrh na jednání po 21. hodině")
    assert c2.vote_type == "PROCEDURAL_ADJOURNMENT"
    assert c2.is_procedural is True

    c3 = classify_vote("Sloučená rozprava k bodům 4 a 5")
    assert c3.vote_type == "PROCEDURAL_ADJOURNMENT"
    assert c3.is_procedural is True


def test_classify_procedural_emergency_and_personnel():
    c1 = classify_vote("Potvrzení trvání stavu legislativní nouze")
    assert c1.vote_type == "PROCEDURAL_EMERGENCY"
    assert c1.is_procedural is True

    c2 = classify_vote("Inf. o ustavení volební komise PS a volbě členů")
    assert c2.vote_type == "PROCEDURAL_PERSONNEL"
    assert c2.is_procedural is True


def test_is_valid_vote_mismatch_blocks_procedural():
    # Poslanec u pultíku odmítá zákon ("PROTI"), ale hlasuje "PRO" u pořadu schůze
    proc_vote = classify_vote("Pořad schůze")
    is_cand, reason = is_valid_vote_mismatch("PROTI", "PRO", proc_vote)
    assert is_cand is False
    assert "Procedurální hlasování" in reason


def test_is_valid_vote_mismatch_detects_real_substantive():
    # Poslanec u pultíku odmítá zákon ("PROTI"), ale hlasuje "PRO" u finálního čtení
    law_vote = classify_vote("Novela z. - trestní zákoník**")
    is_cand, reason = is_valid_vote_mismatch("PROTI", "PRO", law_vote)
    assert is_cand is True
    assert "Meritorní rozpor" in reason


def test_is_valid_vote_mismatch_handles_consistent():
    law_vote = classify_vote("Novela z. - trestní zákoník**")
    is_cand, reason = is_valid_vote_mismatch("PRO", "PRO", law_vote)
    assert is_cand is False
    assert "shoda" in reason
