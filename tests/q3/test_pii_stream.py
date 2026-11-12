from pii_guard import StreamUnmasker, Vault, mask

ORIGINAL = "請撥 0912345678 或寄信到 amy@example.com [備註] 謝謝"


def masked_reply():
    vault = Vault()
    masked = mask(ORIGINAL, vault)
    assert masked == "請撥 [PHONE_1] 或寄信到 [EMAIL_1] [備註] 謝謝"
    return masked, vault


def stream(chunks, vault):
    unmasker = StreamUnmasker(vault)
    return "".join(unmasker.feed(chunk) for chunk in chunks) + unmasker.flush()


def test_placeholder_split_at_every_position_is_restored():
    masked, vault = masked_reply()
    for cut in range(len(masked) + 1):
        assert stream([masked[:cut], masked[cut:]], vault) == ORIGINAL, cut


def test_one_character_chunks_are_restored():
    masked, vault = masked_reply()
    assert stream(list(masked), vault) == ORIGINAL


def test_complete_placeholder_is_released_without_waiting_for_more():
    masked, vault = masked_reply()
    unmasker = StreamUnmasker(vault)
    assert unmasker.feed("請撥 [PHONE_1]") == "請撥 0912345678"


def test_unfinished_placeholder_is_released_on_flush():
    _, vault = masked_reply()
    unmasker = StreamUnmasker(vault)
    assert unmasker.feed("結尾是 [PHONE_") == "結尾是 "
    assert unmasker.flush() == "[PHONE_"
